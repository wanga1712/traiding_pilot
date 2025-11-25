"""
Модуль для расчета смещенных скользящих средних (DMA) по методу Ди Наполи.

DMA (Displaced Moving Average) - это скользящая средняя, смещенная вперед во времени.
Для удержания торговой позиции и измерения тренда используются комбинации:
- 3×3 (период 3, смещение 3)
- 7×5 (период 7, смещение 5)
- 25×5 (период 25, смещение 5)
"""

import pandas as pd
import numpy as np
from loguru import logger
from typing import List, Tuple, Optional
from datetime import datetime

from crypto_trading_bot.database.db_connection import DatabaseManager
from crypto_trading_bot.database.data_import import DataImport
from crypto_trading_bot.analytics.db_schema import AnalyticsSchemaManager


class DinapoliDMAService:
    """
    Сервис для расчета и сохранения DMA по методу Ди Наполи.
    """
    
    # Стандартные комбинации DMA по Ди Наполи
    DMA_COMBINATIONS = [
        (3, 3),   # 3×3
        (7, 5),   # 7×5
        (25, 5)   # 25×5
    ]
    
    def __init__(self, db_manager: DatabaseManager = None):
        """
        Инициализация сервиса DMA.
        
        Параметры:
            db_manager: Объект DatabaseManager. Если None, создается новый.
        """
        self.db_manager = db_manager or DatabaseManager()
        self.schema = AnalyticsSchemaManager(self.db_manager)
        self.data_import = DataImport()
        
        # Убеждаемся, что схема БД создана
        self.schema.ensure_schema()
    
    def calculate_dma(self, close_prices: pd.Series, period: int, displacement: int) -> pd.Series:
        """
        Рассчитывает простую скользящую среднюю (SMA) с периодом period.
        
        Смещение происходит при сохранении в БД (timestamp смещается вперед).
        Этот метод используется только для внутренних расчетов.
        
        Параметры:
            close_prices: Series с ценами закрытия.
            period: Период скользящей средней (N).
            displacement: Смещение вперед (M) - не используется здесь, только для совместимости.
        
        Возвращает:
            Series с значениями SMA. NaN значения остаются там, где данных недостаточно.
        """
        # Проверяем, достаточно ли данных для расчета
        min_required = period
        if len(close_prices) < min_required:
            logger.warning(
                f"Недостаточно данных для SMA({period}): "
                f"требуется минимум {min_required}, получено {len(close_prices)}"
            )
            return pd.Series(dtype=float, index=close_prices.index)
        
        # Вычисляем простую скользящую среднюю с окном period
        # SMA(t) = среднее от P_t, P_{t-1}, ..., P_{t-period+1}
        sma = close_prices.rolling(window=period).mean()
        
        return sma
    
    def fetch_price_data(self, symbol: str, timeframe_code: str) -> Optional[pd.DataFrame]:
        """
        Получает данные цен из БД для указанного инструмента и таймфрейма.
        
        Параметры:
            symbol: Символ инструмента.
            timeframe_code: Код таймфрейма.
        
        Возвращает:
            DataFrame с колонками: timestamp, close, или None если данных нет.
        """
        try:
            # Получаем ID инструмента и таймфрейма
            instrument_id = self.schema.ensure_instrument(symbol)
            timeframe_id = self.schema.ensure_timeframe(timeframe_code)
            
            # Получаем данные цен
            price_data = self.data_import.get_price_data(instrument_id, timeframe_id)
            
            if not price_data:
                logger.warning(f"Нет данных для {symbol} на {timeframe_code}")
                return None
            
            # Преобразуем в DataFrame
            df = pd.DataFrame(
                price_data,
                columns=['candle_time', 'open', 'close', 'high', 'low', 'volume']
            )
            
            # Преобразуем timestamp в datetime
            df['candle_time'] = pd.to_datetime(df['candle_time'])
            df.set_index('candle_time', inplace=True)
            
            # Сортируем по времени
            df.sort_index(inplace=True)
            
            return df
            
        except Exception as e:
            logger.error(f"Ошибка при получении данных для {symbol} на {timeframe_code}: {e}")
            return None
    
    def calculate_dma_from_dataframe(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe_code: str,
        period: int,
        displacement: int
    ) -> bool:
        """
        Рассчитывает DMA из DataFrame и сохраняет результаты в БД.
        
        Параметры:
            df: DataFrame с колонкой 'Close' или 'close' и DatetimeIndex.
            symbol: Символ инструмента.
            timeframe_code: Код таймфрейма.
            period: Период скользящей средней.
            displacement: Смещение.
        
        Возвращает:
            bool: True если успешно, False в противном случае.
        """
        try:
            if df is None or df.empty:
                return False
            
            # Определяем колонку с ценой закрытия
            close_col = 'Close' if 'Close' in df.columns else 'close'
            if close_col not in df.columns:
                logger.error(f"Колонка {close_col} не найдена в DataFrame для {symbol}")
                return False
            
            # Рассчитываем SMA (без смещения)
            sma = df[close_col].rolling(window=period).mean()
            
            # Удаляем NaN значения (в начале из-за rolling window)
            valid_sma = sma.dropna()
            
            if valid_sma.empty:
                logger.debug(f"Нет валидных данных SMA для {symbol} на {timeframe_code}")
                return False
            
            # Определяем период таймфрейма (разница между соседними timestamp'ами)
            if len(df.index) < 2:
                logger.warning(f"Недостаточно данных для определения периода таймфрейма для {symbol}")
                return False
            
            timeframe_period = df.index[1] - df.index[0]
            
            # Получаем ID
            instrument_id = self.schema.ensure_instrument(symbol)
            timeframe_id = self.schema.ensure_timeframe(timeframe_code)
            
            # Сохраняем каждое значение в БД со смещенным timestamp
            metric_type = f"DMA_{period}x{displacement}"
            saved_count = 0
            
            for original_timestamp, value in valid_sma.items():
                try:
                    # Смещаем timestamp вперед на displacement периодов
                    shifted_timestamp = original_timestamp + (timeframe_period * displacement)
                    
                    # Убираем timezone из timestamp для сохранения в БД
                    if hasattr(shifted_timestamp, 'tz') and shifted_timestamp.tz is not None:
                        timestamp_naive = shifted_timestamp.tz_localize(None)
                    else:
                        timestamp_naive = shifted_timestamp
                    
                    # Используем UPSERT для избежания дубликатов
                    query = """
                    INSERT INTO analytics_metrics 
                        (instrument_id, timeframe_id, metric_type, metric_window, metric_displacement, 
                         metric_timestamp, value)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (
                        instrument_id, timeframe_id, metric_type,
                        metric_window, metric_displacement, metric_timestamp
                    )
                    DO UPDATE SET 
                        value = EXCLUDED.value, created_at = NOW();
                    """
                    
                    self.db_manager.execute_query(
                        query,
                        (
                            instrument_id,
                            timeframe_id,
                            metric_type,
                            period,
                            displacement,
                            timestamp_naive,
                            float(value),
                        )
                    )
                    saved_count += 1
                    
                except Exception as e:
                    logger.error(f"Ошибка при сохранении DMA значения для {symbol}: {e}")
                    continue
            
            logger.debug(
                f"DMA {period}x{displacement} для {symbol} на {timeframe_code}: "
                f"сохранено {saved_count} значений"
            )
            return True
            
        except Exception as e:
            logger.error(f"Ошибка при расчете DMA для {symbol} на {timeframe_code}: {e}")
            return False
    
    def calculate_and_save_dma(
        self,
        symbol: str,
        timeframe_code: str,
        period: int,
        displacement: int
    ) -> bool:
        """
        Рассчитывает DMA и сохраняет результаты в БД.
        
        Параметры:
            symbol: Символ инструмента.
            timeframe_code: Код таймфрейма.
            period: Период скользящей средней.
            displacement: Смещение.
        
        Возвращает:
            bool: True если успешно, False в противном случае.
        """
        try:
            # Получаем данные
            df = self.fetch_price_data(symbol, timeframe_code)
            if df is None or df.empty:
                return False
            
            # Используем метод с DataFrame
            return self.calculate_dma_from_dataframe(df, symbol, timeframe_code, period, displacement)
            
        except Exception as e:
            logger.error(f"Ошибка при расчете DMA для {symbol} на {timeframe_code}: {e}")
            return False
    
    def get_dma_from_db(
        self,
        symbol: str,
        timeframe_code: str,
        period: int,
        displacement: int
    ) -> Optional[pd.Series]:
        """
        Получает рассчитанные значения DMA из БД.
        
        Параметры:
            symbol: Символ инструмента.
            timeframe_code: Код таймфрейма.
            period: Период скользящей средней.
            displacement: Смещение.
        
        Возвращает:
            Series с индексом timestamp и значениями DMA, или None если данных нет.
        """
        try:
            instrument_id = self.schema.ensure_instrument(symbol)
            timeframe_id = self.schema.ensure_timeframe(timeframe_code)
            metric_type = f"DMA_{period}x{displacement}"
            
            query = """
            SELECT metric_timestamp, value
            FROM analytics_metrics
            WHERE instrument_id = %s 
                AND timeframe_id = %s 
                AND metric_type = %s
                AND metric_window = %s
                AND metric_displacement = %s
            ORDER BY metric_timestamp;
            """
            
            results = self.db_manager.fetch_all(
                query,
                (instrument_id, timeframe_id, metric_type, period, displacement)
            )
            
            if not results:
                return None
            
            # Преобразуем в Series
            timestamps = [row[0] for row in results]
            values = [float(row[1]) for row in results]
            
            # Создаем DatetimeIndex и убираем timezone
            index = pd.to_datetime(timestamps)
            if index.tz is not None:
                index = index.tz_localize(None)
            
            series = pd.Series(values, index=index)
            series.index.name = 'timestamp'
            
            return series
            
        except Exception as e:
            logger.error(f"Ошибка при получении DMA из БД: {e}")
            return None
    
    def calculate_all_dma_from_dataframe(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe_code: str
    ) -> bool:
        """
        Рассчитывает все стандартные комбинации DMA из DataFrame.
        
        Параметры:
            df: DataFrame с колонкой 'Close' или 'close' и DatetimeIndex.
            symbol: Символ инструмента.
            timeframe_code: Код таймфрейма.
        
        Возвращает:
            bool: True если все расчеты успешны.
        """
        if df is None or df.empty:
            return False
        
        success_count = 0
        for period, displacement in self.DMA_COMBINATIONS:
            if self.calculate_dma_from_dataframe(df, symbol, timeframe_code, period, displacement):
                success_count += 1
        
        logger.debug(
            f"DMA для {symbol} на {timeframe_code}: "
            f"рассчитано {success_count}/{len(self.DMA_COMBINATIONS)} комбинаций"
        )
        
        return success_count == len(self.DMA_COMBINATIONS)
    
    def calculate_all_dma_combinations(self, symbol: str, timeframe_code: str) -> bool:
        """
        Рассчитывает все стандартные комбинации DMA для инструмента и таймфрейма.
        
        Параметры:
            symbol: Символ инструмента.
            timeframe_code: Код таймфрейма.
        
        Возвращает:
            bool: True если все расчеты успешны.
        """
        try:
            # Получаем данные
            df = self.fetch_price_data(symbol, timeframe_code)
            if df is None or df.empty:
                return False
            
            # Используем метод с DataFrame
            return self.calculate_all_dma_from_dataframe(df, symbol, timeframe_code)
            
        except Exception as e:
            logger.error(f"Ошибка при расчете DMA для {symbol} на {timeframe_code}: {e}")
            return False
    
    def run(self, symbols: List[str], timeframes: List[str]):
        """
        Запускает расчет DMA для списка инструментов и таймфреймов.
        
        Параметры:
            symbols: Список символов инструментов.
            timeframes: Список кодов таймфреймов.
        """
        total = len(symbols) * len(timeframes)
        processed = 0
        
        logger.info(f"Начинаем расчет DMA для {len(symbols)} инструментов и {len(timeframes)} таймфреймов")
        
        for symbol in symbols:
            for timeframe in timeframes:
                try:
                    self.calculate_all_dma_combinations(symbol, timeframe)
                    processed += 1
                    logger.info(f"Прогресс: {processed}/{total}")
                except Exception as e:
                    logger.error(f"Ошибка при обработке {symbol} на {timeframe}: {e}")
        
        logger.info(f"Расчет DMA завершен: обработано {processed}/{total}")


# Пример использования
if __name__ == '__main__':
    service = DinapoliDMAService()
    
    # Пример: расчет для одного инструмента и таймфрейма
    service.calculate_all_dma_combinations('BTCUSDT', '1d')
    
    # Пример: получение данных из БД
    dma_3x3 = service.get_dma_from_db('BTCUSDT', '1d', 3, 3)
    if dma_3x3 is not None:
        print(f"DMA 3x3 последние 5 значений:\n{dma_3x3.tail()}")

