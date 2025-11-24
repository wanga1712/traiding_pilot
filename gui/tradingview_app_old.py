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
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from gui.ui_config import UIConfig
from gui.data_fetcher import DataFetcher
from crypto_trading_bot.database.data_import import DataImport
from crypto_trading_bot.trading.data_updater import DataUpdater
from crypto_trading_bot.analytics.dinapoli_dma import DinapoliDMAService
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

        def apply_time_axis_formatting(axis):
            """
            Применяет форматирование оси X в зависимости от таймфрейма.
            """
            import matplotlib.dates as mdates
            from matplotlib.dates import DateFormatter, AutoDateLocator, num2date, date2num

            if '1d' in timeframe_code or '1D' in timeframe_code:
                date_format = DateFormatter('%d %b')
                locator = AutoDateLocator(maxticks=12)
            elif '1w' in timeframe_code or '1mo' in timeframe_code:
                date_format = DateFormatter('%d.%m')
                locator = AutoDateLocator(maxticks=15)
            elif ('1h' in timeframe_code or '2h' in timeframe_code or '4h' in timeframe_code or
                  '6h' in timeframe_code or '12h' in timeframe_code):
                date_format = DateFormatter('%d.%m %H:%M')
                locator = AutoDateLocator(maxticks=15)
            else:
                date_format = DateFormatter('%H:%M')
                locator = AutoDateLocator(maxticks=20)

            axis.xaxis.set_major_locator(locator)
            axis.xaxis.set_major_formatter(date_format)

            x_min, x_max = axis.get_xlim()
            try:
                date_min = num2date(x_min)
                date_max = num2date(x_max)
                logger.info(f"Пределы оси X (даты): {date_min} - {date_max}")
                logger.info(f"Год минимальной даты: {date_min.year}, максимальной: {date_max.year}")

                if date_min.year < 2020 or date_max.year < 2020:
                    logger.warning("Даты на оси X неправильные, исправляем...")
                    x_min_correct = date2num(df.index[0])
                    x_max_correct = date2num(df.index[-1])

                    if len(df) > 1:
                        time_diffs = df.index.to_series().diff().dropna()
                        if len(time_diffs) > 0:
                            avg_time_diff = time_diffs.mean()
                            width_days = avg_time_diff.total_seconds() / 86400.0
                        else:
                            width_days = (x_max_correct - x_min_correct) / len(df) if len(df) > 0 else 1.0
                    else:
                        width_days = (x_max_correct - x_min_correct) if (x_max_correct - x_min_correct) > 0 else 1.0

                    future_space = width_days * 10
                    axis.set_xlim(x_min_correct, x_max_correct + future_space)
                    logger.info(
                        f"Установлены правильные пределы: {df.index[0]} - {df.index[-1]} + {future_space:.2f} дней"
                    )
            except Exception as date_err:
                logger.error(f"Ошибка преобразования числовых значений в даты: {date_err}")
                import traceback
                logger.error(traceback.format_exc())

        def calculate_candle_width():
            """
            Рассчитывает ширину свечи в днях для корректного отображения.
            """
            if len(df) > 1:
                time_diffs = df.index.to_series().diff().dropna()
                if len(time_diffs) > 0:
                    avg_time_diff = time_diffs.mean()
                    return avg_time_diff.total_seconds() / 86400.0 * 0.7

            if '1m' in timeframe_code:
                return 1.0 / 60.0 / 24.0 * 0.7
            if '3m' in timeframe_code:
                return 3.0 / 60.0 / 24.0 * 0.7
            if '5m' in timeframe_code:
                return 5.0 / 60.0 / 24.0 * 0.7
            if '15m' in timeframe_code:
                return 15.0 / 60.0 / 24.0 * 0.7
            if '30m' in timeframe_code:
                return 30.0 / 60.0 / 24.0 * 0.7
            if '1h' in timeframe_code:
                return 1.0 / 24.0 * 0.7
            if '1d' in timeframe_code or '1D' in timeframe_code:
                return 0.7
            if '1w' in timeframe_code:
                return 7.0 * 0.7
            if '1mo' in timeframe_code:
                return 30.0 * 0.7
            return 0.6

        def prepare_plot_payload():
            """
            Готовит массивы данных для отрисовки свечей и объемов.
            """
            from matplotlib.dates import date2num
            import numpy as np

            width_days = calculate_candle_width()
            timestamps = np.array([date2num(ts) for ts in df.index])
            opens = df['Open'].astype(float).values
            closes = df['Close'].astype(float).values
            highs = df['High'].astype(float).values
            lows = df['Low'].astype(float).values
            volumes = df['Volume'].astype(float).values

            colors = np.where(closes >= opens, UIConfig.CANDLE_BULLISH_COLOR, UIConfig.CANDLE_BEARISH_COLOR)

            max_draw = 500
            if len(timestamps) > max_draw:
                step = len(timestamps) // max_draw
                indices = list(range(0, len(timestamps), step))[:max_draw]
                timestamps = timestamps[indices]
                opens = opens[indices]
                closes = closes[indices]
                highs = highs[indices]
                lows = lows[indices]
                volumes = volumes[indices]
                colors = colors[indices]

            return {
                'timestamps': timestamps,
                'opens': opens,
                'closes': closes,
                'highs': highs,
                'lows': lows,
                'volumes': volumes,
                'colors': colors,
                'width_days': width_days
            }

        def draw_price(ax_price, payload):
            """
            Отрисовывает свечной график вручную.
            """
            from matplotlib.patches import Rectangle

            timestamps = payload['timestamps']
            opens = payload['opens']
            closes = payload['closes']
            highs = payload['highs']
            lows = payload['lows']
            colors = payload['colors']
            width_days = payload['width_days']

            for idx, ts in enumerate(timestamps):
                ax_price.plot(
                    [ts, ts],
                    [lows[idx], highs[idx]],
                    color=colors[idx],
                    linewidth=0.5,
                    alpha=0.8
                )

            for idx, ts in enumerate(timestamps):
                body_bottom = min(opens[idx], closes[idx])
                body_height = abs(closes[idx] - opens[idx])
                if body_height == 0:
                    body_height = (highs[idx] - lows[idx]) * 0.1
                    if body_height == 0:
                        body_height = (highs.max() - lows.min()) * 0.001
                x_pos = ts - width_days / 2
                candle = Rectangle(
                    (x_pos, body_bottom),
                    width_days,
                    body_height,
                    facecolor=colors[idx],
                    edgecolor=colors[idx],
                    linewidth=0.5
                )
                ax_price.add_patch(candle)

            future_space = width_days * 10
            ax_price.set_xlim(timestamps[0] - width_days, timestamps[-1] + future_space)
            ax_price.set_ylim(lows.min() * 0.99, highs.max() * 1.01)

        def draw_volume(ax_volume, payload):
            """
            Отрисовывает гистограмму объемов.
            """
            timestamps = payload['timestamps']
            volumes = payload['volumes']
            colors = payload['colors']
            width_days = payload['width_days']

            ax_volume.bar(
                timestamps,
                volumes,
                width=width_days,
                color=colors,
                align='center',
                alpha=0.5
            )
            if volumes.max() > 0:
                ax_volume.set_ylim(0, volumes.max() * 1.2)
            ax_volume.set_xlim(timestamps[0] - width_days, timestamps[-1] + width_days * 10)

        def draw_dma_lines(ax_price, instrument_symbol, timeframe_code, df_index):
            """
            Отрисовывает линии DMA на графике цен.
            
            Параметры:
                ax_price: Ось для отрисовки цен.
                instrument_symbol: Символ инструмента.
                timeframe_code: Код таймфрейма.
                df_index: Индекс DataFrame с временными метками.
            """
            try:
                from matplotlib.dates import date2num
                dma_service = DinapoliDMAService()
                
                # Цвета для разных DMA линий
                dma_colors = {
                    (3, 3): '#00ff00',    # Зеленый для 3x3
                    (7, 5): '#ffff00',   # Желтый для 7x5
                    (25, 5): '#ff00ff'   # Пурпурный для 25x5
                }
                
                # Получаем и отрисовываем каждую комбинацию DMA
                for period, displacement in DinapoliDMAService.DMA_COMBINATIONS:
                    dma_series = dma_service.get_dma_from_db(
                        instrument_symbol, timeframe_code, period, displacement
                    )
                    
                    if dma_series is not None and not dma_series.empty:
                        # Фильтруем данные по индексу основного графика
                        # Оставляем только те значения, которые попадают в диапазон графика
                        dma_filtered = dma_series[
                            (dma_series.index >= df_index[0]) & 
                            (dma_series.index <= df_index[-1])
                        ]
                        
                        if not dma_filtered.empty:
                            # Преобразуем timestamp в числовые значения для matplotlib
                            timestamps_num = [date2num(ts) for ts in dma_filtered.index]
                            
                            # Отрисовываем линию DMA
                            color = dma_colors.get((period, displacement), '#ffffff')
                            ax_price.plot(
                                timestamps_num,
                                dma_filtered.values,
                                color=color,
                                linewidth=1.5,
                                alpha=0.8,
                                label=f'DMA {period}x{displacement}'
                            )
                            
                            logger.debug(
                                f"DMA {period}x{displacement} отрисована: "
                                f"{len(dma_filtered)} точек"
                            )
                    else:
                        logger.debug(
                            f"DMA {period}x{displacement} не найдена в БД для "
                            f"{instrument_symbol} на {timeframe_code}"
                        )
                        
            except Exception as e:
                logger.error(f"Ошибка при отрисовке DMA: {e}")
                import traceback
                logger.error(traceback.format_exc())

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
                logger.debug(f"Первый элемент из БД: {first_record}")
                logger.debug(f"Тип первого элемента: {type(first_record)}")
                logger.debug(f"Тип candle_time (первый элемент кортежа): {type(first_record[0])}, значение: {first_record[0]}")
                if len(price_data) > 1:
                    logger.debug(f"Второй элемент: {price_data[1]}")
            
            # Преобразуем в DataFrame
            # Порядок колонок из БД: candle_time, open, close, high, low, volume
            
            # Преобразуем данные, правильно обрабатывая timestamp
            timestamps = []
            for i, data in enumerate(price_data):
                ts = data[0]
                
                # Логируем первые несколько значений для отладки
                if i < 5:
                    logger.debug(f"[{i}] Тип timestamp: {type(ts)}, значение: {repr(ts)}")
                
                # PostgreSQL возвращает datetime объекты или строки
                # Преобразуем напрямую в pd.Timestamp
                try:
                    # Если это datetime объект Python (из PostgreSQL psycopg2)
                    if hasattr(ts, 'year') and hasattr(ts, 'month') and hasattr(ts, 'day'):
                        # Это datetime объект, преобразуем в pd.Timestamp
                        ts_converted = pd.Timestamp(ts)
                        if i < 5:
                            logger.debug(f"[{i}] Преобразовано из datetime: {ts} -> {ts_converted}")
                    # Если это строка
                    elif isinstance(ts, str):
                        ts_converted = pd.to_datetime(ts)
                        if i < 5:
                            logger.debug(f"[{i}] Преобразовано из строки: {ts} -> {ts_converted}")
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
                        logger.debug(f"[{i}] Преобразовано из числа: {ts} -> {ts_converted}")
                    else:
                        # Для всех остальных случаев используем pd.to_datetime
                        ts_converted = pd.to_datetime(ts)
                        if i < 5:
                            logger.debug(f"[{i}] Преобразовано через pd.to_datetime: {ts} -> {ts_converted}")
                    
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
            logger.debug(f"Первый timestamp после преобразования: {timestamps[0]} (год: {timestamps[0].year})")
            logger.debug(f"Последний timestamp: {timestamps[-1]} (год: {timestamps[-1].year})")
            
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
            logger.debug(f"Индекс DataFrame (первые 3): {df.index[:3].tolist()}")
            logger.debug(f"Индекс DataFrame (последние 3): {df.index[-3:].tolist()}")
            logger.debug(f"Тип индекса: {type(df.index)}")
            logger.debug(f"Год первого элемента индекса: {df.index[0].year}")
            logger.debug(f"Год последнего элемента индекса: {df.index[-1].year}")
            
            # Сортируем по времени
            df.sort_index(inplace=True)
            
            # ПРОВЕРЯЕМ DataFrame перед передачей в mplfinance
            logger.debug(f"DataFrame индекс (первые 3): {df.index[:3].tolist()}")
            logger.debug(f"DataFrame индекс (последние 3): {df.index[-3:].tolist()}")
            logger.debug(f"Тип индекса: {type(df.index)}")
            logger.debug(f"Тип первого элемента индекса: {type(df.index[0])}")
            
            # Убеждаемся, что индекс - это DatetimeIndex
            if not isinstance(df.index, pd.DatetimeIndex):
                logger.warning("Индекс не DatetimeIndex, преобразуем...")
                df.index = pd.to_datetime(df.index)
                logger.debug(f"После преобразования: {type(df.index)}, первые значения: {df.index[:3].tolist()}")
            
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
                logger.debug(f"Ограничено до последних {limit} свечей для таймфрейма {timeframe_code}")
            
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
            
            logger.debug(f"Используется часовой пояс: {local_tz}")
            
            # Если индекс без timezone, предполагаем что это UTC и локализуем
            if df.index.tz is None:
                logger.debug("Индекс без timezone, предполагаем UTC и конвертируем в локальный часовой пояс")
                df.index = df.index.tz_localize('UTC').tz_convert(local_tz)
            else:
                # Если есть timezone, конвертируем в локальный
                logger.debug(f"Индекс с timezone {df.index.tz}, конвертируем в локальный часовой пояс")
                df.index = df.index.tz_convert(local_tz)
            
            # ВАЖНО: Убираем timezone из индекса для mplfinance
            # mplfinance может не работать с timezone-aware datetime
            logger.debug("Убираем timezone из индекса DataFrame для mplfinance (после конвертации в локальный часовой пояс)")
            df.index = df.index.tz_localize(None)
            
            logger.debug(f"Первый timestamp после конвертации: {df.index[0]} (локальное время)")
            logger.debug(f"Последний timestamp: {df.index[-1]} (локальное время)")
            
            # Проверяем данные на наличие NaN и других проблем
            logger.debug(f"Проверка данных: Open min={df['Open'].min():.2f}, max={df['Open'].max():.2f}")
            logger.debug(f"Проверка данных: High min={df['High'].min():.2f}, max={df['High'].max():.2f}")
            logger.debug(f"Проверка данных: Low min={df['Low'].min():.2f}, max={df['Low'].max():.2f}")
            logger.debug(f"Проверка данных: Close min={df['Close'].min():.2f}, max={df['Close'].max():.2f}")
            
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
            
            payload = prepare_plot_payload()
            self.figure.clear()
            grid_spec = self.figure.add_gridspec(2, 1, height_ratios=[4, 1], hspace=0.06)
            ax_price = self.figure.add_subplot(grid_spec[0])
            ax_volume = self.figure.add_subplot(grid_spec[1], sharex=ax_price)

            draw_price(ax_price, payload)
            draw_volume(ax_volume, payload)
            draw_dma_lines(ax_price, instrument_symbol, timeframe_code, df.index)

            apply_time_axis_formatting(ax_price)
            apply_price_formatter(ax_price)
            ax_price.tick_params(axis='x', colors=UIConfig.CHART_TEXT_COLOR, labelsize=12, labelbottom=False)
            ax_price.set_facecolor(UIConfig.CHART_BACKGROUND_COLOR)
            ax_price.tick_params(axis='y', colors=UIConfig.CHART_TEXT_COLOR, labelsize=14)
            ax_price.spines['bottom'].set_color(UIConfig.CHART_GRID_COLOR)
            ax_price.spines['top'].set_color(UIConfig.CHART_GRID_COLOR)
            ax_price.spines['right'].set_color(UIConfig.CHART_GRID_COLOR)
            ax_price.spines['left'].set_color(UIConfig.CHART_GRID_COLOR)
            ax_price.yaxis.tick_right()
            ax_price.yaxis.set_label_position('right')
            
            # Добавляем легенду для DMA линий
            ax_price.legend(loc='upper left', fontsize=10, framealpha=0.8, 
                facecolor=UIConfig.CHART_BACKGROUND_COLOR,
                           edgecolor=UIConfig.CHART_GRID_COLOR)

            ax_volume.set_facecolor(UIConfig.CHART_BACKGROUND_COLOR)
            ax_volume.spines['bottom'].set_color(UIConfig.CHART_GRID_COLOR)
            ax_volume.spines['top'].set_color(UIConfig.CHART_GRID_COLOR)
            ax_volume.spines['right'].set_color(UIConfig.CHART_GRID_COLOR)
            ax_volume.spines['left'].set_color(UIConfig.CHART_GRID_COLOR)
            ax_volume.tick_params(axis='y', colors=UIConfig.CHART_TEXT_COLOR, labelsize=12)
            ax_volume.yaxis.tick_right()
            ax_volume.yaxis.set_label_position('right')
            ax_volume.set_ylabel("Объём", color=UIConfig.CHART_TEXT_COLOR)
            ax_volume.ticklabel_format(style='plain', axis='y', useOffset=False)

            def volume_formatter(value, _):
                return f"{value:,.0f}".replace(",", " ")

            ax_volume.yaxis.set_major_formatter(FuncFormatter(volume_formatter))
            ax_volume.tick_params(axis='x', rotation=45, colors=UIConfig.CHART_TEXT_COLOR, labelsize=12)

            self.figure.autofmt_xdate()

            num_lines = len(ax_price.lines)
            num_patches = len(ax_price.patches)
            logger.debug(f"На графике после отрисовки: {num_lines} линий, {num_patches} патчей")
            
            if num_lines == 0 and num_patches == 0:
                logger.warning("После отрисовки график пуст – проверьте входные данные.")
            
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

