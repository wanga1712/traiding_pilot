"""
Утилиты для отрисовки графиков (обратная совместимость).

Импортирует функции из специализированных модулей.
"""

# Импортируем из новых модулей для обратной совместимости
from gui.chart_formatters import apply_price_formatter, apply_time_axis_formatting
from gui.chart_calculators import calculate_candle_width, prepare_plot_payload
from gui.chart_drawers import draw_price, draw_volume, draw_dma_lines

__all__ = [
    'apply_price_formatter',
    'apply_time_axis_formatting',
    'calculate_candle_width',
    'prepare_plot_payload',
    'draw_price',
    'draw_volume',
    'draw_dma_lines'
]
