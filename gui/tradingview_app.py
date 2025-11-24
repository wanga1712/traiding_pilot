"""
Главное приложение TradingView-style для анализа криптовалют.

Структура:
- Левая панель: список инструментов (двойной клик для выбора)
- Правая панель: свечной график
- Нижняя панель: выбор таймфрейма
"""

import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QSplitter, QLabel, QPushButton,
    QHBoxLayout as QHBox, QFrame
)
from PyQt5.QtCore import Qt, QSize, QTimer, pyqtSignal
from threading import Thread
from PyQt5.QtGui import QFont, QColor, QPalette
from PyQt5.QtWidgets import QDesktopWidget
from loguru import logger
import pandas as pd
import mplfinance as mpf
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

from gui.ui_config import UIConfig
from gui.data_fetcher import DataFetcher
from crypto_trading_bot.database.data_import import DataImport
from crypto_trading_bot.trading.data_updater import DataUpdater
from PyQt5.QtCore import QThread, pyqtSignal


class CandlestickChartWidget(QWidget):
    """
    Виджет для отображения свечного графика.
    """
    
    def __init__(self, parent=None):
        """
        Инициализация виджета графика.
        """
        super().__init__(parent)
        self.data_fetcher = DataFetcher()
        self.data_import = DataImport()
        
        # Создаем фигуру matplotlib с темной темой (увеличенный размер для высокого разрешения)
        self.figure = Figure(figsize=(20, 12), facecolor=UIConfig.CHART_BACKGROUND_COLOR, dpi=100)
        self.canvas = FigureCanvas(self.figure)
        
        # Добавляем панель навигации для прокрутки графика
        self.toolbar = NavigationToolbar(self.canvas, self)
        
        # Настраиваем layout
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        layout.addWidget(self.toolbar)  # Добавляем панель навигации
        self.setLayout(layout)
        
        # Применяем стиль
        self.setStyleSheet(f"background-color: {UIConfig.CHART_BACKGROUND_COLOR};")
        
        # Текущие данные
        self.current_instrument = None
        self.current_timeframe = "1d"
        
    def plot_candlestick(self, instrument_symbol: str, timeframe_code: str):
        """
        Отрисовывает свечной график для указанного инструмента и таймфрейма.
        
        Параметры:
            instrument_symbol: Символ инструмента (например, 'BTCUSDT').
            timeframe_code: Код таймфрейма из БД (например, '1d', '1h', '5m').
        """
        def apply_price_formatter(axis):
            """
            Настраивает форматирование оси Y для отображения полных цен.
            """
            if axis is None:
                return
            axis.ticklabel_format(style='plain', axis='y', useOffset=False)

            def price_formatter(value, _):
                return f"{value:,.2f}".replace(",", " ")

            axis.yaxis.set_major_formatter(FuncFormatter(price_formatter))

        try:
            logger.info(f"Отрисовка графика для {instrument_symbol} на таймфрейме {timeframe_code}")
            
            # Получаем ID инструмента и таймфрейма
            instruments = self.data_fetcher.get_instruments()
            instrument = next((inst for inst in instruments if inst.symbol == instrument_symbol), None)
            
            if not instrument:
                logger.error(f"Инструмент {instrument_symbol} не найден")
                return
            
            timeframes = self.data_fetcher.get_timeframes()
            # Проверяем разные варианты названий таймфрейма
            timeframe = None
            for tf in timeframes:
                tf_name = getattr(tf, 'interval_name', None) or getattr(tf, 'name', None) or getattr(tf, 'timeframe_name', None)
                if tf_name == timeframe_code:
                    timeframe = tf
                    break
            
            if not timeframe:
                logger.error(f"Таймфрейм {timeframe_code} не найден")
                return
            
            # Получаем данные из БД
            price_data = self.data_import.get_price_data(instrument.id, timeframe.id)
            
            if not price_data:
                logger.warning(f"Нет данных для {instrument_symbol} на таймфрейме {timeframe_code}")
                return
            
            # ЛОГИРУЕМ ПЕРВЫЕ ДАННЫЕ ИЗ БД ДЛЯ ОТЛАДКИ
            logger.info(f"Получено {len(price_data)} записей из БД")
            if len(price_data) > 0:
                first_record = price_data[0]
                logger.info(f"Первый элемент из БД: {first_record}")
                logger.info(f"Тип первого элемента: {type(first_record)}")
                logger.info(f"Тип candle_time (первый элемент кортежа): {type(first_record[0])}, значение: {first_record[0]}")
                if len(price_data) > 1:
                    logger.info(f"Второй элемент: {price_data[1]}")
            
            # Преобразуем в DataFrame
            # Порядок колонок из БД: candle_time, open, close, high, low, volume
            
            # Преобразуем данные, правильно обрабатывая timestamp
            timestamps = []
            for i, data in enumerate(price_data):
                ts = data[0]
                
                # Логируем первые несколько значений для отладки
                if i < 5:
                    logger.info(f"[{i}] Тип timestamp: {type(ts)}, значение: {repr(ts)}")
                
                # PostgreSQL возвращает datetime объекты или строки
                # Преобразуем напрямую в pd.Timestamp
                try:
                    # Если это datetime объект Python (из PostgreSQL psycopg2)
                    if hasattr(ts, 'year') and hasattr(ts, 'month') and hasattr(ts, 'day'):
                        # Это datetime объект, преобразуем в pd.Timestamp
                        ts_converted = pd.Timestamp(ts)
                        if i < 5:
                            logger.info(f"[{i}] Преобразовано из datetime: {ts} -> {ts_converted}")
                    # Если это строка
                    elif isinstance(ts, str):
                        ts_converted = pd.to_datetime(ts)
                        if i < 5:
                            logger.info(f"[{i}] Преобразовано из строки: {ts} -> {ts_converted}")
                    # Если это число (маловероятно для PostgreSQL TIMESTAMP)
                    elif isinstance(ts, (int, float)):
                        logger.warning(f"[{i}] Timestamp - это число: {ts}, возможно ошибка в БД")
                        # Пробуем интерпретировать как Unix timestamp
                        if ts > 1e12:  # Микросекунды
                            ts_converted = pd.Timestamp.fromtimestamp(ts / 1e6, tz='UTC')
                        elif ts > 1e10:  # Миллисекунды
                            ts_converted = pd.Timestamp.fromtimestamp(ts / 1000.0, tz='UTC')
                        else:  # Секунды
                            ts_converted = pd.Timestamp.fromtimestamp(ts, tz='UTC')
                        logger.info(f"[{i}] Преобразовано из числа: {ts} -> {ts_converted}")
                    else:
                        # Для всех остальных случаев используем pd.to_datetime
                        ts_converted = pd.to_datetime(ts)
                        if i < 5:
                            logger.info(f"[{i}] Преобразовано через pd.to_datetime: {ts} -> {ts_converted}")
                    
                    # Проверяем, что дата разумная
                    if ts_converted.year < 2020:
                        logger.error(f"[{i}] ПОДОЗРИТЕЛЬНАЯ ДАТА: {ts_converted}, исходное: {ts}, тип: {type(ts)}")
                    
                    timestamps.append(ts_converted)
                except Exception as e:
                    logger.error(f"[{i}] Ошибка преобразования timestamp {ts} (тип: {type(ts)}): {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    continue
            
            if not timestamps:
                logger.error("Не удалось преобразовать ни одного timestamp")
                return
            
            # Проверяем результат
            logger.info(f"Первый timestamp после преобразования: {timestamps[0]} (год: {timestamps[0].year})")
            logger.info(f"Последний timestamp: {timestamps[-1]} (год: {timestamps[-1].year})")
            
            df = pd.DataFrame({
                'timestamp': timestamps,
                'open': [float(data[1]) for data in price_data],
                'close': [float(data[2]) for data in price_data],
                'high': [float(data[3]) for data in price_data],
                'low': [float(data[4]) for data in price_data],
                'volume': [float(data[5]) for data in price_data]
            })
            
            # Устанавливаем timestamp как индекс
            df.set_index('timestamp', inplace=True)
            
            # ВАЖНО: Убеждаемся, что индекс - это DatetimeIndex
            if not isinstance(df.index, pd.DatetimeIndex):
                logger.warning("Индекс не DatetimeIndex, преобразуем...")
                df.index = pd.to_datetime(df.index)
            
            # Проверяем индекс после установки
            logger.info(f"Индекс DataFrame (первые 3): {df.index[:3].tolist()}")
            logger.info(f"Индекс DataFrame (последние 3): {df.index[-3:].tolist()}")
            logger.info(f"Тип индекса: {type(df.index)}")
            logger.info(f"Год первого элемента индекса: {df.index[0].year}")
            logger.info(f"Год последнего элемента индекса: {df.index[-1].year}")
            
            # Сортируем по времени
            df.sort_index(inplace=True)
            
            # ПРОВЕРЯЕМ DataFrame перед передачей в mplfinance
            logger.info(f"DataFrame индекс (первые 3): {df.index[:3].tolist()}")
            logger.info(f"DataFrame индекс (последние 3): {df.index[-3:].tolist()}")
            logger.info(f"Тип индекса: {type(df.index)}")
            logger.info(f"Тип первого элемента индекса: {type(df.index[0])}")
            
            # Убеждаемся, что индекс - это DatetimeIndex
            if not isinstance(df.index, pd.DatetimeIndex):
                logger.warning("Индекс не DatetimeIndex, преобразуем...")
                df.index = pd.to_datetime(df.index)
                logger.info(f"После преобразования: {type(df.index)}, первые значения: {df.index[:3].tolist()}")
            
            # Ограничиваем количество свечей для отображения в зависимости от таймфрейма
            # Для минутных таймфреймов ограничиваем сильнее, чтобы не перегружать график и не вызывать падение программы
            max_candles = {
                '1m': 200,   # Последние 200 минутных свечей (~3 часа) - уменьшено для предотвращения падения
                '3m': 300,   # Последние 300 свечей (~15 часов)
                '5m': 300,   # Последние 300 свечей (~25 часов)
                '15m': 400,  # Последние 400 свечей (~4 дня)
                '30m': 400,  # Последние 400 свечей (~8 дней)
                '1h': 500,   # Последние 500 свечей (~20 дней)
                '2h': 400,
                '4h': 300,
                '6h': 300,
                '12h': 300,
                '1d': 500,   # Последние 500 дней
                '1w': 200,
                '1mo': 100,
            }
            
            limit = max_candles.get(timeframe_code, 500)
            if len(df) > limit:
                df = df.tail(limit)
                logger.info(f"Ограничено до последних {limit} свечей для таймфрейма {timeframe_code}")
            
            # Переименовываем колонки для mplfinance (должны быть с заглавной буквы)
            df.rename(columns={
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'close': 'Close',
                'volume': 'Volume'
            }, inplace=True)
            
            # Проверяем, что все необходимые колонки есть
            required_columns = ['Open', 'High', 'Low', 'Close', 'Volume']
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                logger.error(f"Отсутствуют колонки: {missing_columns}")
                return
            
            # Проверяем, что данные не пустые
            if df.empty:
                logger.warning(f"DataFrame пустой для {instrument_symbol} на {timeframe_code}")
                return
            
            # ВАЖНО: Конвертируем время в локальный часовой пояс системы
            import pytz
            from datetime import datetime
            
            # Определяем локальный часовой пояс системы автоматически
            try:
                # Используем системный локальный часовой пояс через datetime
                local_now = datetime.now()
                # Получаем timezone из текущего времени
                local_tz = local_now.astimezone().tzinfo
                
                # Если timezone не определен, используем pytz для определения
                if local_tz is None or str(local_tz) == 'None':
                    # Пробуем определить по смещению
                    import time
                    local_tz_offset = -time.timezone if (time.daylight == 0) else -time.altzone
                    
                    # Определяем часовой пояс по смещению (для России обычно UTC+3)
                    if local_tz_offset == 10800:  # UTC+3 (Москва)
                        local_tz = pytz.timezone('Europe/Moscow')
                    elif local_tz_offset == 14400:  # UTC+4
                        local_tz = pytz.timezone('Europe/Samara')
                    elif local_tz_offset == 7200:  # UTC+2
                        local_tz = pytz.timezone('Europe/Kaliningrad')
                    else:
                        # По умолчанию используем Москву
                        local_tz = pytz.timezone('Europe/Moscow')
                        logger.info(f"Не удалось определить часовой пояс автоматически, используем Москву (UTC+3)")
                else:
                    # Если timezone определен, но это не pytz объект, конвертируем
                    if not isinstance(local_tz, pytz.BaseTzInfo):
                        # Пробуем найти соответствующий pytz timezone
                        local_tz = pytz.timezone('Europe/Moscow')  # По умолчанию
            except Exception as e:
                logger.warning(f"Ошибка определения часового пояса: {e}, используем Москву")
                local_tz = pytz.timezone('Europe/Moscow')  # Fallback на Москву
            
            logger.info(f"Используется часовой пояс: {local_tz}")
            
            # Если индекс без timezone, предполагаем что это UTC и локализуем
            if df.index.tz is None:
                logger.info("Индекс без timezone, предполагаем UTC и конвертируем в локальный часовой пояс")
                df.index = df.index.tz_localize('UTC').tz_convert(local_tz)
            else:
                # Если есть timezone, конвертируем в локальный
                logger.info(f"Индекс с timezone {df.index.tz}, конвертируем в локальный часовой пояс")
                df.index = df.index.tz_convert(local_tz)
            
            # ВАЖНО: Убираем timezone из индекса для mplfinance
            # mplfinance может не работать с timezone-aware datetime
            logger.info("Убираем timezone из индекса DataFrame для mplfinance (после конвертации в локальный часовой пояс)")
            df.index = df.index.tz_localize(None)
            
            logger.info(f"Первый timestamp после конвертации: {df.index[0]} (локальное время)")
            logger.info(f"Последний timestamp: {df.index[-1]} (локальное время)")
            
            # Проверяем данные на наличие NaN и других проблем
            logger.info(f"Проверка данных: Open min={df['Open'].min():.2f}, max={df['Open'].max():.2f}")
            logger.info(f"Проверка данных: High min={df['High'].min():.2f}, max={df['High'].max():.2f}")
            logger.info(f"Проверка данных: Low min={df['Low'].min():.2f}, max={df['Low'].max():.2f}")
            logger.info(f"Проверка данных: Close min={df['Close'].min():.2f}, max={df['Close'].max():.2f}")
            
            # Проверяем на NaN
            if df.isnull().any().any():
                logger.warning("В данных есть NaN, удаляем...")
                df = df.dropna()
                if df.empty:
                    logger.error("После удаления NaN DataFrame пустой")
                    return
            
            # Проверяем, что все значения положительные
            if (df[['Open', 'High', 'Low', 'Close']] <= 0).any().any():
                logger.error("В данных есть неположительные значения!")
                return
            
            # Очищаем предыдущий график
            self.figure.clear()
            
            # Создаем стиль для свечей (TradingView стиль)
            mc = mpf.make_marketcolors(
                up=UIConfig.CANDLE_BULLISH_COLOR,
                down=UIConfig.CANDLE_BEARISH_COLOR,
                edge='inherit',
                wick='inherit',
                volume='in'
            )
            
            style = mpf.make_mpf_style(
                marketcolors=mc,
                gridstyle='-',
                gridcolor=UIConfig.CHART_GRID_COLOR,
                facecolor=UIConfig.CHART_BACKGROUND_COLOR,
                edgecolor=UIConfig.CHART_GRID_COLOR,
                figcolor=UIConfig.CHART_BACKGROUND_COLOR,
                y_on_right=True,  # Цена справа
                rc={'axes.labelcolor': UIConfig.CHART_TEXT_COLOR,
                    'xtick.color': UIConfig.CHART_TEXT_COLOR,
                    'ytick.color': UIConfig.CHART_TEXT_COLOR,
                    'text.color': UIConfig.CHART_TEXT_COLOR}
            )
            
            try:
                # Используем returnfig=True, чтобы получить фигуру и оси обратно
                # НЕ передаем fig или ax - пусть mplfinance создаст свою фигуру
                logger.info(f"Вызов mplfinance.plot с {len(df)} строками данных")
                logger.info(f"Диапазон индекса: {df.index[0]} - {df.index[-1]}")
                logger.info(f"Диапазон цен: {df['Low'].min():.2f} - {df['High'].max():.2f}")
                
                # Логируем данные перед передачей в mplfinance
                logger.info(f"Вызов mplfinance.plot с {len(df)} строками данных")
                logger.info(f"Диапазон индекса: {df.index[0]} - {df.index[-1]}")
                logger.info(f"Диапазон цен: {df['Low'].min():.2f} - {df['High'].max():.2f}")
                logger.info(f"Первые 3 строки DataFrame:\n{df.head(3)}")
                
                fig, axes = mpf.plot(
                    df,
                    type='candle',
                    style=style,
                    volume=False,  # Без объемов
                    show_nontrading=False,
                    warn_too_much_data=1000,
                    returnfig=True
                )
                logger.info("mplfinance.plot выполнен успешно")
                
                # Проверяем, что mplfinance отрисовал график
                if len(axes) == 0:
                    logger.error("mplfinance не создал осей")
                    return
                
                ax_source = axes[0]
                
                # Проверяем, есть ли графические элементы
                num_lines = len(ax_source.lines)
                num_patches = len(ax_source.patches)
                logger.info(f"На оси от mplfinance: {num_lines} линий, {num_patches} патчей")
                
                if num_lines == 0 and num_patches == 0:
                    logger.error("mplfinance не отрисовал график - нет элементов на оси!")
                    logger.info("Пробуем отрисовать график вручную через matplotlib...")
                    
                    # Закрываем временную фигуру
                    import matplotlib.pyplot as plt
                    plt.close(fig)
                    
                    # Отрисовываем график вручную
                    self.figure.clear()
                    ax1 = self.figure.add_subplot(1, 1, 1)
                    
                    # Отрисовываем свечи вручную - оптимизированная версия
                    from matplotlib.patches import Rectangle
                    from matplotlib.dates import date2num
                    import numpy as np
                    
                    # Вычисляем ширину свечи в зависимости от таймфрейма
                    if len(df) > 1:
                        # Вычисляем средний интервал между свечами
                        time_diffs = df.index.to_series().diff().dropna()
                        if len(time_diffs) > 0:
                            avg_time_diff = time_diffs.mean()
                            # Преобразуем в дни для date2num
                            width_days = avg_time_diff.total_seconds() / 86400.0 * 0.7  # 70% от среднего интервала
                        else:
                            # Fallback: используем разумную ширину в зависимости от таймфрейма
                            if '1m' in timeframe_code:
                                width_days = 1.0 / 60.0 / 24.0 * 0.7  # 0.7 минуты в днях
                            elif '3m' in timeframe_code:
                                width_days = 3.0 / 60.0 / 24.0 * 0.7
                            elif '5m' in timeframe_code:
                                width_days = 5.0 / 60.0 / 24.0 * 0.7
                            elif '15m' in timeframe_code:
                                width_days = 15.0 / 60.0 / 24.0 * 0.7
                            elif '30m' in timeframe_code:
                                width_days = 30.0 / 60.0 / 24.0 * 0.7
                            elif '1h' in timeframe_code:
                                width_days = 1.0 / 24.0 * 0.7
                            elif '1d' in timeframe_code or '1D' in timeframe_code:
                                width_days = 0.7  # 0.7 дня
                            elif '1w' in timeframe_code:
                                width_days = 7.0 * 0.7
                            elif '1mo' in timeframe_code:
                                width_days = 30.0 * 0.7
                            else:
                                width_days = 0.6
                    else:
                        width_days = 0.6
                    
                    # Оптимизация: собираем данные в массивы для пакетной отрисовки
                    try:
                        timestamps_num = np.array([date2num(ts) for ts in df.index])
                        opens = df['Open'].values
                        closes = df['Close'].values
                        highs = df['High'].values
                        lows = df['Low'].values
                        
                        # Определяем цвета свечей
                        colors = np.where(closes >= opens, UIConfig.CANDLE_BULLISH_COLOR, UIConfig.CANDLE_BEARISH_COLOR)
                        
                        # Ограничиваем количество свечей для отрисовки, чтобы не перегружать
                        # Для больших таймфреймов (месячных) может быть слишком много данных
                        max_draw = 500  # Максимум свечей для ручной отрисовки
                        if len(df) > max_draw:
                            logger.warning(f"Слишком много свечей ({len(df)}), ограничиваем до {max_draw} для отрисовки")
                            step = len(df) // max_draw
                            indices = list(range(0, len(df), step))[:max_draw]
                            timestamps_num = timestamps_num[indices]
                            opens = opens[indices]
                            closes = closes[indices]
                            highs = highs[indices]
                            lows = lows[indices]
                            colors = colors[indices]
                        
                        # Рисуем тени (wicks) пакетно
                        for i in range(len(timestamps_num)):
                            ax1.plot([timestamps_num[i], timestamps_num[i]], 
                                   [lows[i], highs[i]], 
                                   color=colors[i], linewidth=0.5, alpha=0.8)
                        
                        # Рисуем тела свечей
                        for i in range(len(timestamps_num)):
                            body_bottom = min(opens[i], closes[i])
                            body_height = abs(closes[i] - opens[i])
                            if body_height == 0:
                                body_height = (highs[i] - lows[i]) * 0.1  # 10% от диапазона, но не меньше минимального
                                if body_height == 0:
                                    body_height = (df['High'].max() - df['Low'].min()) * 0.001  # 0.1% от общего диапазона
                            x_pos = timestamps_num[i] - width_days/2
                            
                            body = Rectangle((x_pos, body_bottom), width_days, body_height,
                                            facecolor=colors[i], edgecolor=colors[i], linewidth=0.5)
                            ax1.add_patch(body)
                    except Exception as e:
                        logger.error(f"Ошибка при ручной отрисовке свечей: {e}")
                        import traceback
                        logger.error(traceback.format_exc())
                        return
                    
                    # Устанавливаем пределы
                    # Добавляем справа пространство для будущих свечей (около 10 свечей)
                    future_space = width_days * 10  # Пространство для 10 будущих свечей
                    ax1.set_xlim(date2num(df.index[0]) - width_days, date2num(df.index[-1]) + future_space)
                    ax1.set_ylim(df['Low'].min() * 0.99, df['High'].max() * 1.01)
                    
                    # Настраиваем форматирование дат
                    import matplotlib.dates as mdates
                    from matplotlib.dates import DateFormatter, AutoDateLocator
                    
                    # Форматирование дат как в TradingView
                    if '1d' in timeframe_code or '1D' in timeframe_code:
                        date_format = DateFormatter('%d %b')
                        locator = AutoDateLocator(maxticks=12)
                    elif '1w' in timeframe_code or '1mo' in timeframe_code:
                        # Для недельного и месячного - дата без года
                        date_format = DateFormatter('%d.%m')
                        locator = AutoDateLocator(maxticks=15)
                    elif '1h' in timeframe_code or '2h' in timeframe_code or '4h' in timeframe_code or '6h' in timeframe_code or '12h' in timeframe_code:
                        # Для часовых таймфреймов - дата и время
                        date_format = DateFormatter('%d.%m %H:%M')
                        locator = AutoDateLocator(maxticks=15)
                    else:
                        # Для минутных таймфреймов - только время (часы:минуты)
                        date_format = DateFormatter('%H:%M')
                        locator = AutoDateLocator(maxticks=20)
                    
                    ax1.xaxis.set_major_locator(locator)
                    ax1.xaxis.set_major_formatter(date_format)
                    ax1.tick_params(axis='x', rotation=45, colors=UIConfig.CHART_TEXT_COLOR, labelsize=12)
                    
                    # Настраиваем цвета
                    ax1.set_facecolor(UIConfig.CHART_BACKGROUND_COLOR)
                    ax1.tick_params(axis='y', colors=UIConfig.CHART_TEXT_COLOR, labelsize=14)
                    ax1.spines['bottom'].set_color(UIConfig.CHART_GRID_COLOR)
                    ax1.spines['top'].set_color(UIConfig.CHART_GRID_COLOR)
                    ax1.spines['right'].set_color(UIConfig.CHART_GRID_COLOR)
                    ax1.spines['left'].set_color(UIConfig.CHART_GRID_COLOR)
                    
                    # Размещаем цену справа
                    ax1.yaxis.tick_right()
                    ax1.yaxis.set_label_position('right')
                    apply_price_formatter(ax1)
                    
                    self.figure.subplots_adjust(left=0.05, right=0.95, bottom=0.12, top=0.95)
                    self.canvas.draw()
                    
                    logger.info("График отрисован вручную через matplotlib")
                    return
                
                # Копируем содержимое полученной фигуры в нашу фигуру
                self.figure.clear()
                ax1 = self.figure.add_subplot(1, 1, 1)
                
                # Копируем все линии
                for line in ax_source.lines:
                    ax1.plot(line.get_xdata(), line.get_ydata(),
                           color=line.get_color(),
                           linewidth=line.get_linewidth(),
                           linestyle=line.get_linestyle(),
                           marker=line.get_marker())
                
                # Копируем все патчи (свечи)
                for patch in ax_source.patches:
                    # Создаем новый патч с теми же свойствами
                    from matplotlib.patches import Rectangle
                    if isinstance(patch, Rectangle):
                        new_patch = Rectangle(
                            patch.get_xy(),
                            patch.get_width(),
                            patch.get_height(),
                            facecolor=patch.get_facecolor(),
                            edgecolor=patch.get_edgecolor(),
                            linewidth=patch.get_linewidth(),
                            alpha=patch.get_alpha()
                        )
                        ax1.add_patch(new_patch)
                
                # Копируем настройки
                x_min_source, x_max_source = ax_source.get_xlim()
                # Добавляем справа пространство для будущих свечей (около 10 свечей)
                # Вычисляем ширину одной свечи
                if len(df) > 1:
                    time_diffs = df.index.to_series().diff().dropna()
                    if len(time_diffs) > 0:
                        avg_time_diff = time_diffs.mean()
                        width_days = avg_time_diff.total_seconds() / 86400.0
                    else:
                        width_days = (x_max_source - x_min_source) / len(df) if len(df) > 0 else 1.0
                else:
                    width_days = (x_max_source - x_min_source) if (x_max_source - x_min_source) > 0 else 1.0
                
                future_space = width_days * 10  # Пространство для 10 будущих свечей
                ax1.set_xlim(x_min_source, x_max_source + future_space)
                ax1.set_ylim(ax_source.get_ylim())
                ax1.set_facecolor(ax_source.get_facecolor())
                
                # Закрываем временную фигуру
                import matplotlib.pyplot as plt
                plt.close(fig)
                
                logger.info(f"Скопировано в нашу фигуру: {len(ax1.lines)} линий, {len(ax1.patches)} патчей")
                    
            except Exception as e:
                logger.error(f"Ошибка при вызове mplfinance.plot: {e}")
                import traceback
                logger.error(traceback.format_exc())
                return
            
            # Получаем ось после отрисовки
            if len(self.figure.axes) == 0:
                logger.error("mplfinance не создал ось после отрисовки")
                return
            
            ax1 = self.figure.axes[0]
            
            # Настраиваем форматирование дат на оси X (как в TradingView)
            import matplotlib.dates as mdates
            from matplotlib.dates import DateFormatter, AutoDateLocator
            
            # Определяем формат дат в зависимости от таймфрейма
            num_candles = len(df)
            
            # Форматирование дат как в TradingView
            if '1d' in timeframe_code or '1D' in timeframe_code:
                date_format = DateFormatter('%d %b')
                locator = AutoDateLocator(maxticks=12)
            elif '1w' in timeframe_code or '1mo' in timeframe_code:
                # Для недельного и месячного - дата без года
                date_format = DateFormatter('%d.%m')
                locator = AutoDateLocator(maxticks=15)
            elif '1h' in timeframe_code or '2h' in timeframe_code or '4h' in timeframe_code or '6h' in timeframe_code or '12h' in timeframe_code:
                # Для часовых таймфреймов - дата и время
                date_format = DateFormatter('%d.%m %H:%M')
                locator = AutoDateLocator(maxticks=15)
            else:
                # Для минутных таймфреймов - только время (часы:минуты)
                date_format = DateFormatter('%H:%M')
                locator = AutoDateLocator(maxticks=20)
            
            # ВАЖНО: Проверяем пределы оси X перед форматированием
            x_min, x_max = ax1.get_xlim()
            logger.info(f"Пределы оси X (числовые): {x_min} - {x_max}")
            
            # Преобразуем числовые значения обратно в даты для проверки
            from matplotlib.dates import num2date
            try:
                date_min = num2date(x_min)
                date_max = num2date(x_max)
                logger.info(f"Пределы оси X (даты): {date_min} - {date_max}")
                logger.info(f"Год минимальной даты: {date_min.year}, максимальной: {date_max.year}")
                
                # Если даты неправильные (1969-1970), исправляем их
                if date_min.year < 2020 or date_max.year < 2020:
                    logger.warning("Даты на оси X неправильные, исправляем...")
                    # Устанавливаем правильные пределы на основе данных DataFrame
                    # Используем matplotlib.dates.date2num для преобразования дат в числовые значения
                    from matplotlib.dates import date2num
                    x_min_correct = date2num(df.index[0])
                    x_max_correct = date2num(df.index[-1])
                    
                    # Вычисляем ширину одной свечи для добавления пространства справа
                    if len(df) > 1:
                        time_diffs = df.index.to_series().diff().dropna()
                        if len(time_diffs) > 0:
                            avg_time_diff = time_diffs.mean()
                            width_days = avg_time_diff.total_seconds() / 86400.0
                        else:
                            width_days = (x_max_correct - x_min_correct) / len(df) if len(df) > 0 else 1.0
                    else:
                        width_days = (x_max_correct - x_min_correct) if (x_max_correct - x_min_correct) > 0 else 1.0
                    
                    # Добавляем справа пространство для будущих свечей (около 10 свечей)
                    future_space = width_days * 10
                    ax1.set_xlim(x_min_correct, x_max_correct + future_space)
                    logger.info(f"Установлены правильные пределы: {df.index[0]} - {df.index[-1]} + {future_space:.2f} дней (10 будущих свечей)")
                    logger.info(f"Числовые значения: {x_min_correct} - {x_max_correct + future_space}")
                    
                    # Проверяем пределы после установки
                    x_min_new, x_max_new = ax1.get_xlim()
                    logger.info(f"Пределы после установки: {x_min_new} - {x_max_new}")
                    
                    # Проверяем, что графические элементы все еще на месте
                    num_lines_after = len(ax1.lines)
                    num_patches_after = len(ax1.patches)
                    logger.info(f"После установки пределов: {num_lines_after} линий, {num_patches_after} патчей")
                    
                    # Если элементов нет, возможно проблема в том, что они были отрисованы в неправильных координатах
                    if num_lines_after == 0 and num_patches_after == 0:
                        logger.error("Графические элементы исчезли после установки пределов!")
                        # Пробуем перерисовать график с правильными пределами
                        # Но сначала нужно понять, почему элементы исчезли
            except Exception as e:
                logger.error(f"Ошибка преобразования числовых значений в даты: {e}")
                import traceback
                logger.error(traceback.format_exc())
            
            ax1.xaxis.set_major_locator(locator)
            ax1.xaxis.set_major_formatter(date_format)
            
            # Поворачиваем метки дат для лучшей читаемости
            ax1.tick_params(axis='x', rotation=45, colors=UIConfig.CHART_TEXT_COLOR, labelsize=12)
            
            # Убеждаемся, что метки видны
            ax1.xaxis.set_visible(True)
            
            # Принудительно обновляем форматирование
            ax1.xaxis.set_major_formatter(date_format)
            self.figure.autofmt_xdate()  # Автоматическое форматирование дат
            
            # Настраиваем цвета осей для основного графика
            ax1.set_facecolor(UIConfig.CHART_BACKGROUND_COLOR)
            ax1.tick_params(axis='y', colors=UIConfig.CHART_TEXT_COLOR, labelsize=14)
            ax1.spines['bottom'].set_color(UIConfig.CHART_GRID_COLOR)
            ax1.spines['top'].set_color(UIConfig.CHART_GRID_COLOR)
            ax1.spines['right'].set_color(UIConfig.CHART_GRID_COLOR)
            ax1.spines['left'].set_color(UIConfig.CHART_GRID_COLOR)
            apply_price_formatter(ax1)
            
            # Размещаем цену справа от графика (уже установлено через y_on_right=True)
            
            # Проверяем, что на оси есть графические элементы
            num_lines = len(ax1.lines)
            num_patches = len(ax1.patches)
            logger.info(f"На оси после отрисовки: {num_lines} линий, {num_patches} патчей")
            
            # Если нет элементов, возможно проблема с данными или отрисовкой
            if num_lines == 0 and num_patches == 0:
                logger.warning("На оси нет графических элементов после отрисовки mplfinance!")
                logger.info(f"Диапазон данных: {df.index[0]} - {df.index[-1]}")
                logger.info(f"Диапазон цен: {df['Low'].min():.2f} - {df['High'].max():.2f}")
            
            # Настраиваем отступы для максимального использования пространства
            # Увеличиваем нижний отступ для меток дат
            self.figure.subplots_adjust(left=0.05, right=0.95, bottom=0.12, top=0.95)
            
            # Обновляем canvas
            try:
                self.canvas.draw()
                logger.info("Canvas обновлен успешно")
            except Exception as e:
                logger.error(f"Ошибка при обновлении canvas: {e}")
                import traceback
                logger.error(traceback.format_exc())
                return
            
            # Сохраняем текущие параметры
            self.current_instrument = instrument_symbol
            self.current_timeframe = timeframe_code
            
            logger.info(f"График отрисован: {instrument_symbol} {timeframe_code} ({len(df)} свечей)")
            
        except Exception as e:
            logger.error(f"Ошибка при отрисовке графика: {e}")
            import traceback
            logger.error(traceback.format_exc())


class InstrumentsListWidget(QListWidget):
    """
    Виджет списка инструментов с поддержкой двойного клика.
    """
    
    instrument_selected = pyqtSignal(str)  # Сигнал при выборе инструмента
    
    def __init__(self, parent=None):
        """
        Инициализация списка инструментов.
        """
        super().__init__(parent)
        self.setup_ui()
        
    def setup_ui(self):
        """
        Настройка UI списка.
        """
        # Применяем стиль
        self.setStyleSheet(f"""
            QListWidget {{
                background-color: {UIConfig.SECONDARY_BACKGROUND_COLOR};
                color: {UIConfig.TEXT_COLOR_PRIMARY};
                border: none;
                font-size: {UIConfig.FONT_SIZE_NORMAL}px;
            }}
            QListWidget::item {{
                padding: 12px;
                border-bottom: 1px solid {UIConfig.TERTIARY_BACKGROUND_COLOR};
                min-height: 40px;
            }}
            QListWidget::item:hover {{
                background-color: {UIConfig.LIST_ITEM_HOVER};
            }}
            QListWidget::item:selected {{
                background-color: {UIConfig.LIST_ITEM_SELECTED};
                color: white;
            }}
        """)
        
        # Подключаем двойной клик
        self.itemDoubleClicked.connect(self.on_item_double_clicked)
        
    def load_instruments(self, instruments):
        """
        Загружает список инструментов в виджет.
        
        Параметры:
            instruments: Список объектов Instrument.
        """
        self.clear()
        for instrument in instruments:
            item = QListWidgetItem(instrument.symbol)
            item.setData(Qt.UserRole, instrument.symbol)
            self.addItem(item)
        
        logger.info(f"Загружено {len(instruments)} инструментов в список")
    
    def on_item_double_clicked(self, item):
        """
        Обработчик двойного клика по элементу списка.
        """
        symbol = item.data(Qt.UserRole)
        if symbol:
            logger.info(f"Выбран инструмент: {symbol}")
            self.instrument_selected.emit(symbol)


class TimeframePanelWidget(QWidget):
    """
    Панель выбора таймфрейма.
    """
    
    timeframe_changed = pyqtSignal(str)  # Сигнал при изменении таймфрейма
    
    def __init__(self, parent=None):
        """
        Инициализация панели таймфреймов.
        """
        super().__init__(parent)
        self.current_timeframe = "1d"
        self.setup_ui()
        
    def setup_ui(self):
        """
        Настройка UI панели.
        """
        layout = QHBoxLayout()
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(5)
        
        # Метка
        label = QLabel("Таймфрейм:")
        label.setStyleSheet(f"color: {UIConfig.TEXT_COLOR_PRIMARY}; font-size: {UIConfig.FONT_SIZE_NORMAL}px;")
        layout.addWidget(label)
        
        # Кнопки таймфреймов
        timeframes = [
            ("1m", "1m"), ("3m", "3m"), ("5m", "5m"), ("15m", "15m"), ("30m", "30m"),
            ("1h", "1h"), ("2h", "2h"), ("4h", "4h"), ("6h", "6h"), ("12h", "12h"),
            ("1d", "1D"), ("1w", "1W"), ("1mo", "1M")
        ]
        
        for code, label_text in timeframes:
            btn = QPushButton(label_text)
            btn.setCheckable(True)
            btn.setMinimumSize(60, 50)  # Увеличено с 40x30
            btn.clicked.connect(lambda checked, c=code: self.on_timeframe_clicked(c))
            
            # Стиль кнопки
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {UIConfig.SECONDARY_BACKGROUND_COLOR};
                    color: {UIConfig.TEXT_COLOR_PRIMARY};
                    border: 1px solid {UIConfig.TERTIARY_BACKGROUND_COLOR};
                    border-radius: 4px;
                    font-size: {UIConfig.FONT_SIZE_NORMAL}px;
                    padding: 8px 16px;
                }}
                QPushButton:hover {{
                    background-color: {UIConfig.TERTIARY_BACKGROUND_COLOR};
                }}
                QPushButton:checked {{
                    background-color: {UIConfig.ACCENT_COLOR};
                    color: white;
                    border-color: {UIConfig.ACCENT_COLOR};
                }}
            """)
            
            layout.addWidget(btn)
            
            # Сохраняем ссылку на кнопку
            setattr(self, f"btn_{code}", btn)
        
        layout.addStretch()
        self.setLayout(layout)
        
        # Устанавливаем таймфрейм по умолчанию (1d)
        self.set_timeframe("1d")
        
        # Применяем стиль к панели
        self.setStyleSheet(f"background-color: {UIConfig.SECONDARY_BACKGROUND_COLOR};")
    
    def set_timeframe(self, timeframe_code: str):
        """
        Устанавливает активный таймфрейм.
        
        Параметры:
            timeframe_code: Код таймфрейма.
        """
        # Сбрасываем все кнопки
        for code in ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d", "1w", "1mo"]:
            btn = getattr(self, f"btn_{code}", None)
            if btn:
                btn.setChecked(False)
        
        # Активируем выбранный
        btn = getattr(self, f"btn_{timeframe_code}", None)
        if btn:
            btn.setChecked(True)
            self.current_timeframe = timeframe_code
    
    def on_timeframe_clicked(self, timeframe_code: str):
        """
        Обработчик клика по кнопке таймфрейма.
        """
        self.set_timeframe(timeframe_code)
        logger.info(f"Выбран таймфрейм: {timeframe_code}")
        self.timeframe_changed.emit(timeframe_code)


class TradingViewApp(QMainWindow):
    """
    Главное окно приложения в стиле TradingView.
    """
    
    def __init__(self):
        """
        Инициализация главного окна.
        """
        super().__init__()
        self.data_fetcher = DataFetcher()
        self.current_instrument = None
        self.current_timeframe = "1d"
        self.is_first_show = True
        
        # Инициализируем обновлятель данных
        self.data_updater = DataUpdater()
        
        self.init_ui()
        self.load_instruments()
        
        # Подключаем обработчик изменения геометрии окна
        self.geometry_change_timer = QTimer()
        self.geometry_change_timer.setSingleShot(True)
        self.geometry_change_timer.timeout.connect(self.on_geometry_changed)
        
        # Таймер для автоматического обновления графика
        self.chart_update_timer = QTimer()
        self.chart_update_timer.timeout.connect(self.update_chart_if_needed)
        self.start_chart_auto_update()
        
        # Запускаем обновление данных в фоне (не блокируя UI)
        self.start_data_update()
        
    def init_ui(self):
        """
        Инициализация пользовательского интерфейса.
        """
        self.setWindowTitle("Trading Bot - TradingView Style")
        
        # Применяем стиль главного окна
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {UIConfig.BACKGROUND_COLOR};
            }}
        """)
        
        # Создаем центральный виджет
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Главный layout
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        central_widget.setLayout(main_layout)
        
        # Создаем splitter для разделения панели инструментов и графика
        main_splitter = QSplitter(Qt.Horizontal)
        
        # Левая панель: список инструментов
        self.instruments_list = InstrumentsListWidget()
        self.instruments_list.instrument_selected.connect(self.on_instrument_selected)
        main_splitter.addWidget(self.instruments_list)
        
        # Правая панель: график с наложенной панелью таймфреймов
        right_panel = QWidget()
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        
        # График (занимает все пространство)
        self.chart_widget = CandlestickChartWidget()
        right_layout.addWidget(self.chart_widget)
        
        # Панель таймфреймов - размещаем поверх графика в верхнем левом углу
        self.timeframe_panel = TimeframePanelWidget()
        self.timeframe_panel.timeframe_changed.connect(self.on_timeframe_changed)
        # Делаем панель прозрачной и размещаем поверх графика
        self.timeframe_panel.setStyleSheet(f"""
            {self.timeframe_panel.styleSheet()}
            background-color: transparent;
        """)
        
        right_panel.setLayout(right_layout)
        
        # Размещаем панель таймфреймов поверх графика (overlay) в верхнем левом углу
        # Используем абсолютное позиционирование
        self.timeframe_panel.setParent(right_panel)
        self.timeframe_panel.setGeometry(5, 5, self.timeframe_panel.sizeHint().width(), self.timeframe_panel.sizeHint().height())
        self.timeframe_panel.raise_()  # Поднимаем наверх
        
        main_splitter.addWidget(right_panel)
        
        # Устанавливаем пропорции (20% инструменты, 80% график)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 4)
        main_splitter.setSizes([UIConfig.INSTRUMENTS_PANEL_WIDTH, 1200])
        
        main_layout.addWidget(main_splitter)
        
        # Устанавливаем минимальные размеры
        self.setMinimumSize(UIConfig.MAIN_WINDOW_MIN_WIDTH, UIConfig.MAIN_WINDOW_MIN_HEIGHT)
        
        # Сохраняем ссылку на right_panel для обновления позиции панели таймфреймов
        self.right_panel = right_panel
        
    def showEvent(self, event):
        """
        Обработчик события показа окна.
        При первом показе делаем окно полноэкранным.
        """
        super().showEvent(event)
        
        if self.is_first_show:
            self.is_first_show = False
            # Используем showMaximized() для корректного отображения на любом разрешении
            self.showMaximized()
            screen = QApplication.primaryScreen()
            if screen:
                geometry = self.geometry()
                logger.info(f"Окно максимизировано: {geometry.width()}x{geometry.height()}")
            else:
                logger.warning("Не удалось получить размеры экрана")
    
    def moveEvent(self, event):
        """
        Обработчик перемещения окна.
        При переносе на другой монитор адаптируем размер.
        """
        super().moveEvent(event)
        # Используем таймер для задержки проверки (чтобы не проверять при каждом пикселе движения)
        self.geometry_change_timer.start(100)
    
    def resizeEvent(self, event):
        """
        Обработчик изменения размера окна.
        """
        super().resizeEvent(event)
        self.geometry_change_timer.start(100)
        # Обновляем позицию панели таймфреймов
        if hasattr(self, 'timeframe_panel') and hasattr(self, 'right_panel'):
            panel_size = self.timeframe_panel.sizeHint()
            self.timeframe_panel.setGeometry(5, 5, panel_size.width(), panel_size.height())
    
    def on_geometry_changed(self):
        """
        Обработчик изменения геометрии окна (после задержки).
        Адаптирует размер окна под текущий монитор.
        """
        # Получаем экран, на котором находится окно
        screen = QApplication.screenAt(self.geometry().center())
        if screen:
            screen_geometry = screen.availableGeometry()  # Используем availableGeometry
            current_geometry = self.geometry()
            
            # Проверяем, выходит ли окно за пределы экрана
            if (current_geometry.x() < screen_geometry.x() or
                current_geometry.y() < screen_geometry.y() or
                current_geometry.right() > screen_geometry.right() or
                current_geometry.bottom() > screen_geometry.bottom()):
                
                # Если окно выходит за пределы, максимизируем его на текущем экране
                logger.info(f"Окно выходит за пределы экрана, максимизируем на экране {screen_geometry.width()}x{screen_geometry.height()}")
                self.showMaximized()
    
    def load_instruments(self):
        """
        Загружает список инструментов из БД.
        """
        try:
            instruments = self.data_fetcher.get_instruments()
            self.instruments_list.load_instruments(instruments)
            logger.info(f"Загружено {len(instruments)} инструментов")
        except Exception as e:
            logger.error(f"Ошибка при загрузке инструментов: {e}")
    
    def on_instrument_selected(self, symbol: str):
        """
        Обработчик выбора инструмента.
        
        Параметры:
            symbol: Символ инструмента.
        """
        self.current_instrument = symbol
        logger.info(f"Выбран инструмент: {symbol}, таймфрейм: {self.current_timeframe}")
        self.chart_widget.plot_candlestick(symbol, self.current_timeframe)
    
    def on_timeframe_changed(self, timeframe_code: str):
        """
        Обработчик изменения таймфрейма.
        
        Параметры:
            timeframe_code: Код таймфрейма.
        """
        self.current_timeframe = timeframe_code
        if self.current_instrument:
            logger.info(f"Изменен таймфрейм: {timeframe_code} для {self.current_instrument}")
            self.chart_widget.plot_candlestick(self.current_instrument, timeframe_code)
        
        # Перезапускаем автообновление с новым интервалом
        self.start_chart_auto_update()
    
    def get_update_interval_ms(self, timeframe_code: str) -> int:
        """
        Возвращает интервал обновления графика в миллисекундах для заданного таймфрейма.
        
        Параметры:
            timeframe_code: Код таймфрейма.
        
        Возвращает:
            Интервал в миллисекундах.
        """
        # Интервалы обновления в зависимости от таймфрейма
        intervals = {
            '1m': 60 * 1000,      # Каждую минуту
            '3m': 3 * 60 * 1000,  # Каждые 3 минуты
            '5m': 5 * 60 * 1000,  # Каждые 5 минут
            '15m': 15 * 60 * 1000, # Каждые 15 минут
            '30m': 30 * 60 * 1000, # Каждые 30 минут
            '1h': 60 * 60 * 1000,   # Каждый час
            '2h': 2 * 60 * 60 * 1000,
            '4h': 4 * 60 * 60 * 1000,
            '6h': 6 * 60 * 60 * 1000,
            '12h': 12 * 60 * 60 * 1000,
            '1d': 24 * 60 * 60 * 1000,  # Раз в день
            '1w': 7 * 24 * 60 * 60 * 1000,
            '1mo': 30 * 24 * 60 * 60 * 1000,
        }
        return intervals.get(timeframe_code, 60 * 1000)  # По умолчанию каждую минуту
    
    def start_chart_auto_update(self):
        """
        Запускает автоматическое обновление графика с интервалом, соответствующим текущему таймфрейму.
        """
        if self.chart_update_timer.isActive():
            self.chart_update_timer.stop()
        
        interval_ms = self.get_update_interval_ms(self.current_timeframe)
        self.chart_update_timer.start(interval_ms)
        logger.info(f"Автообновление графика запущено с интервалом {interval_ms/1000} секунд для таймфрейма {self.current_timeframe}")
    
    def update_chart_if_needed(self):
        """
        Обновляет график, если выбран инструмент.
        """
        if self.current_instrument:
            logger.info(f"Автообновление графика для {self.current_instrument} на {self.current_timeframe}")
            self.chart_widget.plot_candlestick(self.current_instrument, self.current_timeframe)
    
    def start_data_update(self):
        """
        Запускает обновление данных в фоне.
        Сначала проверяет и загружает недостающие данные, затем запускает периодическое обновление.
        """
        def update_in_background():
            """
            Функция для выполнения в фоновом потоке.
            """
            try:
                logger.info("Начало проверки и загрузки недостающих данных...")
                
                # Обновляем все инструменты (загружаем недостающие свечи)
                # force_all=True - при первом запуске обновляем все таймфреймы
                self.data_updater.update_all_instruments(force_all=True)
                
                logger.info("Недостающие данные загружены, запуск периодического обновления...")
                
                # Запускаем фоновое обновление
                # Базовый интервал проверки - 60 секунд (каждую минуту проверяем, что нужно обновить)
                # Каждый таймфрейм обновляется с интервалом, соответствующим его периоду
                self.data_updater.start_background_update(base_check_interval=60)
                
            except Exception as e:
                logger.error(f"Ошибка при обновлении данных в фоне: {e}")
                import traceback
                logger.error(traceback.format_exc())
        
        # Запускаем в отдельном потоке, чтобы не блокировать UI
        update_thread = Thread(target=update_in_background, daemon=True)
        update_thread.start()
        logger.info("Запущен фоновый поток обновления данных")
    
    def closeEvent(self, event):
        """
        Обработчик закрытия окна.
        Останавливает фоновое обновление данных.
        """
        logger.info("Закрытие приложения, остановка фонового обновления...")
        self.data_updater.stop_background_update()
        super().closeEvent(event)


def main():
    """
    Точка входа в приложение.
    """
    # Включаем DPI scaling для высоких разрешений
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    
    app = QApplication(sys.argv)
    
    # Устанавливаем шрифт
    font = QFont(UIConfig.FONT_FAMILY, UIConfig.FONT_SIZE_NORMAL)
    app.setFont(font)
    
    # Создаем и показываем главное окно
    window = TradingViewApp()
    window.show()
    
    logger.info("Приложение TradingView-style запущено")
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

