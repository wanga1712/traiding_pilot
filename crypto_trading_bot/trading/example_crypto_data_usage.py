"""
Пример использования модуля crypto_data_provider для получения исторических данных криптовалют.

Этот скрипт демонстрирует, как получить данные OHLCV для построения свечных графиков.
"""

from crypto_trading_bot.trading.crypto_data_provider import CryptoDataProvider
from loguru import logger
import matplotlib.pyplot as plt
import mplfinance as mpf

def example_get_data():
    """
    Пример получения исторических данных для криптовалюты.
    """
    # Создаем провайдер данных
    provider = CryptoDataProvider()
    
    # Получаем данные для BTC за последние 2 года на дневном таймфрейме
    symbol = 'BTCUSDT'
    timeframe = '1day'
    
    logger.info(f"Загрузка данных для {symbol} на таймфрейме {timeframe}...")
    
    df = provider.get_historical_data(symbol, timeframe, years=2)
    
    if df is not None:
        logger.info(f"Успешно загружено {len(df)} свечей")
        logger.info(f"\nПервые 5 строк:\n{df.head()}")
        logger.info(f"\nПоследние 5 строк:\n{df.tail()}")
        
        # Выводим статистику
        logger.info(f"\nСтатистика по ценам:\n{df[['open', 'high', 'low', 'close']].describe()}")
        
        return df
    else:
        logger.error("Не удалось загрузить данные")
        return None


def example_candlestick_chart():
    """
    Пример построения свечного графика из полученных данных.
    """
    provider = CryptoDataProvider()
    
    # Получаем данные специально для свечного графика
    symbol = 'BTCUSDT'
    timeframe = '1day'
    
    logger.info(f"Получение данных для свечного графика {symbol}...")
    
    df = provider.get_data_for_candlestick_chart(symbol, timeframe, years=2)
    
    if df is not None and not df.empty:
        # Строим свечной график с помощью mplfinance
        mpf.plot(
            df,
            type='candle',
            style='charles',
            title=f'{symbol} - Свечной график ({timeframe})',
            volume=True,
            mav=(20, 50),  # Скользящие средние
            savefig=f'{symbol}_{timeframe}_candlestick.png'
        )
        
        logger.info(f"График сохранен в файл {symbol}_{timeframe}_candlestick.png")
    else:
        logger.error("Не удалось получить данные для графика")


def example_multiple_symbols():
    """
    Пример получения данных для нескольких криптовалют.
    """
    provider = CryptoDataProvider()
    
    symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT']
    timeframe = '1day'
    
    results = {}
    
    for symbol in symbols:
        logger.info(f"Загрузка данных для {symbol}...")
        df = provider.get_historical_data(symbol, timeframe, years=2)
        
        if df is not None:
            results[symbol] = df
            logger.info(f"✓ {symbol}: {len(df)} свечей загружено")
        else:
            logger.warning(f"✗ {symbol}: не удалось загрузить данные")
    
    return results


def example_different_timeframes():
    """
    Пример получения данных на разных таймфреймах.
    """
    provider = CryptoDataProvider()
    
    symbol = 'BTCUSDT'
    timeframes = ['1day', '4hour', '1hour']
    
    results = {}
    
    for timeframe in timeframes:
        logger.info(f"Загрузка данных для {symbol} на таймфрейме {timeframe}...")
        df = provider.get_historical_data(symbol, timeframe, years=1)  # 1 год для меньших таймфреймов
        
        if df is not None:
            results[timeframe] = df
            logger.info(f"✓ {timeframe}: {len(df)} свечей загружено")
        else:
            logger.warning(f"✗ {timeframe}: не удалось загрузить данные")
    
    return results


if __name__ == "__main__":
    """
    Запуск примеров использования.
    """
    logger.info("=== Пример 1: Получение данных для одной криптовалюты ===")
    df = example_get_data()
    
    logger.info("\n=== Пример 2: Построение свечного графика ===")
    example_candlestick_chart()
    
    logger.info("\n=== Пример 3: Получение данных для нескольких криптовалют ===")
    results = example_multiple_symbols()
    
    logger.info("\n=== Пример 4: Получение данных на разных таймфреймах ===")
    timeframe_results = example_different_timeframes()

