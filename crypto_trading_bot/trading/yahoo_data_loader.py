"""
Модуль для загрузки исторических данных криптовалют с Yahoo Finance.

Загружает данные за весь период существования монеты для всех таймфреймов.
"""
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from loguru import logger
import time

from crypto_trading_bot.database.data_export import DataExporter
from crypto_trading_bot.database.data_import import DataImport


class YahooDataLoader:
    """
    Класс для загрузки исторических данных криптовалют с Yahoo Finance.
    
    Загружает данные за максимально доступный период для каждого инструмента
    и сохраняет их в базу данных.
    """
    
    # Маппинг таймфреймов Yahoo Finance
    TIMEFRAME_MAPPING = {
        '1min': '1m',
        '5min': '5m',
        '15min': '15m',
        '30min': '30m',
        '1hour': '1h',
        '4hour': '4h',
        '1day': '1d',
        '1week': '1wk',
        '1month': '1mo'
    }
    
    # Маппинг символов для Yahoo Finance (добавляем -USD)
    SYMBOL_MAPPING = {
        'BTCUSDT': 'BTC-USD',
        'ETHUSDT': 'ETH-USD',
        'BNBUSDT': 'BNB-USD',
        # Добавьте другие по необходимости
    }
    
    def __init__(self):
        """
        Инициализация загрузчика данных с Yahoo Finance.
        """
        self.data_exporter = DataExporter()
        self.data_import = DataImport()
    
    def convert_symbol_to_yahoo(self, symbol: str) -> str:
        """
        Конвертирует символ биржи в символ Yahoo Finance.
        
        Параметры:
            symbol (str): Символ биржи (например, 'BTCUSDT').
        
        Возвращает:
            str: Символ Yahoo Finance (например, 'BTC-USD').
        """
        # Если есть маппинг, используем его
        if symbol in self.SYMBOL_MAPPING:
            return self.SYMBOL_MAPPING[symbol]
        
        # Иначе пытаемся преобразовать автоматически
        # Убираем USDT и добавляем -USD
        if symbol.endswith('USDT'):
            base = symbol[:-4]  # Убираем USDT
            return f"{base}-USD"
        
        return symbol
    
    def load_historical_data(self, symbol: str, timeframe: str, 
                            period: str = "max") -> Optional[pd.DataFrame]:
        """
        Загружает исторические данные с Yahoo Finance.
        
        Параметры:
            symbol (str): Символ инструмента (например, 'BTCUSDT').
            timeframe (str): Таймфрейм ('1min', '5min', '1hour', '1day' и т.д.).
            period (str): Период загрузки ('max', '1y', '2y', '5y' и т.д.).
        
        Возвращает:
            pd.DataFrame или None: Данные о ценах или None в случае ошибки.
        """
        try:
            yahoo_symbol = self.convert_symbol_to_yahoo(symbol)
            yahoo_interval = self.TIMEFRAME_MAPPING.get(timeframe, '1d')
            
            logger.info(f"Загрузка данных для {symbol} ({yahoo_symbol}) на таймфрейме {timeframe}...")
            
            # Загружаем данные с Yahoo Finance
            ticker = yf.Ticker(yahoo_symbol)
            
            # Для разных таймфреймов Yahoo Finance имеет ограничения
            # Для мелких таймфреймов (1m, 5m) максимальный период - 7 дней
            # Для дневных - можно загрузить весь период
            if yahoo_interval in ['1m', '5m', '15m', '30m']:
                # Для минутных таймфреймов ограничиваем период
                if period == "max":
                    period = "7d"  # Максимум 7 дней для минутных таймфреймов
            elif yahoo_interval == '1h':
                if period == "max":
                    period = "730d"  # Максимум 2 года для часовых
            # Для дневных таймфреймов можно загрузить весь период
            
            df = ticker.history(period=period, interval=yahoo_interval)
            
            if df.empty:
                logger.warning(f"Нет данных для {symbol} на таймфрейме {timeframe}")
                return None
            
            logger.info(f"Загружено {len(df)} свечей для {symbol} на {timeframe} (период: {period})")
            return df
            
        except Exception as e:
            logger.error(f"Ошибка при загрузке данных для {symbol} на {timeframe}: {e}")
            return None
    
    def save_data_to_db(self, symbol: str, timeframe: str, df: pd.DataFrame) -> bool:
        """
        Сохраняет загруженные данные в базу данных.
        
        Параметры:
            symbol (str): Символ инструмента.
            timeframe (str): Таймфрейм.
            df (pd.DataFrame): DataFrame с данными о ценах.
        
        Возвращает:
            bool: True если данные успешно сохранены.
        """
        try:
            # Сохраняем DataFrame напрямую через DataExporter
            # Метод insert_price_data теперь поддерживает DataFrame
            success = self.data_exporter.insert_price_data(symbol, timeframe, df)
            
            if success:
                logger.info(f"Данные для {symbol} на {timeframe} сохранены в БД ({len(df)} свечей)")
            else:
                logger.warning(f"Не удалось сохранить данные для {symbol} на {timeframe}")
            
            return success
            
        except Exception as e:
            logger.error(f"Ошибка при сохранении данных в БД: {e}")
            return False
    
    def ensure_instrument_exists(self, symbol: str) -> bool:
        """
        Убеждается, что инструмент существует в базе данных. Если нет - добавляет его.
        
        Параметры:
            symbol (str): Символ инструмента.
        
        Возвращает:
            bool: True если инструмент существует или был добавлен.
        """
        try:
            # Проверяем, существует ли инструмент
            instruments = self.data_import.get_instruments()
            for inst in instruments:
                if inst.symbol.lower() == symbol.lower():
                    logger.debug(f"Инструмент {symbol} уже существует в БД")
                    return True
            
            # Если не существует, добавляем
            logger.info(f"Добавление инструмента {symbol} в БД...")
            query = """
                INSERT INTO instruments (symbol)
                VALUES (%s)
                ON CONFLICT (symbol) DO NOTHING;
            """
            from crypto_trading_bot.database.db_connection import DatabaseManager
            db = DatabaseManager()
            db.execute_query(query, (symbol,))
            db.connection.commit()
            db.close()
            
            logger.info(f"Инструмент {symbol} добавлен в БД")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка при добавлении инструмента {symbol}: {e}")
            return False
    
    def load_all_data_for_symbol(self, symbol: str, timeframes: List[str] = None) -> Dict[str, bool]:
        """
        Загружает все исторические данные для указанного символа по всем таймфреймам.
        
        Параметры:
            symbol (str): Символ инструмента.
            timeframes (list[str], optional): Список таймфреймов. 
                По умолчанию: ['1day', '4hour', '1hour', '15min'].
        
        Возвращает:
            dict: Словарь с результатами загрузки для каждого таймфрейма.
        """
        if timeframes is None:
            timeframes = ['1day', '4hour', '1hour', '15min']
        
        # Убеждаемся, что инструмент существует в БД
        self.ensure_instrument_exists(symbol)
        
        results = {}
        
        logger.info(f"Начало загрузки данных для {symbol}...")
        
        for timeframe in timeframes:
            try:
                # Загружаем данные
                df = self.load_historical_data(symbol, timeframe, period="max")
                
                if df is not None and not df.empty:
                    # Сохраняем в БД
                    success = self.save_data_to_db(symbol, timeframe, df)
                    results[timeframe] = success
                else:
                    results[timeframe] = False
                
                # Небольшая задержка между запросами
                time.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Ошибка при загрузке данных для {symbol} на {timeframe}: {e}")
                results[timeframe] = False
        
        logger.info(f"Загрузка данных для {symbol} завершена")
        return results
    
    def load_data_for_top_coins(self, symbols: List[str], timeframes: List[str] = None) -> Dict[str, Dict[str, bool]]:
        """
        Загружает исторические данные для списка символов.
        
        Параметры:
            symbols (list[str]): Список символов инструментов.
            timeframes (list[str], optional): Список таймфреймов.
        
        Возвращает:
            dict: Словарь с результатами загрузки для каждого символа.
        """
        all_results = {}
        
        logger.info(f"Начало загрузки данных для {len(symbols)} инструментов...")
        
        for i, symbol in enumerate(symbols, 1):
            logger.info(f"[{i}/{len(symbols)}] Обработка {symbol}...")
            results = self.load_all_data_for_symbol(symbol, timeframes)
            all_results[symbol] = results
            
            # Задержка между инструментами
            time.sleep(1)
        
        logger.info("Загрузка данных для всех инструментов завершена")
        return all_results


if __name__ == "__main__":
    """
    Тестовый запуск для загрузки данных.
    """
    loader = YahooDataLoader()
    
    # Тестовая загрузка для BTC
    test_symbols = ['BTCUSDT', 'ETHUSDT']
    loader.load_data_for_top_coins(test_symbols, ['1day', '4hour', '1hour'])

