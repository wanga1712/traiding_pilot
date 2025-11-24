"""
Модуль для фонового обновления данных о свечах.

Обеспечивает:
- Проверку последних записей в БД
- Загрузку недостающих свечей
- Периодическое обновление данных в фоне
"""

from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from loguru import logger
import pandas as pd
from threading import Thread
import time

from crypto_trading_bot.database.data_import import DataImport
from crypto_trading_bot.database.data_export import DataExporter
from crypto_trading_bot.trading.crypto_data_provider import CryptoDataProvider
from crypto_trading_bot.trading.binance_symbol_checker import BinanceSymbolChecker
from gui.data_fetcher import DataFetcher


class DataUpdater:
    """
    Класс для фонового обновления данных о свечах.
    """
    
    def __init__(self):
        """
        Инициализация обновлятеля данных.
        """
        self.data_fetcher = DataFetcher()
        self.data_import = DataImport()
        self.data_export = DataExporter()
        self.data_provider = CryptoDataProvider()
        self.symbol_checker = BinanceSymbolChecker()
        
        # Флаг работы фонового потока
        self.is_running = False
        self.update_thread = None
        
        # Кэш доступных символов (обновляется при первом использовании)
        self._available_symbols_cache = None
        self._symbols_cache_time = None
        
        # Маппинг таймфреймов из БД в формат провайдера
        self.TIMEFRAME_MAPPING = {
            '1m': '1min', '3m': '3min', '5m': '5min', '15m': '15min', '30m': '30min',
            '1h': '1hour', '2h': '1hour', '4h': '4hour', '6h': '4hour', '12h': '4hour',
            '1d': '1day', '1w': '1week', '1mo': '1day'
        }
    
    def get_last_candle_time(self, instrument_id: int, timeframe_id: int) -> Optional[datetime]:
        """
        Получает время последней свечи для инструмента и таймфрейма.
        
        Параметры:
            instrument_id: ID инструмента.
            timeframe_id: ID таймфрейма.
        
        Возвращает:
            datetime или None: Время последней свечи или None если данных нет.
        """
        try:
            query = """
                SELECT MAX(candle_time) 
                FROM candles 
                WHERE instrument_id = %s AND timeframe_id = %s;
            """
            result = self.data_import.db_manager.fetch_one(query, (instrument_id, timeframe_id))
            
            if result and result[0]:
                return result[0]
            return None
            
        except Exception as e:
            logger.error(f"Ошибка при получении последней свечи для instrument_id={instrument_id}, timeframe_id={timeframe_id}: {e}")
            return None
    
    def calculate_missing_candles(self, last_candle_time: datetime, timeframe_code: str, 
                                  current_time: datetime = None) -> Tuple[datetime, datetime]:
        """
        Вычисляет период для загрузки недостающих свечей.
        
        Параметры:
            last_candle_time: Время последней свечи в БД.
            timeframe_code: Код таймфрейма (например, '1m', '1h', '1d').
            current_time: Текущее время (по умолчанию datetime.now()).
        
        Возвращает:
            tuple: (start_time, end_time) для загрузки данных.
        """
        if current_time is None:
            current_time = datetime.now()
        
        # Определяем интервал таймфрейма в минутах
        timeframe_minutes = {
            '1m': 1, '3m': 3, '5m': 5, '15m': 15, '30m': 30,
            '1h': 60, '2h': 120, '4h': 240, '6h': 360, '12h': 720,
            '1d': 1440, '1w': 10080, '1mo': 43200
        }
        
        minutes = timeframe_minutes.get(timeframe_code, 60)
        
        # Вычисляем следующую свечу после последней
        if last_candle_time:
            # Округляем до начала следующей свечи
            next_candle_time = last_candle_time + timedelta(minutes=minutes)
        else:
            # Если данных нет, загружаем последние 100 свечей
            next_candle_time = current_time - timedelta(minutes=minutes * 100)
        
        # Загружаем до текущего времени
        return next_candle_time, current_time
    
    def _is_symbol_available(self, symbol: str) -> bool:
        """
        Проверяет, доступен ли символ на Binance.
        Использует кэш для оптимизации.
        
        Параметры:
            symbol: Символ для проверки.
        
        Возвращает:
            bool: True если символ доступен.
        """
        # Обновляем кэш раз в час
        if (self._available_symbols_cache is None or 
            self._symbols_cache_time is None or
            (datetime.now() - self._symbols_cache_time).total_seconds() > 3600):
            self._available_symbols_cache = self.symbol_checker.get_available_symbols()
            self._symbols_cache_time = datetime.now()
            logger.debug(f"Обновлен кэш доступных символов: {len(self._available_symbols_cache)} символов")
        
        return symbol in self._available_symbols_cache
    
    def load_missing_candles(self, instrument_symbol: str, timeframe_code: str) -> bool:
        """
        Загружает недостающие свечи для инструмента и таймфрейма.
        
        Параметры:
            instrument_symbol: Символ инструмента.
            timeframe_code: Код таймфрейма из БД.
        
        Возвращает:
            bool: True если данные успешно загружены.
        """
        try:
            # Проверяем доступность символа на Binance
            if not self._is_symbol_available(instrument_symbol):
                logger.debug(f"Символ {instrument_symbol} недоступен на Binance, пропускаем")
                return False
            
            # Получаем ID инструмента и таймфрейма
            instruments = self.data_fetcher.get_instruments()
            instrument = next((inst for inst in instruments if inst.symbol == instrument_symbol), None)
            
            if not instrument:
                logger.warning(f"Инструмент {instrument_symbol} не найден")
                return False
            
            timeframes = self.data_fetcher.get_timeframes()
            timeframe = None
            for tf in timeframes:
                tf_name = getattr(tf, 'interval_name', None) or getattr(tf, 'name', None)
                if tf_name == timeframe_code:
                    timeframe = tf
                    break
            
            if not timeframe:
                logger.warning(f"Таймфрейм {timeframe_code} не найден")
                return False
            
            # Получаем время последней свечи
            last_candle_time = self.get_last_candle_time(instrument.id, timeframe.id)
            
            # Вычисляем период для загрузки
            start_time, end_time = self.calculate_missing_candles(
                last_candle_time, timeframe_code
            )
            
            # Если нет новых данных для загрузки
            if last_candle_time and start_time >= end_time:
                logger.debug(f"Нет новых данных для {instrument_symbol} {timeframe_code}")
                return True
            
            # Преобразуем таймфрейм для провайдера
            provider_timeframe = self.TIMEFRAME_MAPPING.get(timeframe_code, '1hour')
            
            logger.info(f"Загрузка недостающих свечей для {instrument_symbol} {timeframe_code} с {start_time} по {end_time}")
            
            # Загружаем данные через провайдера за конкретный период
            # Используем get_historical_data с указанием start_date и end_date
            if last_candle_time:
                # Ограничиваем максимальный период (для безопасности)
                # Для мелких таймфреймов ограничиваем период
                if timeframe_code in ['1m', '3m', '5m']:
                    max_days = 7  # Максимум 7 дней для минутных
                elif timeframe_code in ['15m', '30m']:
                    max_days = 30  # Максимум 30 дней для 15-30 минутных
                elif timeframe_code in ['1h', '2h']:
                    max_days = 90  # Максимум 90 дней для часовых
                else:
                    max_days = 365  # Максимум 1 год для остальных
                
                # Ограничиваем период загрузки
                days_diff = (end_time - start_time).total_seconds() / (24 * 60 * 60)
                if days_diff > max_days:
                    # Если период больше максимума, загружаем только последние max_days
                    start_time = end_time - timedelta(days=max_days)
                    logger.warning(f"Период загрузки ограничен до {max_days} дней для {instrument_symbol} {timeframe_code}")
                
                logger.info(f"Загрузка данных за период {start_time} - {end_time} для {instrument_symbol} {timeframe_code}")
                df = self.data_provider.get_historical_data(
                    instrument_symbol, 
                    provider_timeframe,
                    start_date=start_time,
                    end_date=end_time
                )
            else:
                # Если данных нет, загружаем последние 100 свечей для быстрого старта
                # Потом при следующем обновлении догрузим остальное
                logger.info(f"Нет данных для {instrument_symbol} {timeframe_code}, загружаем последние 100 свечей для старта")
                df = self.data_provider.get_recent_data(instrument_symbol, provider_timeframe, limit=100)
            
            if df is None or df.empty:
                logger.warning(f"Не удалось загрузить данные для {instrument_symbol} {timeframe_code}")
                return False
            
            # Фильтруем данные по времени (только новые свечи)
            if last_candle_time:
                # Приводим last_candle_time к timezone-aware формату, если df.index timezone-aware
                if df.index.tz is not None:
                    # Если last_candle_time timezone-naive, добавляем UTC
                    if last_candle_time.tzinfo is None:
                        from pytz import UTC
                        last_candle_time = UTC.localize(last_candle_time)
                    # Если timezone разные, конвертируем
                    elif last_candle_time.tzinfo != df.index.tz:
                        last_candle_time = last_candle_time.astimezone(df.index.tz)
                elif last_candle_time.tzinfo is not None:
                    # Если df.index timezone-naive, а last_candle_time timezone-aware, убираем timezone
                    last_candle_time = last_candle_time.replace(tzinfo=None)
                
                df = df[df.index > last_candle_time]
            
            if df.empty:
                logger.debug(f"Нет новых свечей для {instrument_symbol} {timeframe_code}")
                return True
            
            # Преобразуем в формат для БД
            df_for_db = self._convert_dataframe_for_db(df)
            
            # Сохраняем в БД
            success = self.data_export.insert_price_data(instrument_symbol, timeframe_code, df_for_db)
            
            if success:
                logger.info(f"Загружено {len(df)} новых свечей для {instrument_symbol} {timeframe_code}")
                return True
            else:
                logger.error(f"Не удалось сохранить данные для {instrument_symbol} {timeframe_code}")
                return False
                
        except Exception as e:
            logger.error(f"Ошибка при загрузке недостающих свечей для {instrument_symbol} {timeframe_code}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def _convert_dataframe_for_db(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Преобразует DataFrame в формат для DataExporter.
        
        Параметры:
            df: DataFrame с колонками 'open', 'high', 'low', 'close', 'volume'.
        
        Возвращает:
            DataFrame с колонками 'Open', 'High', 'Low', 'Close', 'Volume'.
        """
        if df is None or df.empty:
            return df
        
        df_copy = df.copy()
        
        # Переименовываем колонки
        column_mapping = {
            'open': 'Open',
            'high': 'High',
            'low': 'Low',
            'close': 'Close',
            'volume': 'Volume'
        }
        
        df_copy = df_copy.rename(columns=column_mapping)
        
        return df_copy
    
    def get_timeframe_update_interval(self, timeframe_code: str) -> int:
        """
        Определяет интервал обновления для таймфрейма в секундах.
        
        Параметры:
            timeframe_code: Код таймфрейма (например, '1m', '1h', '1d').
        
        Возвращает:
            int: Интервал обновления в секундах.
        """
        # Интервалы обновления для каждого таймфрейма
        update_intervals = {
            # Минутные таймфреймы - обновляем каждую минуту
            '1m': 60,   # 1 минута
            '3m': 60,   # 1 минута (чтобы не пропустить новую свечу)
            '5m': 60,   # 1 минута
            
            # 15-30 минутные - обновляем каждые 15 минут
            '15m': 15 * 60,  # 15 минут
            '30m': 15 * 60,  # 15 минут
            
            # Часовые - обновляем каждый час
            '1h': 60 * 60,   # 1 час
            '2h': 60 * 60,   # 1 час
            
            # 4-12 часовые - обновляем каждые 4 часа
            '4h': 4 * 60 * 60,   # 4 часа
            '6h': 4 * 60 * 60,   # 4 часа
            '12h': 4 * 60 * 60,  # 4 часа
            
            # Дневные - обновляем раз в день
            '1d': 24 * 60 * 60,  # 24 часа
            
            # Недельные - обновляем раз в день (проверяем, может быть новая неделя)
            '1w': 24 * 60 * 60,  # 24 часа
            
            # Месячные - обновляем раз в день (проверяем, может быть новый месяц)
            '1mo': 24 * 60 * 60,  # 24 часа
        }
        
        return update_intervals.get(timeframe_code, 60)  # По умолчанию 1 минута
    
    def should_update_timeframe(self, timeframe_code: str, last_update_time: dict) -> bool:
        """
        Проверяет, нужно ли обновлять таймфрейм сейчас.
        
        Параметры:
            timeframe_code: Код таймфрейма.
            last_update_time: Словарь с временем последнего обновления для каждого таймфрейма.
        
        Возвращает:
            bool: True если нужно обновить.
        """
        if timeframe_code not in last_update_time:
            return True  # Первое обновление
        
        interval = self.get_timeframe_update_interval(timeframe_code)
        time_since_update = (datetime.now() - last_update_time[timeframe_code]).total_seconds()
        
        return time_since_update >= interval
    
    def update_all_instruments(self, force_all: bool = False) -> int:
        """
        Обновляет данные для всех инструментов и таймфреймов.
        
        Параметры:
            force_all: Если True, обновляет все таймфреймы независимо от интервала.
        
        Возвращает:
            int: Количество успешно обновленных комбинаций.
        """
        try:
            instruments = self.data_fetcher.get_instruments()
            timeframes = self.data_fetcher.get_timeframes()
            
            success_count = 0
            skipped_count = 0
            
            # Словарь для отслеживания времени последнего обновления каждого таймфрейма
            if not hasattr(self, 'last_update_times'):
                self.last_update_times = {}
            
            logger.info(f"Начало обновления данных для {len(instruments)} инструментов и {len(timeframes)} таймфреймов")
            
            for instrument in instruments:
                for timeframe in timeframes:
                    timeframe_code = getattr(timeframe, 'interval_name', None) or getattr(timeframe, 'name', None)
                    
                    if not timeframe_code:
                        continue
                    
                    # Пропускаем таймфреймы, для которых нет маппинга
                    if timeframe_code not in self.TIMEFRAME_MAPPING:
                        continue
                    
                    # Проверяем, нужно ли обновлять этот таймфрейм
                    if not force_all and not self.should_update_timeframe(timeframe_code, self.last_update_times):
                        skipped_count += 1
                        continue
                    
                    if self.load_missing_candles(instrument.symbol, timeframe_code):
                        success_count += 1
                        # Обновляем время последнего обновления
                        self.last_update_times[timeframe_code] = datetime.now()
                    
                    # Небольшая задержка для соблюдения rate limit
                    time.sleep(0.1)
            
            logger.info(f"Обновление завершено: {success_count} успешно, {skipped_count} пропущено (не пришло время)")
            return success_count
            
        except Exception as e:
            logger.error(f"Ошибка при обновлении всех инструментов: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return 0
    
    def start_background_update(self, base_check_interval: int = 60):
        """
        Запускает фоновое обновление данных.
        
        Каждый таймфрейм обновляется с интервалом, соответствующим его периоду:
        - Минутные (1m, 3m, 5m) - каждую минуту
        - 15-30 минутные - каждые 15 минут
        - Часовые - каждый час
        - 4-12 часовые - каждые 4 часа
        - Дневные и выше - раз в день
        
        Параметры:
            base_check_interval: Базовый интервал проверки в секундах (по умолчанию 60).
                                  Система проверяет каждую минуту, какие таймфреймы нужно обновить.
        """
        if self.is_running:
            logger.warning("Фоновое обновление уже запущено")
            return
        
        self.is_running = True
        self.base_check_interval = base_check_interval
        
        # Инициализируем словарь времени последнего обновления
        if not hasattr(self, 'last_update_times'):
            self.last_update_times = {}
        
        def update_loop():
            logger.info(f"Запуск фонового обновления данных (базовая проверка каждые {base_check_interval} сек)")
            logger.info("Интервалы обновления по таймфреймам:")
            logger.info("  - 1m, 3m, 5m: каждую минуту")
            logger.info("  - 15m, 30m: каждые 15 минут")
            logger.info("  - 1h, 2h: каждый час")
            logger.info("  - 4h, 6h, 12h: каждые 4 часа")
            logger.info("  - 1d, 1w, 1mo: раз в день")
            
            while self.is_running:
                try:
                    # Проверяем, какие таймфреймы нужно обновить
                    # Обновляем только те, для которых пришло время
                    logger.debug("Проверка необходимости обновления данных...")
                    self.update_all_instruments(force_all=False)
                    
                    # Ждем базовый интервал проверки
                    for _ in range(base_check_interval):
                        if not self.is_running:
                            break
                        time.sleep(1)
                        
                except Exception as e:
                    logger.error(f"Ошибка в цикле обновления: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    time.sleep(10)  # Небольшая задержка при ошибке
        
        self.update_thread = Thread(target=update_loop, daemon=True)
        self.update_thread.start()
        logger.info("Фоновый поток обновления данных запущен")
    
    def stop_background_update(self):
        """
        Останавливает фоновое обновление данных.
        """
        if not self.is_running:
            return
        
        self.is_running = False
        logger.info("Остановка фонового обновления данных...")
        
        if self.update_thread:
            self.update_thread.join(timeout=5)
            logger.info("Фоновый поток обновления данных остановлен")


if __name__ == "__main__":
    """
    Тестовый запуск обновлятеля данных.
    """
    updater = DataUpdater()
    
    # Обновляем данные один раз
    print("Обновление данных...")
    updater.update_all_instruments()
    
    # Запускаем фоновое обновление
    print("Запуск фонового обновления...")
    updater.start_background_update(update_interval=60)
    
    # Ждем 5 минут
    import time
    time.sleep(300)
    
    # Останавливаем
    updater.stop_background_update()

