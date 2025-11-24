"""
Модуль для получения списка криптовалют по капитализации через CoinGecko API.

CoinGecko API бесплатный и работает из России.
"""

import requests
from typing import List, Dict, Optional
from loguru import logger
import time


class CoinGeckoFetcher:
    """
    Класс для получения данных о криптовалютах через CoinGecko API.
    """
    
    BASE_URL = "https://api.coingecko.com/api/v3"
    
    def __init__(self):
        """
        Инициализация CoinGecko Fetcher.
        """
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def get_ethereum_market_cap(self) -> Optional[float]:
        """
        Получает текущую рыночную капитализацию Ethereum.
        
        Возвращает:
            float или None: Капитализация Ethereum в USD или None в случае ошибки.
        """
        try:
            url = f"{self.BASE_URL}/simple/price"
            params = {
                'ids': 'ethereum',
                'vs_currencies': 'usd',
                'include_market_cap': 'true'
            }
            
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if 'ethereum' in data and 'usd_market_cap' in data['ethereum']:
                market_cap = data['ethereum']['usd_market_cap']
                logger.info(f"Капитализация Ethereum: ${market_cap:,.0f}")
                return market_cap
            
            return None
            
        except Exception as e:
            logger.error(f"Ошибка при получении капитализации Ethereum: {e}")
            return None
    
    def get_coins_by_market_cap(self, max_market_cap: float, limit: int = 100) -> List[Dict]:
        """
        Получает список криптовалют с капитализацией меньше указанной.
        
        Параметры:
            max_market_cap (float): Максимальная капитализация в USD.
            limit (int): Максимальное количество монет для получения (по умолчанию 100).
        
        Возвращает:
            list[dict]: Список словарей с информацией о монетах.
        """
        try:
            url = f"{self.BASE_URL}/coins/markets"
            params = {
                'vs_currency': 'usd',
                'order': 'market_cap_desc',
                'per_page': min(limit, 250),  # CoinGecko максимум 250 за запрос
                'page': 1,
                'sparkline': 'false'
            }
            
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            coins = response.json()
            
            # Фильтруем по максимальной капитализации
            filtered_coins = [
                coin for coin in coins 
                if coin.get('market_cap', 0) > 0 and coin.get('market_cap', 0) <= max_market_cap
            ]
            
            logger.info(f"Найдено {len(filtered_coins)} монет с капитализацией <= ${max_market_cap:,.0f}")
            return filtered_coins
            
        except Exception as e:
            logger.error(f"Ошибка при получении списка монет: {e}")
            return []
    
    def get_coins_below_eth_cap_ratio(self, ratio: float = 5.0, limit: int = 100) -> List[Dict]:
        """
        Получает список криптовалют с капитализацией в ratio раз меньше Ethereum.
        
        Параметры:
            ratio (float): Во сколько раз капитализация должна быть меньше ETH (по умолчанию 5.0).
            limit (int): Максимальное количество монет для получения.
        
        Возвращает:
            list[dict]: Список словарей с информацией о монетах.
        """
        try:
            # Получаем капитализацию Ethereum
            eth_market_cap = self.get_ethereum_market_cap()
            
            if not eth_market_cap:
                logger.warning("Не удалось получить капитализацию Ethereum, используем значение по умолчанию")
                # Используем примерное значение (около $400 млрд)
                eth_market_cap = 400_000_000_000
            
            # Вычисляем максимальную капитализацию
            max_market_cap = eth_market_cap / ratio
            
            logger.info(f"Ищем монеты с капитализацией <= ${max_market_cap:,.0f} (ETH / {ratio})")
            
            # Получаем список монет
            coins = self.get_coins_by_market_cap(max_market_cap, limit)
            
            return coins
            
        except Exception as e:
            logger.error(f"Ошибка при получении монет ниже ETH/{ratio}: {e}")
            return []
    
    def convert_to_binance_symbols(self, coins: List[Dict]) -> List[str]:
        """
        Преобразует список монет из CoinGecko в символы для Binance.
        
        Параметры:
            coins: Список словарей с информацией о монетах из CoinGecko.
        
        Возвращает:
            list[str]: Список символов в формате 'SYMBOLUSDT'.
        """
        symbols = []
        
        for coin in coins:
            symbol = coin.get('symbol', '').upper()
            if symbol:
                # Добавляем USDT для создания торговой пары
                binance_symbol = f"{symbol}USDT"
                symbols.append(binance_symbol)
        
        logger.info(f"Преобразовано {len(symbols)} символов для Binance")
        return symbols
    
    def get_filtered_symbols(self, ratio: float = 5.0, limit: int = 100) -> List[str]:
        """
        Получает список символов криптовалют с капитализацией в ratio раз меньше Ethereum.
        
        Параметры:
            ratio (float): Во сколько раз капитализация должна быть меньше ETH.
            limit (int): Максимальное количество монет.
        
        Возвращает:
            list[str]: Список символов в формате 'SYMBOLUSDT'.
        """
        coins = self.get_coins_below_eth_cap_ratio(ratio, limit)
        symbols = self.convert_to_binance_symbols(coins)
        
        return symbols
    
    def get_coins_with_market_cap(self, ratio: float = 5.0, limit: int = 100) -> List[Dict]:
        """
        Получает список монет с капитализацией в ratio раз меньше Ethereum.
        
        Параметры:
            ratio (float): Во сколько раз капитализация должна быть меньше ETH.
            limit (int): Максимальное количество монет.
        
        Возвращает:
            list[dict]: Список словарей с информацией о монетах (включая капитализацию).
        """
        return self.get_coins_below_eth_cap_ratio(ratio, limit)


if __name__ == "__main__":
    """
    Тестовый запуск для проверки работы CoinGecko Fetcher.
    """
    fetcher = CoinGeckoFetcher()
    
    # Получаем список монет с капитализацией в 5 раз меньше Ethereum
    symbols = fetcher.get_filtered_symbols(ratio=5.0, limit=50)
    
    print(f"\nНайдено {len(symbols)} монет:")
    for i, symbol in enumerate(symbols[:20], 1):  # Показываем первые 20
        print(f"{i}. {symbol}")

