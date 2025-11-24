"""
Модуль для рисования паттернов на графиках.

Предоставляет функционал для интерактивного рисования паттернов
(линии поддержки/сопротивления, фигуры, уровни) на графиках цен.
"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel, QListWidget
from PyQt5.QtCore import Qt, pyqtSignal
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle, Circle, Polygon
from matplotlib.lines import Line2D
import numpy as np
from loguru import logger
from typing import List, Dict, Tuple

from gui.ui_config import UIConfig


class PatternDrawer(FigureCanvas):
    """
    Виджет для рисования паттернов на графиках.
    
    Позволяет пользователю интерактивно рисовать:
    - Линии поддержки/сопротивления
    - Треугольники, прямоугольники
    - Уровни входа/выхода
    - Другие технические паттерны
    """
    
    # Сигналы для уведомления о создании паттернов
    pattern_created = pyqtSignal(dict)  # Передает информацию о созданном паттерне
    
    def __init__(self, parent=None):
        """
        Инициализация виджета для рисования паттернов.
        
        Параметры:
            parent: Родительский виджет.
        """
        self.figure = Figure(figsize=(12, 6))
        self.figure.patch.set_facecolor(UIConfig.CHART_BACKGROUND_COLOR)
        super().__init__(self.figure)
        
        self.ax = self.figure.add_subplot(111)
        self.ax.set_facecolor(UIConfig.CHART_BACKGROUND_COLOR)
        self.ax.tick_params(colors=UIConfig.CHART_TEXT_COLOR)
        
        # Состояние рисования
        self.drawing_mode = None  # 'line', 'rectangle', 'triangle', 'circle', None
        self.start_point = None
        self.current_patterns = []  # Список нарисованных паттернов
        self.selected_pattern = None
        
        # Подключаем события мыши
        self.mpl_connect('button_press_event', self.on_mouse_press)
        self.mpl_connect('motion_notify_event', self.on_mouse_move)
        self.mpl_connect('button_release_event', self.on_mouse_release)
        
        # Данные графика
        self.price_data = None
        self.timestamps = None
        
    def plot_price_data(self, timestamps, prices, symbol: str = ""):
        """
        Отображает данные о ценах на графике.
        
        Параметры:
            timestamps: Массив временных меток.
            prices: Массив цен.
            symbol (str): Символ инструмента для отображения в заголовке.
        """
        self.ax.clear()
        self.ax.set_facecolor(UIConfig.CHART_BACKGROUND_COLOR)
        self.ax.tick_params(colors=UIConfig.CHART_TEXT_COLOR)
        
        self.timestamps = timestamps
        self.price_data = prices
        
        # Строим график цены
        self.ax.plot(timestamps, prices, color=UIConfig.ACCENT_COLOR, linewidth=1.5, label='Цена')
        self.ax.set_title(f'{symbol} - График с паттернами', 
                         color=UIConfig.CHART_TEXT_COLOR, fontsize=14)
        self.ax.set_xlabel('Время', color=UIConfig.CHART_TEXT_COLOR)
        self.ax.set_ylabel('Цена', color=UIConfig.CHART_TEXT_COLOR)
        self.ax.grid(True, color=UIConfig.CHART_GRID_COLOR, alpha=0.3)
        self.ax.legend()
        
        # Восстанавливаем нарисованные паттерны
        self.redraw_patterns()
        
        self.draw()
    
    def set_drawing_mode(self, mode: str):
        """
        Устанавливает режим рисования.
        
        Параметры:
            mode (str): Режим рисования ('line', 'rectangle', 'triangle', 'circle', None).
        """
        self.drawing_mode = mode
        logger.info(f"Режим рисования установлен: {mode}")
    
    def on_mouse_press(self, event):
        """
        Обработчик нажатия кнопки мыши.
        
        Параметры:
            event: Событие мыши matplotlib.
        """
        if event.inaxes != self.ax or event.button != 1:  # Левая кнопка мыши
            return
        
        if self.drawing_mode:
            self.start_point = (event.xdata, event.ydata)
            logger.debug(f"Начало рисования паттерна {self.drawing_mode} в точке ({event.xdata}, {event.ydata})")
    
    def on_mouse_move(self, event):
        """
        Обработчик движения мыши (для предпросмотра паттерна).
        
        Параметры:
            event: Событие мыши matplotlib.
        """
        if not self.drawing_mode or not self.start_point or event.inaxes != self.ax:
            return
        
        # TODO: Реализовать предпросмотр паттерна при движении мыши
    
    def on_mouse_release(self, event):
        """
        Обработчик отпускания кнопки мыши (завершение рисования).
        
        Параметры:
            event: Событие мыши matplotlib.
        """
        if not self.drawing_mode or not self.start_point or event.inaxes != self.ax:
            return
        
        if event.button != 1:  # Левая кнопка мыши
            return
        
        end_point = (event.xdata, event.ydata)
        
        # Создаем паттерн в зависимости от режима
        pattern = None
        pattern_info = {
            'type': self.drawing_mode,
            'start': self.start_point,
            'end': end_point
        }
        
        if self.drawing_mode == 'line':
            pattern = self.create_line_pattern(self.start_point, end_point)
        elif self.drawing_mode == 'rectangle':
            pattern = self.create_rectangle_pattern(self.start_point, end_point)
        elif self.drawing_mode == 'triangle':
            pattern = self.create_triangle_pattern(self.start_point, end_point)
        elif self.drawing_mode == 'circle':
            pattern = self.create_circle_pattern(self.start_point, end_point)
        
        if pattern:
            self.current_patterns.append({
                'pattern': pattern,
                'info': pattern_info
            })
            self.ax.add_patch(pattern) if hasattr(pattern, 'set_transform') else self.ax.add_line(pattern)
            self.draw()
            
            # Отправляем сигнал о создании паттерна
            self.pattern_created.emit(pattern_info)
            logger.info(f"Паттерн {self.drawing_mode} создан")
        
        # Сбрасываем состояние
        self.start_point = None
    
    def create_line_pattern(self, start: Tuple, end: Tuple) -> Line2D:
        """
        Создает линию (поддержка/сопротивление).
        
        Параметры:
            start: Начальная точка (x, y).
            end: Конечная точка (x, y).
        
        Возвращает:
            Line2D: Объект линии matplotlib.
        """
        line = Line2D([start[0], end[0]], [start[1], end[1]], 
                     color=UIConfig.BUY_SIGNAL_COLOR, linewidth=2, linestyle='--')
        return line
    
    def create_rectangle_pattern(self, start: Tuple, end: Tuple) -> Rectangle:
        """
        Создает прямоугольник (зона консолидации).
        
        Параметры:
            start: Начальная точка (x, y).
            end: Конечная точка (x, y).
        
        Возвращает:
            Rectangle: Объект прямоугольника matplotlib.
        """
        width = abs(end[0] - start[0])
        height = abs(end[1] - start[1])
        x = min(start[0], end[0])
        y = min(start[1], end[1])
        
        rect = Rectangle((x, y), width, height, 
                        linewidth=2, edgecolor=UIConfig.ACCENT_COLOR, 
                        facecolor='none', linestyle='--')
        return rect
    
    def create_triangle_pattern(self, start: Tuple, end: Tuple) -> Polygon:
        """
        Создает треугольник (паттерн треугольника).
        
        Параметры:
            start: Начальная точка (x, y).
            end: Конечная точка (x, y).
        
        Возвращает:
            Polygon: Объект треугольника matplotlib.
        """
        # Создаем треугольник с вершинами: start, end, и средняя точка по x
        mid_x = (start[0] + end[0]) / 2
        mid_y = min(start[1], end[1]) - abs(end[1] - start[1]) * 0.5
        
        triangle = Polygon([start, end, (mid_x, mid_y)], 
                          linewidth=2, edgecolor=UIConfig.SELL_SIGNAL_COLOR, 
                          facecolor='none', linestyle='--')
        return triangle
    
    def create_circle_pattern(self, start: Tuple, end: Tuple) -> Circle:
        """
        Создает круг (зона интереса).
        
        Параметры:
            start: Центр круга (x, y).
            end: Точка на окружности (x, y).
        
        Возвращает:
            Circle: Объект круга matplotlib.
        """
        radius = np.sqrt((end[0] - start[0])**2 + (end[1] - start[1])**2)
        
        circle = Circle(start, radius, 
                       linewidth=2, edgecolor=UIConfig.NEUTRAL_SIGNAL_COLOR, 
                       facecolor='none', linestyle='--')
        return circle
    
    def redraw_patterns(self):
        """
        Перерисовывает все сохраненные паттерны.
        """
        for pattern_data in self.current_patterns:
            pattern = pattern_data['pattern']
            if hasattr(pattern, 'set_transform'):
                self.ax.add_patch(pattern)
            else:
                self.ax.add_line(pattern)
    
    def clear_patterns(self):
        """
        Удаляет все нарисованные паттерны.
        """
        self.current_patterns.clear()
        self.ax.clear()
        if self.price_data is not None and self.timestamps is not None:
            self.ax.plot(self.timestamps, self.price_data, color=UIConfig.ACCENT_COLOR, linewidth=1.5)
        self.draw()
        logger.info("Все паттерны удалены")
    
    def get_patterns(self) -> List[Dict]:
        """
        Возвращает список всех нарисованных паттернов.
        
        Возвращает:
            list[dict]: Список словарей с информацией о паттернах.
        """
        return [pattern_data['info'] for pattern_data in self.current_patterns]
    
    def delete_pattern(self, pattern_index: int):
        """
        Удаляет паттерн по индексу.
        
        Параметры:
            pattern_index (int): Индекс паттерна в списке.
        """
        if 0 <= pattern_index < len(self.current_patterns):
            pattern_data = self.current_patterns.pop(pattern_index)
            pattern_data['pattern'].remove()
            self.draw()
            logger.info(f"Паттерн {pattern_index} удален")

