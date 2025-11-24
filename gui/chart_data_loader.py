"""
Загрузка данных для графика из БД.

Содержит функции для получения инструментов, таймфреймов и данных цен.
"""

from loguru import logger

from gui.data_fetcher import DataFetcher
from crypto_trading_bot.database.data_import import DataImport


class ChartDataLoader:
    """
    Класс для загрузки данных из БД.
    """
    
    def __init__(self):
        """Инициализация загрузчика данных."""
        self.data_fetcher = DataFetcher()
        self.data_import = DataImport()
    
    def get_instrument_and_timeframe(self, instrument_symbol: str, timeframe_code: str):
        """
        Получает объекты инструмента и таймфрейма из БД.
        
        Возвращает:
            tuple: (instrument, timeframe) или (None, None) если не найдены
        """
        instruments = self.data_fetcher.get_instruments()
        instrument = next((inst for inst in instruments if inst.symbol == instrument_symbol), None)
        
        if not instrument:
            logger.error(f"Инструмент {instrument_symbol} не найден")
            return None, None
        
        timeframes = self.data_fetcher.get_timeframes()
        timeframe = None
        for tf in timeframes:
            tf_name = getattr(tf, 'interval_name', None) or getattr(tf, 'name', None) or getattr(tf, 'timeframe_name', None)
            if tf_name == timeframe_code:
                timeframe = tf
                break
        
        if not timeframe:
            logger.error(f"Таймфрейм {timeframe_code} не найден")
            return None, None
        
        return instrument, timeframe
    
    def load_price_data(self, instrument_id: int, timeframe_id: int):
        """
        Загружает данные цен из БД.
        
        Возвращает:
            Список кортежей с данными цен или None
        """
        price_data = self.data_import.get_price_data(instrument_id, timeframe_id)
        if not price_data:
            return None
        return price_data

