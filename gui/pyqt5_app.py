"""
PyQt5 приложение для анализа рынка криптовалют и получения торговых сигналов.

Это приложение предоставляет графический интерфейс для:
- Просмотра графиков цен криптовалют
- Анализа рынка с помощью технических индикаторов
- Получения торговых сигналов на основе стратегий
- Мониторинга состояния портфеля
"""
import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QComboBox, QLabel, QTableWidget, QTableWidgetItem,
    QSplitter, QMessageBox, QGroupBox, QGridLayout, QDesktopWidget
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QColor
from loguru import logger
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from gui.ui_config import UIConfig
from gui.data_fetcher import DataFetcher
from gui.visualizer import DataVisualizer
from crypto_trading_bot.database.data_export import DataExporter


class ChartWidget(QWidget):
    """
    Виджет для отображения графиков цен криптовалют.
    
    Использует matplotlib для отображения свечных графиков и индикаторов.
    """
    
    def __init__(self, parent=None):
        """
        Инициализация виджета графика.
        
        Параметры:
            parent: Родительский виджет.
        """
        super().__init__(parent)
        self.data_fetcher = DataFetcher()
        self.visualizer = DataVisualizer(self.data_fetcher)
        
        # Создаем фигуру matplotlib
        self.figure = Figure(figsize=(UIConfig.CHART_WIDGET_WIDTH / 100, 
                                     UIConfig.CHART_WIDGET_HEIGHT / 100))
        self.canvas = FigureCanvas(self.figure)
        
        # Настраиваем стиль графика
        self.figure.patch.set_facecolor(UIConfig.CHART_BACKGROUND_COLOR)
        
        # Создаем layout
        layout = QVBoxLayout()
        layout.addWidget(self.canvas)
        self.setLayout(layout)
        
        # Применяем стили
        self.setStyleSheet(UIConfig.PANEL_STYLE)
    
    def plot_chart(self, instrument_symbol, timeframe_name, indicator_types=None):
        """
        Отображает график для указанного инструмента и таймфрейма.
        
        Параметры:
            instrument_symbol (str): Символ инструмента (например, 'BTCUSDT').
            timeframe_name (str): Название таймфрейма (например, '1day').
            indicator_types (list, optional): Список типов индикаторов для отображения.
        """
        try:
            # Очищаем предыдущий график
            self.figure.clear()
            
            # Получаем данные
            instrument_id = self.data_fetcher.get_instrument_id(instrument_symbol)
            timeframe_id = self.data_fetcher.get_timeframe_id(timeframe_name)
            
            if not instrument_id or not timeframe_id:
                logger.error(f"Не найден инструмент {instrument_symbol} или таймфрейм {timeframe_name}")
                return
            
            price_data = self.data_fetcher.get_price_data(instrument_id, timeframe_id)
            
            if not price_data:
                logger.warning(f"Нет данных для {instrument_symbol} на таймфрейме {timeframe_name}")
                return
            
            # Создаем оси для графика
            ax = self.figure.add_subplot(111)
            ax.set_facecolor(UIConfig.CHART_BACKGROUND_COLOR)
            ax.tick_params(colors=UIConfig.CHART_TEXT_COLOR)
            ax.spines['bottom'].set_color(UIConfig.CHART_TEXT_COLOR)
            ax.spines['top'].set_color(UIConfig.CHART_TEXT_COLOR)
            ax.spines['right'].set_color(UIConfig.CHART_TEXT_COLOR)
            ax.spines['left'].set_color(UIConfig.CHART_TEXT_COLOR)
            
            # Извлекаем данные для графика
            timestamps = [data.timestamp for data in price_data]
            closes = [float(data.close_price) for data in price_data]
            
            # Строим график цены
            ax.plot(timestamps, closes, color=UIConfig.ACCENT_COLOR, linewidth=1.5, label='Цена закрытия')
            ax.set_title(f'{instrument_symbol} - {timeframe_name}', 
                        color=UIConfig.CHART_TEXT_COLOR, fontsize=14)
            ax.set_xlabel('Время', color=UIConfig.CHART_TEXT_COLOR)
            ax.set_ylabel('Цена', color=UIConfig.CHART_TEXT_COLOR)
            ax.grid(True, color=UIConfig.CHART_GRID_COLOR, alpha=0.3)
            ax.legend()
            
            # Если указаны индикаторы, добавляем их
            if indicator_types:
                for indicator_type in indicator_types:
                    indicator_data = self.data_fetcher.get_indicator_data(
                        instrument_id, timeframe_id, indicator_type
                    )
                    if indicator_data:
                        values = [float(value) for _, value in indicator_data]
                        ax.plot(timestamps[:len(values)], values, 
                               label=indicator_type, alpha=0.7)
            
            # Обновляем график
            self.figure.tight_layout()
            self.canvas.draw()
            
            logger.info(f"График построен для {instrument_symbol} на {timeframe_name}")
            
        except Exception as e:
            logger.error(f"Ошибка при построении графика: {e}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось построить график: {str(e)}")


class SignalsTable(QTableWidget):
    """
    Таблица для отображения торговых сигналов.
    
    Отображает сигналы на покупку/продажу на основе анализа стратегий.
    """
    
    def __init__(self, parent=None):
        """
        Инициализация таблицы сигналов.
        
        Параметры:
            parent: Родительский виджет.
        """
        super().__init__(parent)
        self.setColumnCount(5)
        self.setHorizontalHeaderLabels([
            "Инструмент", "Таймфрейм", "Сигнал", "Цена", "Время"
        ])
        self.setStyleSheet(UIConfig.TABLE_STYLE)
        self.horizontalHeader().setStretchLastSection(True)
    
    def add_signal(self, instrument, timeframe, signal_type, price, timestamp):
        """
        Добавляет новый сигнал в таблицу.
        
        Параметры:
            instrument (str): Символ инструмента.
            timeframe (str): Таймфрейм.
            signal_type (str): Тип сигнала ('BUY' или 'SELL').
            price (float): Цена сигнала.
            timestamp: Время сигнала.
        """
        row = self.rowCount()
        self.insertRow(row)
        
        # Определяем цвет сигнала
        if signal_type == 'BUY':
            color = UIConfig.BUY_SIGNAL_COLOR
        elif signal_type == 'SELL':
            color = UIConfig.SELL_SIGNAL_COLOR
        else:
            color = UIConfig.NEUTRAL_SIGNAL_COLOR
        
        # Заполняем ячейки
        self.setItem(row, 0, QTableWidgetItem(instrument))
        self.setItem(row, 1, QTableWidgetItem(timeframe))
        signal_item = QTableWidgetItem(signal_type)
        signal_item.setForeground(QColor(color))
        self.setItem(row, 2, signal_item)
        self.setItem(row, 3, QTableWidgetItem(str(price)))
        self.setItem(row, 4, QTableWidgetItem(str(timestamp)))


class TradingApp(QMainWindow):
    """
    Главное окно приложения для анализа рынка и получения торговых сигналов.
    
    Содержит:
    - Виджет графика для отображения цен
    - Панель управления для выбора инструментов и таймфреймов
    - Таблицу торговых сигналов
    - Панель настроек
    """
    
    def __init__(self):
        """
        Инициализация главного окна приложения.
        """
        super().__init__()
        self.data_fetcher = DataFetcher()
        self.init_ui()
        self.apply_styles()
        
        # Таймер для обновления данных (каждые 100 секунд)
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_market_data)
        self.update_timer.start(100000)  # 100 секунд = 100000 миллисекунд
        
        # Загружаем инструменты из БД при запуске
        self.load_instruments_from_db()
    
    def init_ui(self):
        """
        Инициализация пользовательского интерфейса.
        """
        # Устанавливаем размеры и заголовок окна
        self.setWindowTitle("Торговый бот - Анализ рынка")
        self.setMinimumSize(UIConfig.MAIN_WINDOW_MIN_WIDTH, 
                           UIConfig.MAIN_WINDOW_MIN_HEIGHT)
        self.resize(UIConfig.MAIN_WINDOW_WIDTH, UIConfig.MAIN_WINDOW_HEIGHT)
        
        # Центрируем окно
        if UIConfig.MAIN_WINDOW_X is None or UIConfig.MAIN_WINDOW_Y is None:
            self.center_window()
        
        # Создаем центральный виджет
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Создаем главный layout
        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)
        
        # Создаем панель управления
        control_panel = self.create_control_panel()
        main_layout.addWidget(control_panel)
        
        # Создаем splitter для разделения графика и таблицы сигналов
        splitter = QSplitter(Qt.Horizontal)
        
        # Виджет графика
        self.chart_widget = ChartWidget()
        splitter.addWidget(self.chart_widget)
        
        # Панель с сигналами
        signals_panel = self.create_signals_panel()
        splitter.addWidget(signals_panel)
        
        # Устанавливаем пропорции (70% график, 30% сигналы)
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)
        
        main_layout.addWidget(splitter)
    
    def create_control_panel(self):
        """
        Создает панель управления для выбора инструментов и таймфреймов.
        
        Возвращает:
            QGroupBox: Группа с элементами управления.
        """
        group = QGroupBox("Настройки анализа")
        layout = QGridLayout()
        
        # Выбор инструмента
        layout.addWidget(QLabel("Инструмент:"), 0, 0)
        self.instrument_combo = QComboBox()
        self.instrument_combo.setStyleSheet(UIConfig.COMBO_BOX_STYLE)
        self.instrument_combo.setMinimumWidth(150)
        layout.addWidget(self.instrument_combo, 0, 1)
        
        # Кнопка загрузки данных с Yahoo Finance
        self.load_data_button = QPushButton("Загрузить данные")
        self.load_data_button.setStyleSheet(UIConfig.BUTTON_STYLE)
        self.load_data_button.clicked.connect(self.on_load_historical_data)
        layout.addWidget(self.load_data_button, 0, 2)
        
        # Выбор таймфрейма
        layout.addWidget(QLabel("Таймфрейм:"), 0, 3)
        self.timeframe_combo = QComboBox()
        self.timeframe_combo.setStyleSheet(UIConfig.COMBO_BOX_STYLE)
        self.timeframe_combo.setMinimumWidth(120)
        layout.addWidget(self.timeframe_combo, 0, 4)
        
        # Кнопка обновления графика
        self.update_button = QPushButton("Обновить график")
        self.update_button.setStyleSheet(UIConfig.BUTTON_STYLE)
        self.update_button.clicked.connect(self.on_update_chart)
        layout.addWidget(self.update_button, 0, 5)
        
        # Кнопка анализа сигналов
        self.analyze_button = QPushButton("Анализировать сигналы")
        self.analyze_button.setStyleSheet(UIConfig.BUTTON_STYLE)
        self.analyze_button.clicked.connect(self.on_analyze_signals)
        layout.addWidget(self.analyze_button, 0, 6)
        
        group.setLayout(layout)
        return group
    
    def create_signals_panel(self):
        """
        Создает панель для отображения торговых сигналов.
        
        Возвращает:
            QWidget: Виджет с таблицей сигналов.
        """
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Заголовок
        title = QLabel("Торговые сигналы")
        title.setStyleSheet(UIConfig.LABEL_HEADER_STYLE)
        layout.addWidget(title)
        
        # Таблица сигналов
        self.signals_table = SignalsTable()
        layout.addWidget(self.signals_table)
        
        widget.setLayout(layout)
        widget.setStyleSheet(UIConfig.PANEL_STYLE)
        widget.setFixedWidth(UIConfig.SIGNALS_PANEL_WIDTH)
        
        return widget
    
    def apply_styles(self):
        """
        Применяет стили из UIConfig ко всему приложению.
        """
        self.setStyleSheet(UIConfig.MAIN_WINDOW_STYLE)
    
    def center_window(self):
        """
        Центрирует окно на экране.
        """
        frame_geometry = self.frameGeometry()
        desktop = QDesktopWidget()
        screen = desktop.screenNumber(desktop.cursor().pos())
        center_point = desktop.screenGeometry(screen).center()
        frame_geometry.moveCenter(center_point)
        self.move(frame_geometry.topLeft())
    
    def on_update_chart(self):
        """
        Обработчик нажатия кнопки обновления графика.
        """
        instrument = self.instrument_combo.currentText()
        timeframe = self.timeframe_combo.currentText()
        
        if not instrument or not timeframe:
            QMessageBox.warning(self, "Предупреждение", 
                              "Выберите инструмент и таймфрейм")
            return
        
        logger.info(f"Обновление графика: {instrument} на {timeframe}")
        self.chart_widget.plot_chart(instrument, timeframe)
    
    def on_analyze_signals(self):
        """
        Обработчик нажатия кнопки анализа сигналов.
        
        Анализирует текущий рынок и генерирует торговые сигналы.
        """
        instrument = self.instrument_combo.currentText()
        timeframe = self.timeframe_combo.currentText()
        
        if not instrument or not timeframe:
            QMessageBox.warning(self, "Предупреждение", 
                              "Выберите инструмент и таймфрейм")
            return
        
        logger.info(f"Анализ сигналов для {instrument} на {timeframe}")
        
        # TODO: Реализовать логику анализа сигналов на основе стратегий
        # Пока что добавляем тестовый сигнал
        QMessageBox.information(self, "Информация", 
                               f"Анализ сигналов для {instrument} на {timeframe} будет реализован")
    
    def load_instruments_from_db(self):
        """
        Загружает список инструментов из базы данных и обновляет комбобокс.
        """
        try:
            instruments = self.data_fetcher.get_instruments()
            self.instrument_combo.clear()
            
            if instruments:
                for instrument in instruments:
                    self.instrument_combo.addItem(instrument.symbol)
                logger.info(f"Загружено {len(instruments)} инструментов из БД")
            else:
                logger.warning("В базе данных нет инструментов")
                self.instrument_combo.addItem("Нет инструментов")
            
            # Загружаем таймфреймы
            timeframes = self.data_fetcher.get_timeframes()
            self.timeframe_combo.clear()
            
            if timeframes:
                for timeframe in timeframes:
                    # Используем interval_name или name
                    tf_name = getattr(timeframe, 'interval_name', None) or getattr(timeframe, 'name', 'Unknown')
                    self.timeframe_combo.addItem(tf_name)
                logger.info(f"Загружено {len(timeframes)} таймфреймов из БД")
            else:
                logger.warning("В базе данных нет таймфреймов")
                self.timeframe_combo.addItem("Нет таймфреймов")
                
        except Exception as e:
            logger.error(f"Ошибка при загрузке инструментов из БД: {e}")
            QMessageBox.warning(self, "Ошибка", f"Не удалось загрузить инструменты: {str(e)}")
    
    def on_load_historical_data(self):
        """
        Обработчик нажатия кнопки загрузки исторических данных с Yahoo Finance.
        
        Загружает исторические данные за весь период существования монет
        и сохраняет их в базу данных.
        """
        try:
            from crypto_trading_bot.trading.yahoo_data_loader import YahooDataLoader
            from crypto_trading_bot.trading.top_coins_fetcher import TopCoinsFetcher
            
            reply = QMessageBox.question(
                self, 
                "Загрузка данных", 
                "Загрузить исторические данные для топ-30 монет с Yahoo Finance?\n\n"
                "Будут загружены данные за весь период существования монет.\n"
                "Это может занять 10-30 минут.",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                # Показываем прогресс
                progress_msg = QMessageBox(self)
                progress_msg.setWindowTitle("Загрузка данных")
                progress_msg.setText("Начата загрузка исторических данных...\nПроверьте логи для отслеживания прогресса.")
                progress_msg.setStandardButtons(QMessageBox.Ok)
                progress_msg.show()
                
                try:
                    loader = YahooDataLoader()
                    top_fetcher = TopCoinsFetcher()
                    
                    # Получаем топ-30 монет по объему торгов
                    logger.info("Получение списка топ-30 монет...")
                    top_coins = top_fetcher.get_top_coins_by_volume(30)
                    
                    if not top_coins:
                        QMessageBox.warning(self, "Ошибка", "Не удалось получить список топ-монет")
                        return
                    
                    symbols = [coin['symbol'] for coin in top_coins]
                    logger.info(f"Найдено {len(symbols)} монет для загрузки: {symbols[:5]}...")
                    
                    # Загружаем данные для всех монет по всем таймфреймам
                    # За весь период существования (period="max")
                    timeframes = ['1day', '4hour', '1hour', '15min']
                    
                    logger.info(f"Начало загрузки данных для {len(symbols)} инструментов...")
                    results = loader.load_data_for_top_coins(symbols, timeframes)
                    
                    # Подсчитываем успешно загруженные
                    success_count = sum(1 for symbol_results in results.values() 
                                      for success in symbol_results.values() if success)
                    
                    # Обновляем список инструментов в интерфейсе
                    self.load_instruments_from_db()
                    
                    progress_msg.close()
                    
                    QMessageBox.information(
                        self, 
                        "Завершено", 
                        f"Загрузка данных завершена!\n\n"
                        f"Обработано инструментов: {len(symbols)}\n"
                        f"Успешно загружено: {success_count} наборов данных\n\n"
                        f"Данные сохранены в базу данных.\n"
                        f"Автоматическое обновление будет каждые 100 секунд."
                    )
                    
                except Exception as e:
                    progress_msg.close()
                    logger.exception(f"Ошибка при загрузке данных: {e}")
                    QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить данные:\n{str(e)}")
                
        except Exception as e:
            logger.error(f"Ошибка при загрузке данных: {e}")
            QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить данные: {str(e)}")
    
    def update_market_data(self):
        """
        Обновляет данные рынка (вызывается по таймеру каждые 100 секунд).
        
        Получает последние свечи из открытых источников (Yahoo Finance) 
        и обновляет их в базе данных.
        """
        try:
            logger.info("Обновление данных рынка (каждые 100 секунд)")
            
            # Получаем все инструменты из БД
            instruments = self.data_fetcher.get_instruments()
            
            if not instruments:
                logger.warning("Нет инструментов для обновления")
                return
            
            from crypto_trading_bot.trading.yahoo_data_loader import YahooDataLoader
            loader = YahooDataLoader()
            
            # Обновляем данные для каждого инструмента
            updated_count = 0
            for instrument in instruments:
                try:
                    symbol = instrument.symbol
                    logger.debug(f"Обновление данных для {symbol}...")
                    
                    # Получаем последние данные с Yahoo Finance (последние 5 дней для обновления)
                    # Загружаем только для основных таймфреймов
                    timeframes = ['1day', '4hour', '1hour']
                    
                    for timeframe in timeframes:
                        try:
                            # Загружаем последние данные (5 дней назад)
                            df = loader.load_historical_data(symbol, timeframe, period="5d")
                            
                            if df is not None and not df.empty:
                                # Сохраняем только последние свечи (обновление)
                                success = loader.save_data_to_db(symbol, timeframe, df)
                                if success:
                                    updated_count += 1
                        except Exception as e:
                            logger.warning(f"Ошибка при обновлении {symbol} на {timeframe}: {e}")
                            continue
                    
                    # Небольшая задержка между инструментами
                    import time
                    time.sleep(0.3)
                    
                except Exception as e:
                    logger.error(f"Ошибка при обновлении данных для {instrument.symbol}: {e}")
                    continue
            
            logger.info(f"Обновление завершено. Обновлено {updated_count} записей")
            
            # Если график отображен, обновляем его
            current_instrument = self.instrument_combo.currentText()
            current_timeframe = self.timeframe_combo.currentText()
            
            if (current_instrument and current_timeframe and 
                current_instrument != "Нет инструментов" and
                hasattr(self.chart_widget, 'price_data') and self.chart_widget.price_data):
                logger.debug(f"Обновление графика для {current_instrument} на {current_timeframe}")
                self.chart_widget.plot_chart(current_instrument, current_timeframe)
                    
        except Exception as e:
            logger.error(f"Ошибка при обновлении данных рынка: {e}")


def main():
    """
    Точка входа в приложение.
    
    Создает и запускает PyQt5 приложение для анализа рынка.
    """
    app = QApplication(sys.argv)
    
    # Устанавливаем шрифт по умолчанию
    font = QFont(UIConfig.FONT_FAMILY, UIConfig.FONT_SIZE_NORMAL)
    app.setFont(font)
    
    # Создаем и показываем главное окно
    window = TradingApp()
    window.show()
    
    logger.info("Приложение запущено")
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

