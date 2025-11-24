"""
Скрипт для массового расчета DMA для всех инструментов и таймфреймов.

Используется для подготовки данных для обучения модели и бэктестинга.
"""

from loguru import logger
from tqdm import tqdm

from gui.data_fetcher import DataFetcher
from crypto_trading_bot.database.data_import import DataImport
from crypto_trading_bot.analytics.dinapoli_dma import DinapoliDMAService
from gui.chart_data_converter import ChartDataConverter


def calculate_all_dma():
    """
    Рассчитывает DMA для всех инструментов и таймфреймов.
    """
    logger.info("Начало массового расчета DMA для всех инструментов и таймфреймов")
    
    data_fetcher = DataFetcher()
    data_import = DataImport()
    dma_service = DinapoliDMAService()
    data_converter = ChartDataConverter()
    
    # Получаем все инструменты
    instruments = data_fetcher.get_instruments()
    if not instruments:
        logger.error("Не найдено инструментов в БД")
        return
    
    logger.info(f"Найдено {len(instruments)} инструментов")
    
    # Получаем все таймфреймы
    timeframes = data_fetcher.get_timeframes()
    if not timeframes:
        logger.error("Не найдено таймфреймов в БД")
        return
    
    logger.info(f"Найдено {len(timeframes)} таймфреймов")
    
    # Определяем название колонки таймфрейма
    timeframe_name_attr = None
    for tf in timeframes:
        if hasattr(tf, 'interval_name'):
            timeframe_name_attr = 'interval_name'
            break
        elif hasattr(tf, 'name'):
            timeframe_name_attr = 'name'
            break
        elif hasattr(tf, 'code'):
            timeframe_name_attr = 'code'
            break
    
    if not timeframe_name_attr:
        logger.error("Не удалось определить атрибут названия таймфрейма")
        return
    
    total_combinations = len(instruments) * len(timeframes)
    processed = 0
    errors = 0
    
    logger.info(f"Всего комбинаций для обработки: {total_combinations}")
    
    # Создаем прогресс-бар
    with tqdm(total=total_combinations, desc="Расчет DMA", unit="комбинация") as pbar:
        for instrument in instruments:
            instrument_symbol = instrument.symbol
            
            for timeframe in timeframes:
                timeframe_code = getattr(timeframe, timeframe_name_attr)
                
                try:
                    # Получаем данные из БД
                    price_data = data_import.get_price_data(instrument.id, timeframe.id)
                    
                    if not price_data:
                        logger.debug(f"Нет данных для {instrument_symbol} на {timeframe_code}")
                        processed += 1
                        pbar.update(1)
                        continue
                    
                    # Конвертируем в DataFrame
                    df = data_converter.process_price_data(
                        price_data, instrument_symbol, timeframe_code
                    )
                    
                    if df is None or df.empty:
                        logger.debug(f"Не удалось обработать данные для {instrument_symbol} на {timeframe_code}")
                        processed += 1
                        pbar.update(1)
                        continue
                    
                    # Рассчитываем все комбинации DMA
                    success = dma_service.calculate_all_dma_from_dataframe(
                        df, instrument_symbol, timeframe_code
                    )
                    
                    if success:
                        logger.debug(
                            f"DMA рассчитаны для {instrument_symbol} на {timeframe_code} "
                            f"({len(df)} свечей)"
                        )
                    else:
                        logger.warning(
                            f"Не удалось рассчитать все DMA для {instrument_symbol} на {timeframe_code}"
                        )
                        errors += 1
                    
                    processed += 1
                    pbar.update(1)
                    
                except Exception as e:
                    logger.error(
                        f"Ошибка при расчете DMA для {instrument_symbol} на {timeframe_code}: {e}"
                    )
                    errors += 1
                    processed += 1
                    pbar.update(1)
                    continue
    
    logger.info(
        f"Массовый расчет DMA завершен: обработано {processed}/{total_combinations}, "
        f"ошибок: {errors}"
    )


if __name__ == '__main__':
    calculate_all_dma()

