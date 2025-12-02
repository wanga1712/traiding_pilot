"""
Расчёт расширенных индикаторов (ATR, Bollinger, RSI, EMA и т.д.) для всех монет и таймфреймов.
Оптимизировано для параллельной обработки и работы с большими объемами данных.
"""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Tuple

import pandas as pd
from loguru import logger
from tqdm import tqdm

from gui.data_fetcher import DataFetcher
from crypto_trading_bot.database.data_import import DataImport
from crypto_trading_bot.analytics.indicators_ext.service import ExtendedIndicatorsService

# Размер чанка для обработки больших DataFrame (в записях)
CHUNK_SIZE = 2_000_000  # 2 млн записей на чанк


def _get_timeframe_name(timeframe) -> str:
    """
    Получает название таймфрейма из объекта timeframe.
    
    Args:
        timeframe: Объект таймфрейма (может иметь атрибуты interval_name, name, code)
        
    Returns:
        Название таймфрейма (например, '1h', '1d')
    """
    if hasattr(timeframe, 'interval_name'):
        return timeframe.interval_name
    elif hasattr(timeframe, 'name'):
        return timeframe.name
    elif hasattr(timeframe, 'code'):
        return timeframe.code
    elif isinstance(timeframe, (list, tuple)) and len(timeframe) >= 2:
        # Если это кортеж/список, берем второй элемент (название)
        return str(timeframe[1])
    else:
        return str(timeframe)


def _process_single_task(args: Tuple[int, str, int, str]) -> Tuple[str, str, int, bool]:
    """
    Обрабатывает одну задачу (инструмент + таймфрейм) в отдельном процессе.
    
    Args:
        args: Кортеж (instrument_id, symbol, timeframe_id, tf_name)
        
    Returns:
        Кортеж (symbol, tf_name, saved_count, success)
    """
    instrument_id, symbol, timeframe_id, tf_name = args
    
    try:
        # Каждый процесс создает свои подключения к БД
        importer = DataImport()
        service = ExtendedIndicatorsService()
        
        # Получаем данные
        rows = importer.get_price_data(instrument_id, timeframe_id)
        if not rows:
            return (symbol, tf_name, 0, True)
        
        # Строим DataFrame
        df = service._build_df(rows)
        
        # Если данных очень много, обрабатываем по чанкам
        total_rows = len(df)
        if total_rows > CHUNK_SIZE:
            logger.debug(
                "Большой объем данных для %s @ %s: %d записей, разбиваю на чанки",
                symbol,
                tf_name,
                total_rows,
            )
            saved_total = 0
            num_chunks = (total_rows + CHUNK_SIZE - 1) // CHUNK_SIZE
            
            for chunk_idx in range(num_chunks):
                start_idx = chunk_idx * CHUNK_SIZE
                end_idx = min((chunk_idx + 1) * CHUNK_SIZE, total_rows)
                
                # Для первого чанка берем больше данных для правильного расчета индикаторов
                # (индикаторы типа EMA, RSI требуют исторических данных)
                if chunk_idx == 0:
                    chunk_df = df.iloc[:end_idx].copy()
                else:
                    # Для последующих чанков берем перекрытие для корректного расчета
                    overlap = min(500, start_idx)  # Перекрытие 500 записей
                    chunk_start = max(0, start_idx - overlap)
                    chunk_df = df.iloc[chunk_start:end_idx].copy()
                
                # Рассчитываем индикаторы для чанка
                saved = service.calculate_from_dataframe(chunk_df, symbol, tf_name)
                saved_total += saved
                
                logger.debug(
                    "Обработан чанк %d/%d для %s @ %s: %d записей, сохранено %d",
                    chunk_idx + 1,
                    num_chunks,
                    symbol,
                    tf_name,
                    len(chunk_df),
                    saved,
                )
            
            return (symbol, tf_name, saved_total, True)
        else:
            # Обычная обработка для небольших объемов
            saved = service.calculate_from_dataframe(df, symbol, tf_name)
            return (symbol, tf_name, saved, True)
            
    except Exception as e:
        logger.error(
            "Ошибка при обработке %s @ %s: %s",
            symbol,
            tf_name,
            e,
        )
        return (symbol, tf_name, 0, False)


def calculate_extended_indicators(max_workers: int | None = None) -> None:
    """
    Рассчитывает расширенные индикаторы для всех инструментов и таймфреймов.
    Использует параллельную обработку для ускорения.
    
    Args:
        max_workers: Максимальное количество параллельных процессов.
                    Если None, используется количество CPU ядер.
    """
    logger.info("Старт расчёта расширенных индикаторов")
    
    # Определяем количество процессов
    if max_workers is None:
        max_workers = os.cpu_count() or 4
        # Ограничиваем максимум 8 процессами для избежания перегрузки БД
        max_workers = min(max_workers, 8)
    
    logger.info("Используется %d параллельных процессов", max_workers)
    
    fetcher = DataFetcher()
    instruments = fetcher.get_instruments()
    timeframes = fetcher.get_timeframes()
    
    # Формируем список задач
    tasks = []
    for instrument in instruments:
        symbol = instrument.symbol
        for timeframe in timeframes:
            tf_name = _get_timeframe_name(timeframe)
            timeframe_id = getattr(timeframe, "id", None)
            if timeframe_id is None and isinstance(timeframe, (list, tuple)):
                timeframe_id = timeframe[0]
            if timeframe_id is None:
                logger.warning(f"Пропуск {symbol} @ {tf_name}: нет timeframe_id")
                continue
            tasks.append((instrument.id, symbol, timeframe_id, tf_name))
    
    total = len(tasks)
    logger.info("Всего задач для обработки: %d", total)
    
    # Обрабатываем задачи параллельно
    completed = 0
    failed = 0
    
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        # Отправляем все задачи
        future_to_task = {
            executor.submit(_process_single_task, task): task
            for task in tasks
        }
        
        # Отслеживаем прогресс
        with tqdm(total=total, desc="Extended indicators") as progress:
            for future in as_completed(future_to_task):
                try:
                    symbol, tf_name, saved_count, success = future.result()
                    if success:
                        completed += 1
                        if saved_count > 0:
                            logger.debug(
                                "Завершено: %s @ %s (%d записей)",
                                symbol,
                                tf_name,
                                saved_count,
                            )
                    else:
                        failed += 1
                except Exception as e:
                    failed += 1
                    task = future_to_task[future]
                    logger.error(
                        "Критическая ошибка при обработке задачи %s: %s",
                        task,
                        e,
                    )
                finally:
                    progress.update(1)
    
    logger.success(
        "Расширенные индикаторы рассчитаны и сохранены. "
        "Успешно: %d, Ошибок: %d",
        completed,
        failed,
    )


if __name__ == "__main__":
    calculate_extended_indicators()

