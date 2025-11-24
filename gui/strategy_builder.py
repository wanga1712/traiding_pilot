"""
Модуль для построения торговых стратегий на основе паттернов.

Позволяет создавать стратегии входа/выхода на основе нарисованных паттернов.
"""
from typing import List, Dict, Tuple, Optional
from loguru import logger
from datetime import datetime
import numpy as np


class PatternStrategy:
    """
    Класс для представления торговой стратегии на основе паттерна.
    """
    
    def __init__(self, pattern_type: str, pattern_data: Dict, entry_conditions: Dict, exit_conditions: Dict):
        """
        Инициализация стратегии на основе паттерна.
        
        Параметры:
            pattern_type (str): Тип паттерна ('line', 'rectangle', 'triangle', 'circle').
            pattern_data (dict): Данные паттерна (координаты, параметры).
            entry_conditions (dict): Условия входа в сделку.
            exit_conditions (dict): Условия выхода из сделки.
        """
        self.pattern_type = pattern_type
        self.pattern_data = pattern_data
        self.entry_conditions = entry_conditions
        self.exit_conditions = exit_conditions
        self.created_at = datetime.now()
    
    def check_entry_signal(self, price_data: np.ndarray, timestamps: np.ndarray) -> Optional[Dict]:
        """
        Проверяет условия входа в сделку.
        
        Параметры:
            price_data: Массив цен.
            timestamps: Массив временных меток.
        
        Возвращает:
            dict или None: Информация о сигнале входа или None, если условия не выполнены.
        """
        # TODO: Реализовать логику проверки условий входа на основе паттерна
        return None
    
    def check_exit_signal(self, entry_price: float, current_price: float, entry_time: datetime) -> Optional[Dict]:
        """
        Проверяет условия выхода из сделки.
        
        Параметры:
            entry_price (float): Цена входа.
            current_price (float): Текущая цена.
            entry_time (datetime): Время входа.
        
        Возвращает:
            dict или None: Информация о сигнале выхода или None.
        """
        # TODO: Реализовать логику проверки условий выхода
        return None


class StrategyBuilder:
    """
    Класс для построения торговых стратегий на основе паттернов.
    """
    
    def __init__(self):
        """
        Инициализация построителя стратегий.
        """
        self.strategies = []  # Список созданных стратегий
    
    def create_strategy_from_pattern(self, pattern: Dict, entry_rules: Dict, exit_rules: Dict) -> PatternStrategy:
        """
        Создает стратегию на основе паттерна.
        
        Параметры:
            pattern (dict): Информация о паттерне.
            entry_rules (dict): Правила входа (например, пробой уровня, отскок).
            exit_rules (dict): Правила выхода (take profit, stop loss, по времени).
        
        Возвращает:
            PatternStrategy: Созданная стратегия.
        """
        strategy = PatternStrategy(
            pattern_type=pattern['type'],
            pattern_data=pattern,
            entry_conditions=entry_rules,
            exit_conditions=exit_rules
        )
        
        self.strategies.append(strategy)
        logger.info(f"Стратегия создана на основе паттерна {pattern['type']}")
        
        return strategy
    
    def create_line_breakout_strategy(self, line_pattern: Dict, direction: str = 'up', 
                                     profit_target: float = 0.02, stop_loss: float = 0.01) -> PatternStrategy:
        """
        Создает стратегию пробоя линии поддержки/сопротивления.
        
        Параметры:
            line_pattern (dict): Данные линии паттерна.
            direction (str): Направление пробоя ('up' или 'down').
            profit_target (float): Целевая прибыль в процентах (например, 0.02 = 2%).
            stop_loss (float): Стоп-лосс в процентах.
        
        Возвращает:
            PatternStrategy: Созданная стратегия.
        """
        entry_rules = {
            'type': 'breakout',
            'direction': direction,
            'pattern': line_pattern
        }
        
        exit_rules = {
            'take_profit_percent': profit_target,
            'stop_loss_percent': stop_loss,
            'type': 'price_target'
        }
        
        return self.create_strategy_from_pattern(line_pattern, entry_rules, exit_rules)
    
    def create_rectangle_range_strategy(self, rectangle_pattern: Dict, 
                                       entry_type: str = 'bounce', 
                                       profit_target: float = 0.015) -> PatternStrategy:
        """
        Создает стратегию торговли в диапазоне (прямоугольник).
        
        Параметры:
            rectangle_pattern (dict): Данные прямоугольника.
            entry_type (str): Тип входа ('bounce' - отскок от границ, 'breakout' - пробой).
            profit_target (float): Целевая прибыль в процентах.
        
        Возвращает:
            PatternStrategy: Созданная стратегия.
        """
        entry_rules = {
            'type': entry_type,
            'pattern': rectangle_pattern
        }
        
        exit_rules = {
            'take_profit_percent': profit_target,
            'type': 'range_exit'
        }
        
        return self.create_strategy_from_pattern(rectangle_pattern, entry_rules, exit_rules)
    
    def get_strategies(self) -> List[PatternStrategy]:
        """
        Возвращает список всех созданных стратегий.
        
        Возвращает:
            list[PatternStrategy]: Список стратегий.
        """
        return self.strategies
    
    def delete_strategy(self, strategy_index: int):
        """
        Удаляет стратегию по индексу.
        
        Параметры:
            strategy_index (int): Индекс стратегии.
        """
        if 0 <= strategy_index < len(self.strategies):
            self.strategies.pop(strategy_index)
            logger.info(f"Стратегия {strategy_index} удалена")

