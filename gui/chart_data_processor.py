"""
Обработка данных для графика.

Объединяет загрузку и конвертацию данных для отрисовки графика.
"""

from loguru import logger

from gui.chart_data_loader import ChartDataLoader
from gui.chart_data_converter import ChartDataConverter
from gui.chart_data_validator import ChartDataValidator
from crypto_trading_bot.analytics.dinapoli_dma import DinapoliDMAService


class ChartDataProcessor:
    """
    Класс для обработки данных для графика.
    """
    
    def __init__(self):
        """Инициализация процессора данных."""
        self.data_loader = ChartDataLoader()
        self.data_converter = ChartDataConverter()
        self.data_validator = ChartDataValidator()
        self.dma_service = DinapoliDMAService()
    
    def get_instrument_and_timeframe(self, instrument_symbol: str, timeframe_code: str):
        """
        Получает объекты инструмента и таймфрейма из БД.
        
        Возвращает:
            tuple: (instrument, timeframe) или (None, None) если не найдены
        """
        return self.data_loader.get_instrument_and_timeframe(instrument_symbol, timeframe_code)
    
    def process_price_data(self, price_data, instrument_symbol: str, timeframe_code: str):
        """
        Обрабатывает данные цен из БД и преобразует в DataFrame.
        
        Возвращает:
            pd.DataFrame или None в случае ошибки
        """
        if not price_data:
            logger.warning(f"Нет данных для {instrument_symbol} на таймфрейме {timeframe_code}")
            return None
        
        # Конвертируем в DataFrame
        df = self.data_converter.process_price_data(price_data, instrument_symbol, timeframe_code)
        if df is None:
            return None
        
        # Ограничиваем количество свечей
        df = self.data_validator.limit_candles(df, timeframe_code)
        
        # Подготавливаем колонки
        df = self.data_validator.prepare_columns(df)
        if df is None:
            return None
        
        # Конвертируем timezone
        df = self.data_converter.convert_timezone(df)
        
        # Валидируем данные
        df = self.data_validator.validate_data(df, instrument_symbol, timeframe_code)
        
        return df
    
    def _has_dma_in_db(self, instrument_symbol: str, timeframe_code: str) -> bool:
        """
        Проверяет, есть ли хотя бы одна запись DMA в БД.
        
        Возвращает:
            bool: True если DMA есть в БД
        """
        try:
            # Проверяем наличие хотя бы одной комбинации DMA
            dma_series = self.dma_service.get_dma_from_db(
                instrument_symbol, timeframe_code, 3, 3
            )
            return dma_series is not None and not dma_series.empty
        except Exception:
            return False
    
    def prepare_chart_data(self, instrument_symbol: str, timeframe_code: str):
        """
        Получает и обрабатывает данные для графика.
        
        Возвращает:
            pd.DataFrame или None
        """
        instrument, timeframe = self.get_instrument_and_timeframe(instrument_symbol, timeframe_code)
        if not instrument or not timeframe:
            return None
        
        price_data = self.data_loader.load_price_data(instrument.id, timeframe.id)
        if price_data is None:
            return None
        
        # Сначала обрабатываем данные БЕЗ ограничения для расчета DMA
        df_full = self.data_converter.process_price_data(price_data, instrument_symbol, timeframe_code)
        if df_full is None:
            return None
        
        # Подготавливаем колонки
        df_full = self.data_validator.prepare_columns(df_full)
        if df_full is None:
            return None
        
        # Конвертируем timezone
        df_full = self.data_converter.convert_timezone(df_full)
        
        # Валидируем данные
        df_full = self.data_validator.validate_data(df_full, instrument_symbol, timeframe_code)
        if df_full is None:
            return None
        
        # Всегда пересчитываем DMA на полном наборе данных
        # Это гарантирует, что DMA актуальны и доходят до конца графика
        try:
            logger.debug(f"Расчет/обновление DMA для {instrument_symbol} на {timeframe_code} (данных: {len(df_full)})")
            self.dma_service.calculate_all_dma_from_dataframe(
                df_full, instrument_symbol, timeframe_code
            )
        except Exception as e:
            logger.error(f"Ошибка при расчете DMA для {instrument_symbol} {timeframe_code}: {e}")
        
        # Теперь ограничиваем данные только для отображения на графике
        df = self.data_validator.limit_candles(df_full, timeframe_code)
        
        return df
