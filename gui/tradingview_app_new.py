"""
Главное приложение TradingView-style для анализа криптовалют.

Использует модули:
- chart_widget: Виджет графика
- instruments_list_widget: Список инструментов
- timeframe_panel_widget: Панель таймфреймов
"""

import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QSplitter
)
from PyQt5.QtCore import Qt, QTimer
from threading import Thread
from loguru import logger

from gui.ui_config import UIConfig
from gui.data_fetcher import DataFetcher
from gui.chart_widget import CandlestickChartWidget
from gui.instruments_list_widget import InstrumentsListWidget
from gui.timeframe_panel_widget import TimeframePanelWidget
from crypto_trading_bot.trading.data_updater import DataUpdater


class TradingViewApp(QMainWindow):
    """
    Главное окно приложения в стиле TradingView.
    """
    
    def __init__(self):
        """Инициализация главного окна."""
        super().__init__()
        self.data_fetcher = DataFetcher()
        self.current_instrument = None
        self.current_timeframe = "1d"
        self.is_first_show = True
        self.data_updater = DataUpdater()
        
        self.init_ui()
        self.load_instruments()
        
        self.geometry_change_timer = QTimer()
        self.geometry_change_timer.setSingleShot(True)
        self.geometry_change_timer.timeout.connect(self.on_geometry_changed)
        
        self.chart_update_timer = QTimer()
        self.chart_update_timer.timeout.connect(self.update_chart_if_needed)
        self.start_chart_auto_update()
        self.start_data_update()
    
    def init_ui(self):
        """Инициализация пользовательского интерфейса."""
        self.setWindowTitle("Trading Bot - TradingView Style")
        self.setStyleSheet(f"QMainWindow {{ background-color: {UIConfig.BACKGROUND_COLOR}; }}")
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        central_widget.setLayout(main_layout)
        
        main_splitter = QSplitter(Qt.Horizontal)
        
        self.instruments_list = InstrumentsListWidget()
        self.instruments_list.instrument_selected.connect(self.on_instrument_selected)
        main_splitter.addWidget(self.instruments_list)
        
        right_panel = QWidget()
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        
        self.chart_widget = CandlestickChartWidget()
        right_layout.addWidget(self.chart_widget)
        
        self.timeframe_panel = TimeframePanelWidget()
        self.timeframe_panel.timeframe_changed.connect(self.on_timeframe_changed)
        self.timeframe_panel.setStyleSheet(f"{self.timeframe_panel.styleSheet()} background-color: transparent;")
        
        right_panel.setLayout(right_layout)
        self.timeframe_panel.setParent(right_panel)
        self.timeframe_panel.setGeometry(5, 5, self.timeframe_panel.sizeHint().width(), self.timeframe_panel.sizeHint().height())
        self.timeframe_panel.raise_()
        
        main_splitter.addWidget(right_panel)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 4)
        main_splitter.setSizes([UIConfig.INSTRUMENTS_PANEL_WIDTH, 1200])
        
        main_layout.addWidget(main_splitter)
        self.setMinimumSize(UIConfig.MAIN_WINDOW_MIN_WIDTH, UIConfig.MAIN_WINDOW_MIN_HEIGHT)
        self.right_panel = right_panel
    
    def showEvent(self, event):
        """Обработчик события показа окна."""
        super().showEvent(event)
        if self.is_first_show:
            self.is_first_show = False
            self.showMaximized()
    
    def resizeEvent(self, event):
        """Обработчик изменения размера окна."""
        super().resizeEvent(event)
        if hasattr(self, 'timeframe_panel') and hasattr(self, 'right_panel'):
            panel_size = self.timeframe_panel.sizeHint()
            self.timeframe_panel.setGeometry(5, 5, panel_size.width(), panel_size.height())
    
    def moveEvent(self, event):
        """Обработчик перемещения окна."""
        super().moveEvent(event)
        self.geometry_change_timer.start(100)
    
    def on_geometry_changed(self):
        """Обработчик изменения геометрии окна."""
        screen = QApplication.screenAt(self.geometry().center())
        if screen:
            screen_geometry = screen.availableGeometry()
            current_geometry = self.geometry()
            if (current_geometry.x() < screen_geometry.x() or
                current_geometry.y() < screen_geometry.y() or
                current_geometry.right() > screen_geometry.right() or
                current_geometry.bottom() > screen_geometry.bottom()):
                self.showMaximized()
    
    def load_instruments(self):
        """Загружает список инструментов из БД."""
        try:
            instruments = self.data_fetcher.get_instruments()
            self.instruments_list.load_instruments(instruments)
            logger.info(f"Загружено {len(instruments)} инструментов")
        except Exception as e:
            logger.error(f"Ошибка при загрузке инструментов: {e}")
    
    def on_instrument_selected(self, symbol: str):
        """Обработчик выбора инструмента."""
        self.current_instrument = symbol
        logger.info(f"Выбран инструмент: {symbol}, таймфрейм: {self.current_timeframe}")
        self.chart_widget.plot_candlestick(symbol, self.current_timeframe)
    
    def on_timeframe_changed(self, timeframe_code: str):
        """Обработчик изменения таймфрейма."""
        self.current_timeframe = timeframe_code
        if self.current_instrument:
            self.chart_widget.plot_candlestick(self.current_instrument, timeframe_code)
        self.start_chart_auto_update()
    
    def get_update_interval_ms(self, timeframe_code: str) -> int:
        """Возвращает интервал обновления графика в миллисекундах."""
        intervals = {
            '1m': 60 * 1000, '3m': 3 * 60 * 1000, '5m': 5 * 60 * 1000,
            '15m': 15 * 60 * 1000, '30m': 30 * 60 * 1000,
            '1h': 60 * 60 * 1000, '2h': 2 * 60 * 60 * 1000,
            '4h': 4 * 60 * 60 * 1000, '6h': 6 * 60 * 60 * 1000,
            '12h': 12 * 60 * 60 * 1000, '1d': 24 * 60 * 60 * 1000,
            '1w': 7 * 24 * 60 * 60 * 1000, '1mo': 30 * 24 * 60 * 60 * 1000,
        }
        return intervals.get(timeframe_code, 60 * 1000)
    
    def start_chart_auto_update(self):
        """Запускает автоматическое обновление графика."""
        if self.chart_update_timer.isActive():
            self.chart_update_timer.stop()
        interval_ms = self.get_update_interval_ms(self.current_timeframe)
        self.chart_update_timer.start(interval_ms)
        logger.info(f"Автообновление графика: {interval_ms/1000} сек для {self.current_timeframe}")
    
    def update_chart_if_needed(self):
        """Обновляет график, если выбран инструмент."""
        if self.current_instrument:
            self.chart_widget.plot_candlestick(self.current_instrument, self.current_timeframe)
    
    def start_data_update(self):
        """Запускает обновление данных в фоне."""
        def update_in_background():
            try:
                logger.info("Начало проверки и загрузки недостающих данных...")
                self.data_updater.update_all_instruments(force_all=True)
                logger.info("Недостающие данные загружены, запуск периодического обновления...")
                self.data_updater.start_background_update(base_check_interval=60)
            except Exception as e:
                logger.error(f"Ошибка при обновлении данных в фоне: {e}")
        
        update_thread = Thread(target=update_in_background, daemon=True)
        update_thread.start()
        logger.info("Запущен фоновый поток обновления данных")
    
    def closeEvent(self, event):
        """Обработчик закрытия окна."""
        logger.info("Закрытие приложения, остановка фонового обновления...")
        self.data_updater.stop_background_update()
        super().closeEvent(event)


def main():
    """Точка входа в приложение."""
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    
    app = QApplication(sys.argv)
    window = TradingViewApp()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()

