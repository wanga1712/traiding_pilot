"""
Модуль для получения данных по топ-30 криптовалютам по капитализации.

Получает список топовых монет с биржи Huobi и загружает их данные в базу данных.
"""
from loguru import logger
from typing import List, Dict
from huobi.client.generic import GenericClient
from huobi.client.market import MarketClient
from crypto_trading_bot.trading.exchange_connection import HuobiConnector
from crypto_trading_bot.database.data_export import DataExport
from crypto_trading_bot.database.data_import import DataImport


class TopCoinsFetcher(HuobiConnector):
    """
    Класс для получения данных по топ-30 криптовалютам.
    
    Получает список монет по капитализации/объему торгов и загружает
    их исторические данные в базу данных.
    """
    
    def __init__(self):
        """
        Инициализация класса для получения топ-30 монет.
        """
        super().__init__()
        self.generic_client = GenericClient()
        self.market_client = MarketClient()
        self.data_export = DataExport()
        self.data_import = DataImport()
        self.top_coins_count = 30
    
    def get_top_coins_by_volume(self, limit: int = 30) -> List[Dict]:
        """
        Получает топ монет по объему торгов за 24 часа.
        
        Параметры:
            limit (int): Количество монет для получения (по умолчанию 30).
        
        Возвращает:
            list[dict]: Список словарей с информацией о монетах.
                Каждый словарь содержит: symbol, volume, price_change
        """
        try:
            logger.info(f"Получение топ-{limit} монет по объему торгов...")
            
            # Получаем все торговые пары
            symbols = self.generic_client.get_exchange_symbols()
            
            if not symbols:
                logger.error("Не удалось получить список торговых пар")
                return []
            
            # Фильтруем только USDT пары
            usdt_pairs = [s for s in symbols if s.quote_currency.lower() == 'usdt' and s.state == 'online']
            
            logger.info(f"Найдено {len(usdt_pairs)} активных USDT пар")
            
            # Получаем данные по объему для каждой пары
            coins_data = []
            for symbol_obj in usdt_pairs:
                try:
                    symbol = symbol_obj.symbol.lower()
                    
                    # Получаем 24h статистику
                    ticker = self.market_client.get_market_ticker_24h(symbol)
                    
                    if ticker and ticker.vol:
                        coins_data.append({
                            'symbol': symbol,
                            'volume': float(ticker.vol),
                            'price': float(ticker.close),
                            'price_change': float(ticker.close) - float(ticker.open),
                            'price_change_percent': ((float(ticker.close) - float(ticker.open)) / float(ticker.open)) * 100 if float(ticker.open) > 0 else 0
                        })
                except Exception as e:
                    logger.warning(f"Ошибка при получении данных для {symbol_obj.symbol}: {e}")
                    continue
            
            # Сортируем по объему и берем топ
            coins_data.sort(key=lambda x: x['volume'], reverse=True)
            top_coins = coins_data[:limit]
            
            logger.info(f"Получено {len(top_coins)} топовых монет")
            for i, coin in enumerate(top_coins, 1):
                logger.info(f"{i}. {coin['symbol']} - объем: ${coin['volume']:,.0f}")
            
            return top_coins
            
        except Exception as e:
            logger.error(f"Ошибка при получении топ-монет: {e}")
            return []
    
    def get_top_coins_by_market_cap(self, limit: int = 30) -> List[str]:
        """
        Получает топ монет по рыночной капитализации.
        
        Примечание: Huobi API не предоставляет данные о капитализации напрямую,
        поэтому используем альтернативный метод - сортировку по объему торгов.
        
        Параметры:
            limit (int): Количество монет для получения.
        
        Возвращает:
            list[str]: Список символов топ-монет.
        """
        top_coins = self.get_top_coins_by_volume(limit)
        return [coin['symbol'] for coin in top_coins]
    
    def fetch_and_store_top_coins_data(self, timeframes: List[str] = None):
        """
        Получает данные по топ-монетам и сохраняет их в базу данных.
        
        Параметры:
            timeframes (list[str], optional): Список таймфреймов для загрузки.
                По умолчанию: ['1day', '4hour', '1hour', '15min']
        """
        if timeframes is None:
            timeframes = ['1day', '4hour', '1hour', '15min']
        
        try:
            logger.info("Начало загрузки данных по топ-30 монетам...")
            
            # Получаем топ-30 монет
            top_coins = self.get_top_coins_by_volume(self.top_coins_count)
            
            if not top_coins:
                logger.error("Не удалось получить список топ-монет")
                return
            
            symbols = [coin['symbol'] for coin in top_coins]
            
            logger.info(f"Начинаем загрузку данных для {len(symbols)} монет...")
            
            # Для каждой монеты загружаем данные по всем таймфреймам
            from crypto_trading_bot.trading.data_fetcher_historical import HuobiHistoricalData
            historical_fetcher = HuobiHistoricalData()
            
            for symbol in symbols:
                logger.info(f"Загрузка данных для {symbol}...")
                
                for timeframe in timeframes:
                    try:
                        # Получаем исторические данные
                        historical_fetcher.fetch_and_store_symbol_data(
                            symbol=symbol,
                            timeframe=timeframe,
                            days_back=365  # Загружаем данные за год
                        )
                        logger.info(f"Данные для {symbol} на {timeframe} загружены")
                    except Exception as e:
                        logger.error(f"Ошибка при загрузке данных для {symbol} на {timeframe}: {e}")
                        continue
            
            logger.info("Загрузка данных по топ-30 монетам завершена")
            
        except Exception as e:
            logger.error(f"Ошибка при загрузке данных по топ-монетам: {e}")
            raise
    
    def update_top_coins_list(self):
        """
        Обновляет список топ-монет в базе данных.
        
        Проверяет текущий список топ-монет и обновляет его при необходимости.
        """
        try:
            logger.info("Обновление списка топ-монет...")
            
            # Получаем текущий список топ-монет
            current_top = self.get_top_coins_by_volume(self.top_coins_count)
            
            # Получаем список инструментов из БД
            db_instruments = self.data_import.get_instruments()
            db_symbols = {inst.symbol.lower() for inst in db_instruments}
            
            # Проверяем, какие монеты нужно добавить
            new_symbols = []
            for coin in current_top:
                symbol = coin['symbol']
                if symbol not in db_symbols:
                    new_symbols.append(symbol)
                    logger.info(f"Новая монета для добавления: {symbol}")
            
            # Добавляем новые монеты в БД
            if new_symbols:
                logger.info(f"Добавление {len(new_symbols)} новых монет в базу данных...")
                # TODO: Реализовать добавление новых инструментов через DataExport
                # self.data_export.add_instruments(new_symbols)
            
            logger.info("Список топ-монет обновлен")
            
        except Exception as e:
            logger.error(f"Ошибка при обновлении списка топ-монет: {e}")
            raise


if __name__ == "__main__":
    """
    Тестовый запуск для получения топ-30 монет.
    """
    fetcher = TopCoinsFetcher()
    
    # Получаем топ-30 монет
    top_coins = fetcher.get_top_coins_by_volume(30)
    
    print("\n=== ТОП-30 МОНЕТ ПО ОБЪЕМУ ТОРГОВ ===")
    for i, coin in enumerate(top_coins, 1):
        print(f"{i:2d}. {coin['symbol']:12s} | "
              f"Объем: ${coin['volume']:>15,.0f} | "
              f"Цена: ${coin['price']:>12,.2f} | "
              f"Изменение: {coin['price_change_percent']:>6.2f}%")

