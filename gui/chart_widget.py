"""
Виджет для отображения свечного графика.

Использует модули chart_utils и chart_data_processor для отрисовки графика.
"""

from PyQt5.QtWidgets import QWidget, QVBoxLayout
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter
from loguru import logger

from gui.ui_config import UIConfig
from gui.chart_utils import (
    apply_price_formatter, apply_time_axis_formatting,
    prepare_plot_payload, draw_price, draw_volume, draw_dma_lines
)
from gui.chart_data_processor import ChartDataProcessor


class CandlestickChartWidget(QWidget):
    """
    Виджет для отображения свечного графика.
    """
    
    def __init__(self, parent=None):
        """Инициализация виджета графика."""
        super().__init__(parent)
        self.data_processor = ChartDataProcessor()
        
        self.figure = Figure(figsize=(20, 12), facecolor=UIConfig.CHART_BACKGROUND_COLOR, dpi=100)
        self.canvas = FigureCanvas(self.figure)
        self.toolbar = NavigationToolbar(self.canvas, self)
        
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        layout.addWidget(self.toolbar)
        self.setLayout(layout)
        
        self.setStyleSheet(f"background-color: {UIConfig.CHART_BACKGROUND_COLOR};")
        
        self.current_instrument = None
        self.current_timeframe = "1d"
    
    def plot_candlestick(self, instrument_symbol: str, timeframe_code: str):
        """
        Отрисовывает свечной график для указанного инструмента и таймфрейма.
        
        Параметры:
            instrument_symbol: Символ инструмента (например, 'BTCUSDT').
            timeframe_code: Код таймфрейма из БД (например, '1d', '1h', '5m').
        """
        try:
            logger.info(f"Отрисовка графика для {instrument_symbol} на таймфрейме {timeframe_code}")
            
            # Получаем данные
            df = self.data_processor.prepare_chart_data(instrument_symbol, timeframe_code)
            if df is None or df.empty:
                return
            
            # Подготавливаем данные для отрисовки
            payload = prepare_plot_payload(df, timeframe_code)
            
            # Очищаем и создаем subplots
            self.figure.clear()
            grid_spec = self.figure.add_gridspec(2, 1, height_ratios=[4, 1], hspace=0.06)
            ax_price = self.figure.add_subplot(grid_spec[0])
            ax_volume = self.figure.add_subplot(grid_spec[1], sharex=ax_price)
            
            # Отрисовываем графики
            draw_price(ax_price, payload)
            draw_volume(ax_volume, payload)
            draw_dma_lines(ax_price, instrument_symbol, timeframe_code, df.index)
            
            # Форматируем оси
            apply_time_axis_formatting(ax_price, timeframe_code, df)
            apply_price_formatter(ax_price)
            
            # Настраиваем стиль оси цен
            ax_price.tick_params(axis='x', colors=UIConfig.CHART_TEXT_COLOR, labelsize=12, labelbottom=False)
            ax_price.set_facecolor(UIConfig.CHART_BACKGROUND_COLOR)
            ax_price.tick_params(axis='y', colors=UIConfig.CHART_TEXT_COLOR, labelsize=14)
            ax_price.spines['bottom'].set_color(UIConfig.CHART_GRID_COLOR)
            ax_price.spines['top'].set_color(UIConfig.CHART_GRID_COLOR)
            ax_price.spines['right'].set_color(UIConfig.CHART_GRID_COLOR)
            ax_price.spines['left'].set_color(UIConfig.CHART_GRID_COLOR)
            ax_price.yaxis.tick_right()
            ax_price.yaxis.set_label_position('right')
            
            # Добавляем легенду только если есть линии с лейблами
            # Размещаем в правом верхнем углу, чтобы не мешать панели таймфреймов
            handles, labels = ax_price.get_legend_handles_labels()
            if handles:
                ax_price.legend(loc='upper right', fontsize=9, framealpha=0.9,
                               facecolor=UIConfig.CHART_BACKGROUND_COLOR,
                               edgecolor=UIConfig.CHART_GRID_COLOR,
                               labelspacing=0.5, handlelength=1.5)
            
            # Настраиваем стиль оси объемов
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
            
            # Увеличиваем верхний отступ для панели таймфреймов и правый для легенды
            self.figure.subplots_adjust(left=0.05, right=0.92, bottom=0.12, top=0.88)
            
            try:
                self.canvas.draw()
                logger.info("Canvas обновлен успешно")
            except Exception as e:
                logger.error(f"Ошибка при обновлении canvas: {e}")
                import traceback
                logger.error(traceback.format_exc())
                return
            
            self.current_instrument = instrument_symbol
            self.current_timeframe = timeframe_code
            
            logger.info(f"График отрисован: {instrument_symbol} {timeframe_code} ({len(df)} свечей)")
            
        except Exception as e:
            logger.error(f"Ошибка при отрисовке графика: {e}")
            import traceback
            logger.error(traceback.format_exc())

