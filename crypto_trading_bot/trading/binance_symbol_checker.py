"""
Модуль для проверки доступности символов на Binance.

Проверяет, какие символы из списка доступны для торговли на Binance.
"""

import requests
from typing import List, Set, Optional
from loguru import logger
import time

try:
    import ccxt
    CCXT_AVAILABLE = True
except ImportError:
    CCXT_AVAILABLE = False


class BinanceSymbolChecker:
    """
    Класс для проверки доступности символов на Binance.
    """
    
    BINANCE_API_URL = "https://api.binance.com/api/v3"
    
    def __init__(self):
        """
        Инициализация проверяльщика символов.
        """
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.ccxt_exchange = None
        
        if CCXT_AVAILABLE:
            try:
                self.ccxt_exchange = ccxt.binance({
                    'enableRateLimit': True,
                    'timeout': 30000,
                    'options': {
                        'defaultType': 'spot',
                    }
                })
                logger.info("CCXT инициализирован для проверки символов")
            except Exception as e:
                logger.warning(f"Не удалось инициализировать CCXT: {e}")
    
    def get_available_symbols_binance_api(self) -> Set[str]:
        """
        Получает список всех доступных символов на Binance через публичный API.
        
        Возвращает:
            set[str]: Множество доступных символов в формате 'SYMBOLUSDT'.
        """
        try:
            url = f"{self.BINANCE_API_URL}/exchangeInfo"
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            symbols = set()
            if 'symbols' in data:
                for symbol_info in data['symbols']:
                    symbol = symbol_info.get('symbol', '')
                    status = symbol_info.get('status', '')
                    # Только активные спотовые пары с USDT
                    if status == 'TRADING' and symbol.endswith('USDT'):
                        symbols.add(symbol)
            
            logger.info(f"Получено {len(symbols)} доступных символов через Binance API")
            return symbols
            
        except Exception as e:
            logger.error(f"Ошибка при получении списка символов через Binance API: {e}")
            return set()
    
    def get_available_symbols_ccxt(self) -> Set[str]:
        """
        Получает список всех доступных символов на Binance через CCXT.
        
        Возвращает:
            set[str]: Множество доступных символов в формате 'SYMBOLUSDT'.
        """
        if not CCXT_AVAILABLE or not self.ccxt_exchange:
            return set()
        
        try:
            markets = self.ccxt_exchange.load_markets()
            symbols = set()
            
            for symbol, market in markets.items():
                # Только активные спотовые пары с USDT
                if market.get('active', False) and market.get('quote', '') == 'USDT':
                    # Преобразуем формат CCXT (BTC/USDT) в формат Binance (BTCUSDT)
                    base = market.get('base', '')
                    if base:
                        binance_symbol = f"{base}USDT"
                        symbols.add(binance_symbol)
            
            logger.info(f"Получено {len(symbols)} доступных символов через CCXT")
            return symbols
            
        except Exception as e:
            logger.error(f"Ошибка при получении списка символов через CCXT: {e}")
            return set()
    
    def get_available_symbols(self) -> Set[str]:
        """
        Получает список всех доступных символов на Binance.
        Пробует оба метода (CCXT и Binance API) и объединяет результаты.
        
        Возвращает:
            set[str]: Множество доступных символов в формате 'SYMBOLUSDT'.
        """
        symbols_ccxt = self.get_available_symbols_ccxt()
        symbols_api = self.get_available_symbols_binance_api()
        
        # Объединяем результаты
        all_symbols = symbols_ccxt.union(symbols_api)
        
        logger.info(f"Всего доступно {len(all_symbols)} символов на Binance")
        return all_symbols
    
    def filter_available_symbols(self, symbols: List[str]) -> List[str]:
        """
        Фильтрует список символов, оставляя только те, что доступны на Binance.
        
        Параметры:
            symbols: Список символов для проверки.
        
        Возвращает:
            list[str]: Список доступных символов.
        """
        available_symbols = self.get_available_symbols()
        
        # Фильтруем только доступные
        filtered = [s for s in symbols if s in available_symbols]
        
        logger.info(f"Из {len(symbols)} символов доступно на Binance: {len(filtered)}")
        
        if len(symbols) > len(filtered):
            unavailable = set(symbols) - set(filtered)
            logger.warning(f"Недоступные на Binance символы ({len(unavailable)}): {list(unavailable)[:10]}...")
        
        return filtered
    
    def check_symbol_available(self, symbol: str) -> bool:
        """
        Проверяет, доступен ли конкретный символ на Binance.
        
        Параметры:
            symbol: Символ для проверки (например, 'BTCUSDT').
        
        Возвращает:
            bool: True если символ доступен, False в противном случае.
        """
        available_symbols = self.get_available_symbols()
        return symbol in available_symbols


if __name__ == "__main__":
    """
    Тестовый запуск для проверки работы Binance Symbol Checker.
    """
    checker = BinanceSymbolChecker()
    
    # Тестовые символы
    test_symbols = ['BTCUSDT', 'ETHUSDT', 'STETHUSDT', 'INVALIDUSDT']
    
    print("\nПроверка доступности символов:")
    for symbol in test_symbols:
        available = checker.check_symbol_available(symbol)
        print(f"{symbol}: {'✓ Доступен' if available else '✗ Недоступен'}")

