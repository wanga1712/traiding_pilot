"""
Модуль для получения исторических данных криптовалют (OHLCV) из различных бесплатных источников.

Поддерживает получение данных за период до 2 лет из источников, доступных из России:
- CCXT (универсальная библиотека для криптобирж)
- Binance API (публичный API)
- CoinGecko API
- yfinance (Yahoo Finance)
"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
from loguru import logger
import time

try:
    import ccxt
    CCXT_AVAILABLE = True
except ImportError:
    CCXT_AVAILABLE = False
    logger.warning("Библиотека ccxt не установлена. Установите: pip install ccxt")

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False
    logger.warning("Библиотека yfinance не установлена. Установите: pip install yfinance")

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    logger.warning("Библиотека requests не установлена. Установите: pip install requests")


class CryptoDataProvider:
    """
    Класс для получения исторических данных криптовалют из различных источников.
    
    Поддерживает несколько источников данных с автоматическим fallback,
    если один источник недоступен.
    """
    
    # Маппинг таймфреймов для разных источников
    # ВАЖНО: Минутные таймфреймы (1min, 3min, 5min) критически важны для обучения ИИ модели
    TIMEFRAME_MAPPING = {
        '1min': {'ccxt': '1m', 'binance': '1m', 'yfinance': '1m'},
        '3min': {'ccxt': '3m', 'binance': '3m', 'yfinance': '5m'},  # yfinance не поддерживает 3m, используем 5m
        '5min': {'ccxt': '5m', 'binance': '5m', 'yfinance': '5m'},
        '15min': {'ccxt': '15m', 'binance': '15m', 'yfinance': '15m'},
        '30min': {'ccxt': '30m', 'binance': '30m', 'yfinance': '30m'},
        '1hour': {'ccxt': '1h', 'binance': '1h', 'yfinance': '1h'},
        '4hour': {'ccxt': '4h', 'binance': '4h', 'yfinance': '4h'},
        '1day': {'ccxt': '1d', 'binance': '1d', 'yfinance': '1d'},
        '1week': {'ccxt': '1w', 'binance': '1w', 'yfinance': '1wk'},
    }
    
    # Маппинг символов для разных источников
    SYMBOL_MAPPING = {
        'BTCUSDT': {'ccxt': 'BTC/USDT', 'binance': 'BTCUSDT', 'yfinance': 'BTC-USD'},
        'ETHUSDT': {'ccxt': 'ETH/USDT', 'binance': 'ETHUSDT', 'yfinance': 'ETH-USD'},
        'BNBUSDT': {'ccxt': 'BNB/USDT', 'binance': 'BNBUSDT', 'yfinance': 'BNB-USD'},
        'ADAUSDT': {'ccxt': 'ADA/USDT', 'binance': 'ADAUSDT', 'yfinance': 'ADA-USD'},
        'SOLUSDT': {'ccxt': 'SOL/USDT', 'binance': 'SOLUSDT', 'yfinance': 'SOL-USD'},
        'XRPUSDT': {'ccxt': 'XRP/USDT', 'binance': 'XRPUSDT', 'yfinance': 'XRP-USD'},
    }
    
    def __init__(self):
        """
        Инициализация провайдера данных.
        """
        self.ccxt_exchange = None
        if CCXT_AVAILABLE:
            try:
                # Используем Binance через CCXT (работает из России)
                self.ccxt_exchange = ccxt.binance({
                    'enableRateLimit': True,
                    'timeout': 30000,  # Таймаут 30 секунд
                    'options': {
                        'defaultType': 'spot',  # spot, future, delivery
                    }
                })
                logger.info("CCXT инициализирован с биржей Binance (таймаут: 30 сек)")
            except Exception as e:
                logger.warning(f"Не удалось инициализировать CCXT: {e}")
    
    def _convert_symbol(self, symbol: str, source: str) -> str:
        """
        Конвертирует символ в формат, требуемый источником данных.
        
        Параметры:
            symbol (str): Исходный символ (например, 'BTCUSDT').
            source (str): Источник данных ('ccxt', 'binance', 'yfinance').
        
        Возвращает:
            str: Символ в формате источника.
        """
        if symbol in self.SYMBOL_MAPPING:
            return self.SYMBOL_MAPPING[symbol].get(source, symbol)
        
        # Автоматическое преобразование
        if source == 'ccxt' and symbol.endswith('USDT'):
            base = symbol[:-4]
            return f"{base}/USDT"
        elif source == 'yfinance' and symbol.endswith('USDT'):
            base = symbol[:-4]
            return f"{base}-USD"
        
        return symbol
    
    def _convert_timeframe(self, timeframe: str, source: str) -> str:
        """
        Конвертирует таймфрейм в формат источника данных.
        
        Параметры:
            timeframe (str): Исходный таймфрейм (например, '1hour').
            source (str): Источник данных.
        
        Возвращает:
            str: Таймфрейм в формате источника.
        """
        if timeframe in self.TIMEFRAME_MAPPING:
            return self.TIMEFRAME_MAPPING[timeframe].get(source, timeframe)
        return timeframe
    
    def get_data_via_ccxt(self, symbol: str, timeframe: str, 
                          start_date: datetime, end_date: datetime) -> Optional[pd.DataFrame]:
        """
        Получает исторические данные через CCXT (Binance).
        
        Параметры:
            symbol (str): Символ инструмента (например, 'BTCUSDT').
            timeframe (str): Таймфрейм (например, '1hour').
            start_date (datetime): Начальная дата.
            end_date (datetime): Конечная дата.
        
        Возвращает:
            pd.DataFrame или None: Данные OHLCV или None в случае ошибки.
        """
        if not CCXT_AVAILABLE or not self.ccxt_exchange:
            return None
        
        try:
            ccxt_symbol = self._convert_symbol(symbol, 'ccxt')
            ccxt_timeframe = self._convert_timeframe(timeframe, 'ccxt')
            
            logger.info(f"Загрузка данных через CCXT для {symbol} ({ccxt_symbol}) на {timeframe}...")
            
            # Преобразуем даты в миллисекунды (timestamp)
            since = int(start_date.timestamp() * 1000)
            end_timestamp = int(end_date.timestamp() * 1000)
            
            all_ohlcv = []
            current_since = since
            
            # CCXT может возвращать ограниченное количество свечей за запрос
            # Поэтому делаем запросы порциями
            batch_count = 0
            max_batches = 1000  # Ограничиваем количество батчей для предотвращения зависания
            
            while current_since < end_timestamp and batch_count < max_batches:
                try:
                    batch_count += 1
                    
                    # Логируем прогресс каждые 10 батчей
                    if batch_count % 10 == 0:
                        logger.info(f"Загружено батчей: {batch_count}, свечей: {len(all_ohlcv)}")
                    elif batch_count == 1:
                        logger.info(f"Начало загрузки первого батча...")
                    
                    # Выполняем запрос с таймаутом
                    try:
                        ohlcv = self.ccxt_exchange.fetch_ohlcv(
                            ccxt_symbol,
                            ccxt_timeframe,
                            since=current_since,
                            limit=1000  # Максимум свечей за запрос
                        )
                    except Exception as fetch_error:
                        logger.error(f"Ошибка при выполнении запроса CCXT (батч {batch_count}): {fetch_error}")
                        # Пробуем еще раз через небольшую задержку
                        time.sleep(1)
                        try:
                            ohlcv = self.ccxt_exchange.fetch_ohlcv(
                                ccxt_symbol,
                                ccxt_timeframe,
                                since=current_since,
                                limit=1000
                            )
                        except Exception as retry_error:
                            logger.error(f"Повторная попытка также не удалась: {retry_error}")
                            break
                    
                    if not ohlcv:
                        logger.info(f"Нет данных для батча {batch_count}, завершаем загрузку")
                        break
                    
                    all_ohlcv.extend(ohlcv)
                    
                    # Обновляем since на timestamp последней свечи + 1
                    current_since = ohlcv[-1][0] + 1
                    
                    # Если получили меньше 1000 свечей, значит достигли конца
                    if len(ohlcv) < 1000:
                        logger.info(f"Получено меньше 1000 свечей в батче {batch_count}, завершаем загрузку")
                        break
                    
                    # Небольшая задержка для соблюдения rate limit
                    time.sleep(0.1)
                    
                except Exception as e:
                    logger.warning(f"Ошибка при загрузке порции данных через CCXT (батч {batch_count}): {e}")
                    break
            
            if batch_count >= max_batches:
                logger.warning(f"Достигнут лимит батчей ({max_batches}), загрузка прервана")
            
            if not all_ohlcv:
                logger.warning(f"Нет данных через CCXT для {symbol}")
                return None
            
            # Преобразуем в DataFrame
            df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            # Добавляем колонку trades (если доступна)
            if len(all_ohlcv[0]) > 6:
                df['trades'] = [row[6] for row in all_ohlcv]
            else:
                df['trades'] = 0
            
            logger.info(f"Загружено {len(df)} свечей через CCXT для {symbol}")
            return df
            
        except Exception as e:
            logger.error(f"Ошибка при получении данных через CCXT для {symbol}: {e}")
            return None
    
    def get_data_via_binance_api(self, symbol: str, timeframe: str,
                                 start_date: datetime, end_date: datetime) -> Optional[pd.DataFrame]:
        """
        Получает исторические данные напрямую через Binance API.
        
        Параметры:
            symbol (str): Символ инструмента (например, 'BTCUSDT').
            timeframe (str): Таймфрейм (например, '1hour').
            start_date (datetime): Начальная дата.
            end_date (datetime): Конечная дата.
        
        Возвращает:
            pd.DataFrame или None: Данные OHLCV или None в случае ошибки.
        """
        if not REQUESTS_AVAILABLE:
            return None
        
        try:
            binance_symbol = self._convert_symbol(symbol, 'binance')
            binance_interval = self._convert_timeframe(timeframe, 'binance')
            
            logger.info(f"Загрузка данных через Binance API для {symbol} на {timeframe}...")
            
            # Маппинг интервалов для Binance API
            interval_map = {
                '1m': '1m', '3m': '3m', '5m': '5m', '15m': '15m', '30m': '30m',
                '1h': '1h', '2h': '2h', '4h': '4h', '6h': '6h', '8h': '8h', '12h': '12h',
                '1d': '1d', '3d': '3d', '1w': '1w', '1M': '1M'
            }
            
            interval = interval_map.get(binance_interval, '1h')
            
            all_data = []
            start_time = int(start_date.timestamp() * 1000)
            end_time = int(end_date.timestamp() * 1000)
            current_start = start_time
            
            # Binance API возвращает максимум 1000 свечей за запрос
            while current_start < end_time:
                try:
                    url = 'https://api.binance.com/api/v3/klines'
                    params = {
                        'symbol': binance_symbol,
                        'interval': interval,
                        'startTime': current_start,
                        'endTime': end_time,
                        'limit': 1000
                    }
                    
                    response = requests.get(url, params=params, timeout=10)
                    response.raise_for_status()
                    data = response.json()
                    
                    if not data:
                        break
                    
                    all_data.extend(data)
                    
                    # Обновляем startTime на timestamp последней свечи + 1
                    current_start = data[-1][6] + 1  # [6] - это closeTime
                    
                    # Если получили меньше 1000 свечей, значит достигли конца
                    if len(data) < 1000:
                        break
                    
                    time.sleep(0.1)  # Задержка для соблюдения rate limit
                    
                except Exception as e:
                    logger.warning(f"Ошибка при загрузке порции данных через Binance API: {e}")
                    break
            
            if not all_data:
                logger.warning(f"Нет данных через Binance API для {symbol}")
                return None
            
            # Преобразуем в DataFrame
            # Формат Binance: [timestamp, open, high, low, close, volume, ...]
            df = pd.DataFrame(all_data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])
            
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            # Конвертируем типы
            df['open'] = df['open'].astype(float)
            df['high'] = df['high'].astype(float)
            df['low'] = df['low'].astype(float)
            df['close'] = df['close'].astype(float)
            df['volume'] = df['volume'].astype(float)
            df['trades'] = df['trades'].astype(int)
            
            logger.info(f"Загружено {len(df)} свечей через Binance API для {symbol}")
            return df
            
        except Exception as e:
            logger.error(f"Ошибка при получении данных через Binance API для {symbol}: {e}")
            return None
    
    def get_data_via_yfinance(self, symbol: str, timeframe: str,
                              start_date: datetime, end_date: datetime) -> Optional[pd.DataFrame]:
        """
        Получает исторические данные через yfinance (Yahoo Finance).
        
        Параметры:
            symbol (str): Символ инструмента (например, 'BTCUSDT').
            timeframe (str): Таймфрейм (например, '1hour').
            start_date (datetime): Начальная дата.
            end_date (datetime): Конечная дата.
        
        Возвращает:
            pd.DataFrame или None: Данные OHLCV или None в случае ошибки.
        """
        if not YFINANCE_AVAILABLE:
            return None
        
        try:
            yfinance_symbol = self._convert_symbol(symbol, 'yfinance')
            yfinance_interval = self._convert_timeframe(timeframe, 'yfinance')
            
            logger.info(f"Загрузка данных через yfinance для {symbol} ({yfinance_symbol}) на {timeframe}...")
            
            ticker = yf.Ticker(yfinance_symbol)
            
            # yfinance имеет ограничения по таймфреймам
            # Для минутных таймфреймов максимальный период - 7 дней
            # Для часовых - 730 дней (2 года)
            # Для дневных - весь период
            
            if yfinance_interval in ['1m', '5m', '15m', '30m']:
                # Для минутных таймфреймов ограничиваем период до 7 дней
                if (end_date - start_date).days > 7:
                    logger.warning(f"yfinance поддерживает максимум 7 дней для минутных таймфреймов")
                    start_date = end_date - timedelta(days=7)
            
            df = ticker.history(
                start=start_date.strftime('%Y-%m-%d'),
                end=end_date.strftime('%Y-%m-%d'),
                interval=yfinance_interval
            )
            
            if df.empty:
                logger.warning(f"Нет данных через yfinance для {symbol}")
                return None
            
            # Переименовываем колонки для единообразия
            df.rename(columns={
                'Open': 'open',
                'High': 'high',
                'Low': 'low',
                'Close': 'close',
                'Volume': 'volume'
            }, inplace=True)
            
            # Добавляем колонку trades (yfinance не предоставляет эту информацию)
            df['trades'] = 0
            
            logger.info(f"Загружено {len(df)} свечей через yfinance для {symbol}")
            return df
            
        except Exception as e:
            logger.error(f"Ошибка при получении данных через yfinance для {symbol}: {e}")
            return None
    
    def get_recent_data(self, symbol: str, timeframe: str, 
                       limit: int = 150,
                       sources: List[str] = None) -> Optional[pd.DataFrame]:
        """
        Получает последние N свечей из доступных источников с автоматическим fallback.
        
        Параметры:
            symbol (str): Символ инструмента (например, 'BTCUSDT').
            timeframe (str): Таймфрейм (например, '1hour', '1day').
            limit (int): Количество последних свечей для загрузки (по умолчанию 150).
            sources (list[str], optional): Список источников для попытки загрузки.
                По умолчанию: ['ccxt', 'binance', 'yfinance'].
        
        Возвращает:
            pd.DataFrame или None: Данные OHLCV или None в случае ошибки.
        """
        if sources is None:
            sources = ['ccxt', 'binance', 'yfinance']
        
        logger.info(f"Загрузка последних {limit} свечей для {symbol} на {timeframe}")
        
        # Пробуем загрузить данные из каждого источника по очереди
        for source in sources:
            try:
                if source == 'ccxt':
                    df = self._get_recent_data_via_ccxt(symbol, timeframe, limit)
                elif source == 'binance':
                    df = self._get_recent_data_via_binance_api(symbol, timeframe, limit)
                elif source == 'yfinance':
                    df = self._get_recent_data_via_yfinance(symbol, timeframe, limit)
                else:
                    continue
                
                if df is not None and not df.empty:
                    # Ограничиваем до запрошенного количества
                    if len(df) > limit:
                        df = df.tail(limit)
                    logger.info(f"Успешно загружены последние {len(df)} свечей для {symbol} из источника {source}")
                    return df
                    
            except Exception as e:
                logger.warning(f"Ошибка при загрузке данных из источника {source}: {e}")
                continue
        
        logger.error(f"Не удалось загрузить данные для {symbol} ни из одного источника")
        return None
    
    def _get_recent_data_via_ccxt(self, symbol: str, timeframe: str, limit: int) -> Optional[pd.DataFrame]:
        """
        Получает последние N свечей через CCXT.
        """
        if not CCXT_AVAILABLE or not self.ccxt_exchange:
            return None
        
        try:
            ccxt_symbol = self._convert_symbol(symbol, 'ccxt')
            ccxt_timeframe = self._convert_timeframe(timeframe, 'ccxt')
            
            logger.info(f"Загрузка последних {limit} свечей через CCXT для {symbol} ({ccxt_symbol}) на {timeframe}...")
            
            # Загружаем последние свечи (без указания since, только limit)
            ohlcv = self.ccxt_exchange.fetch_ohlcv(
                ccxt_symbol,
                ccxt_timeframe,
                limit=min(limit, 1000)  # CCXT максимум 1000 за запрос
            )
            
            if not ohlcv:
                logger.warning(f"Нет данных через CCXT для {symbol}")
                return None
            
            # Преобразуем в DataFrame
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            # Добавляем колонку trades (если доступна)
            if len(ohlcv[0]) > 6:
                df['trades'] = [row[6] for row in ohlcv]
            else:
                df['trades'] = 0
            
            # Ограничиваем до запрошенного количества (берем последние)
            if len(df) > limit:
                df = df.tail(limit)
            
            logger.info(f"Загружено {len(df)} свечей через CCXT для {symbol}")
            return df
            
        except Exception as e:
            logger.error(f"Ошибка при получении данных через CCXT для {symbol}: {e}")
            return None
    
    def _get_recent_data_via_binance_api(self, symbol: str, timeframe: str, limit: int) -> Optional[pd.DataFrame]:
        """
        Получает последние N свечей через Binance API.
        """
        if not REQUESTS_AVAILABLE:
            return None
        
        try:
            binance_symbol = self._convert_symbol(symbol, 'binance')
            binance_interval = self._convert_timeframe(timeframe, 'binance')
            
            logger.info(f"Загрузка последних {limit} свечей через Binance API для {symbol} на {timeframe}...")
            
            # Маппинг интервалов для Binance API
            interval_map = {
                '1m': '1m', '3m': '3m', '5m': '5m', '15m': '15m', '30m': '30m',
                '1h': '1h', '2h': '2h', '4h': '4h', '6h': '6h', '8h': '8h', '12h': '12h',
                '1d': '1d', '3d': '3d', '1w': '1w', '1M': '1M'
            }
            
            interval = interval_map.get(binance_interval, '1h')
            
            url = 'https://api.binance.com/api/v3/klines'
            params = {
                'symbol': binance_symbol,
                'interval': interval,
                'limit': min(limit, 1000)  # Binance максимум 1000 за запрос
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if not data:
                logger.warning(f"Нет данных через Binance API для {symbol}")
                return None
            
            # Преобразуем в DataFrame
            df = pd.DataFrame(data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])
            
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            # Конвертируем типы
            df['open'] = df['open'].astype(float)
            df['high'] = df['high'].astype(float)
            df['low'] = df['low'].astype(float)
            df['close'] = df['close'].astype(float)
            df['volume'] = df['volume'].astype(float)
            df['trades'] = df['trades'].astype(int)
            
            # Ограничиваем до запрошенного количества
            if len(df) > limit:
                df = df.tail(limit)
            
            logger.info(f"Загружено {len(df)} свечей через Binance API для {symbol}")
            return df
            
        except Exception as e:
            logger.error(f"Ошибка при получении данных через Binance API для {symbol}: {e}")
            return None
    
    def _get_recent_data_via_yfinance(self, symbol: str, timeframe: str, limit: int) -> Optional[pd.DataFrame]:
        """
        Получает последние N свечей через yfinance.
        """
        if not YFINANCE_AVAILABLE:
            return None
        
        try:
            yfinance_symbol = self._convert_symbol(symbol, 'yfinance')
            yfinance_interval = self._convert_timeframe(timeframe, 'yfinance')
            
            logger.info(f"Загрузка последних {limit} свечей через yfinance для {symbol} ({yfinance_symbol}) на {timeframe}...")
            
            ticker = yf.Ticker(yfinance_symbol)
            
            # Для yfinance определяем период на основе количества свечей
            # Примерно: для 1d нужно limit дней, для 1h - limit часов и т.д.
            if yfinance_interval in ['1m', '5m', '15m', '30m']:
                period = "7d"  # Максимум 7 дней для минутных
            elif yfinance_interval == '1h':
                days = max(7, limit // 24 + 1)  # Примерно limit часов = limit/24 дней
                period = f"{min(days, 730)}d"  # Максимум 2 года
            else:
                days = max(30, limit + 1)
                period = f"{min(days, 730)}d"
            
            df = ticker.history(period=period, interval=yfinance_interval)
            
            if df.empty:
                logger.warning(f"Нет данных через yfinance для {symbol}")
                return None
            
            # Переименовываем колонки
            df.rename(columns={
                'Open': 'open',
                'High': 'high',
                'Low': 'low',
                'Close': 'close',
                'Volume': 'volume'
            }, inplace=True)
            
            # Добавляем колонку trades
            df['trades'] = 0
            
            # Ограничиваем до запрошенного количества (берем последние)
            if len(df) > limit:
                df = df.tail(limit)
            
            logger.info(f"Загружено {len(df)} свечей через yfinance для {symbol}")
            return df
            
        except Exception as e:
            logger.error(f"Ошибка при получении данных через yfinance для {symbol}: {e}")
            return None
    
    def get_historical_data(self, symbol: str, timeframe: str, 
                            years: float = 2,
                            start_date: datetime = None,
                            end_date: datetime = None,
                            sources: List[str] = None) -> Optional[pd.DataFrame]:
        """
        Получает исторические данные из доступных источников с автоматическим fallback.
        
        Параметры:
            symbol (str): Символ инструмента (например, 'BTCUSDT').
            timeframe (str): Таймфрейм (например, '1hour', '1day').
            years (float): Количество лет истории (по умолчанию 2). Используется если не указаны start_date/end_date.
            start_date (datetime, optional): Начальная дата. Если указана, years игнорируется.
            end_date (datetime, optional): Конечная дата. По умолчанию текущее время.
            sources (list[str], optional): Список источников для попытки загрузки.
                По умолчанию: ['ccxt', 'binance', 'yfinance'].
        
        Возвращает:
            pd.DataFrame или None: Данные OHLCV или None в случае ошибки.
        """
        if sources is None:
            sources = ['ccxt', 'binance', 'yfinance']
        
        if end_date is None:
            end_date = datetime.now()
        
        if start_date is None:
            start_date = end_date - timedelta(days=years * 365)
        
        logger.info(f"Загрузка данных для {symbol} на {timeframe} за период {start_date.date()} - {end_date.date()}")
        
        # Пробуем загрузить данные из каждого источника по очереди
        for source in sources:
            try:
                if source == 'ccxt':
                    df = self.get_data_via_ccxt(symbol, timeframe, start_date, end_date)
                elif source == 'binance':
                    df = self.get_data_via_binance_api(symbol, timeframe, start_date, end_date)
                elif source == 'yfinance':
                    df = self.get_data_via_yfinance(symbol, timeframe, start_date, end_date)
                else:
                    continue
                
                if df is not None and not df.empty:
                    logger.info(f"Успешно загружены данные для {symbol} из источника {source}")
                    return df
                    
            except Exception as e:
                logger.warning(f"Ошибка при загрузке данных из источника {source}: {e}")
                continue
        
        logger.error(f"Не удалось загрузить данные для {symbol} ни из одного источника")
        return None
    
    def get_data_for_candlestick_chart(self, symbol: str, timeframe: str = '1day',
                                      years: int = 2) -> Optional[pd.DataFrame]:
        """
        Получает данные специально для построения свечного графика.
        
        Параметры:
            symbol (str): Символ инструмента (например, 'BTCUSDT').
            timeframe (str): Таймфрейм (по умолчанию '1day').
            years (int): Количество лет истории (по умолчанию 2).
        
        Возвращает:
            pd.DataFrame или None: Данные в формате для mplfinance или None.
        """
        df = self.get_historical_data(symbol, timeframe, years)
        
        if df is None or df.empty:
            return None
        
        # Убеждаемся, что все необходимые колонки присутствуют
        required_columns = ['open', 'high', 'low', 'close', 'volume']
        if not all(col in df.columns for col in required_columns):
            logger.error(f"Отсутствуют необходимые колонки в данных для {symbol}")
            return None
        
        # Выбираем только нужные колонки и переименовываем для mplfinance
        df_candlestick = df[required_columns].copy()
        df_candlestick.columns = [col.capitalize() for col in required_columns]
        
        return df_candlestick


if __name__ == "__main__":
    """
    Тестовый запуск для проверки работы провайдера данных.
    """
    provider = CryptoDataProvider()
    
    # Тестовая загрузка данных для BTC за последние 2 года
    test_symbol = 'BTCUSDT'
    test_timeframe = '1day'
    
    logger.info(f"Тестовая загрузка данных для {test_symbol} на таймфрейме {test_timeframe}...")
    
    df = provider.get_historical_data(test_symbol, test_timeframe, years=2)
    
    if df is not None:
        logger.info(f"Успешно загружено {len(df)} свечей")
        logger.info(f"\nПервые 5 строк:\n{df.head()}")
        logger.info(f"\nПоследние 5 строк:\n{df.tail()}")
        logger.info(f"\nСтатистика:\n{df.describe()}")
    else:
        logger.error("Не удалось загрузить данные")

