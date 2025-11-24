"""
Главная точка входа в приложение Trading Bot.

Консольное приложение для работы с данными криптовалют.
Загружает инструменты и таймфреймы из базы данных, получает исторические данные
из альтернативных источников и сохраняет их в БД.
"""

from loguru import logger
from gui.data_fetcher import DataFetcher
from crypto_trading_bot.trading.crypto_data_provider import CryptoDataProvider
from crypto_trading_bot.database.data_export import DataExporter
from crypto_trading_bot.trading.coin_gecko_fetcher import CoinGeckoFetcher
from crypto_trading_bot.trading.binance_symbol_checker import BinanceSymbolChecker
from crypto_trading_bot.database.models import Instrument
import pandas as pd
from tqdm import tqdm


# Маппинг таймфреймов из БД в формат провайдера данных
# Провайдер поддерживает: 1min, 3min, 5min, 15min, 30min, 1hour, 4hour, 1day, 1week
# ВАЖНО: Минутные таймфреймы (1m, 3m, 5m) критически важны для обучения ИИ модели
TIMEFRAME_MAPPING = {
    '1m': '1min',      # 1 минута - ВАЖНО для ИИ
    '3m': '3min',      # 3 минуты - ВАЖНО для ИИ (Binance API поддерживает)
    '5m': '5min',      # 5 минут - ВАЖНО для ИИ
    '15m': '15min',    # 15 минут
    '30m': '30min',    # 30 минут
    '1h': '1hour',     # 1 час
    '2h': '1hour',     # 2 часа -> используем 1hour (ближайший)
    '4h': '4hour',     # 4 часа
    '6h': '4hour',     # 6 часов -> используем 4hour (ближайший)
    '12h': '4hour',    # 12 часов -> используем 4hour (ближайший)
    '1d': '1day',      # 1 день
    '1w': '1week',     # 1 неделя
    '1mo': '1day',     # 1 месяц -> используем 1day (ближайший)
    'midw': '1week'    # midw = midweek, используем неделю
}


def print_instruments(instruments):
    """
    Выводит список инструментов в консоль.
    
    Параметры:
        instruments: Список объектов Instrument.
    """
    if not instruments:
        logger.warning("В базе данных нет инструментов")
        return
    
    logger.info(f"Загружено {len(instruments)} инструментов из БД")
    print("\n" + "=" * 60)
    print("СПИСОК ИНСТРУМЕНТОВ")
    print("=" * 60)
    print(f"{'ID':<5} {'Символ':<20}")
    print("-" * 60)
    
    for instrument in instruments:
        print(f"{instrument.id:<5} {instrument.symbol:<20}")
    
    print("=" * 60 + "\n")


def print_timeframes(timeframes):
    """
    Выводит список таймфреймов в консоль.
    
    Параметры:
        timeframes: Список объектов Timeframe.
    """
    if not timeframes:
        logger.warning("В базе данных нет таймфреймов")
        return
    
    logger.info(f"Загружено {len(timeframes)} таймфреймов из БД")
    print("\n" + "=" * 60)
    print("СПИСОК ТАЙМФРЕЙМОВ")
    print("=" * 60)
    print(f"{'ID':<5} {'Название':<20}")
    print("-" * 60)
    
    for timeframe in timeframes:
        # Используем interval_name или name
        tf_name = getattr(timeframe, 'interval_name', None) or getattr(timeframe, 'name', 'Unknown')
        print(f"{timeframe.id:<5} {tf_name:<20}")
    
    print("=" * 60 + "\n")


def print_summary(instruments, timeframes):
    """
    Выводит сводную информацию о загруженных данных.
    
    Параметры:
        instruments: Список объектов Instrument.
        timeframes: Список объектов Timeframe.
    """
    print("\n" + "=" * 60)
    print("СВОДНАЯ ИНФОРМАЦИЯ")
    print("=" * 60)
    print(f"Всего инструментов: {len(instruments)}")
    print(f"Всего таймфреймов: {len(timeframes)}")
    print("=" * 60 + "\n")


def convert_dataframe_for_db(df: pd.DataFrame) -> pd.DataFrame:
    """
    Преобразует DataFrame из CryptoDataProvider в формат для DataExporter.
    
    Параметры:
        df: DataFrame с колонками 'open', 'high', 'low', 'close', 'volume'.
    
    Возвращает:
        DataFrame с колонками 'Open', 'High', 'Low', 'Close', 'Volume'.
    """
    if df is None or df.empty:
        return df
    
    # Создаем копию DataFrame
    df_copy = df.copy()
    
    # Переименовываем колонки в формат, ожидаемый DataExporter
    column_mapping = {
        'open': 'Open',
        'high': 'High',
        'low': 'Low',
        'close': 'Close',
        'volume': 'Volume'
    }
    
    # Переименовываем только те колонки, которые есть
    df_copy = df_copy.rename(columns=column_mapping)
    
    return df_copy


def get_timeframe_period(tf_name: str, default_years: int = 2) -> int:
    """
    Определяет период загрузки данных в зависимости от таймфрейма.
    
    Для мелких таймфреймов ограничиваем период, чтобы не загружать слишком много данных.
    ВАЖНО: В режиме тестирования (limit) этот период не используется.
    
    Параметры:
        tf_name: Название таймфрейма из БД.
        default_years: Период по умолчанию в годах.
    
    Возвращает:
        float: Период в годах для загрузки данных.
    """
    # Для минутных таймфреймов ограничиваем период (только для полной загрузки)
    if tf_name in ['1m', '3m', '5m']:
        return 0.5  # 6 месяцев для очень мелких таймфреймов
    elif tf_name in ['15m', '30m']:
        return 1  # 1 год для мелких таймфреймов
    elif tf_name in ['1h', '2h']:
        return 1.5  # 1.5 года для часовых
    else:
        return default_years  # Для дневных и недельных - полный период


def load_historical_data(instruments, timeframes, years=2, limit=None):
    """
    Загружает исторические данные для всех инструментов и таймфреймов.
    
    Параметры:
        instruments: Список объектов Instrument.
        timeframes: Список объектов Timeframe.
        years: Количество лет истории для загрузки (по умолчанию 2).
              Для мелких таймфреймов период автоматически ограничивается.
        limit: Если указан, загружает только последние N свечей (для тестирования).
    """
    provider = CryptoDataProvider()
    exporter = DataExporter()
    
    # Фильтруем таймфреймы, для которых есть маппинг
    # ВАЖНО: Все таймфреймы включены, включая минутные (1m, 3m) - они нужны для обучения ИИ модели
    valid_timeframes = []
    for timeframe in timeframes:
        tf_name = getattr(timeframe, 'interval_name', None) or getattr(timeframe, 'name', 'Unknown')
        if tf_name in TIMEFRAME_MAPPING:
            valid_timeframes.append((timeframe, tf_name))
        else:
            logger.warning(f"Таймфрейм {tf_name} не поддерживается, пропускаем")
    
    total_tasks = len(instruments) * len(valid_timeframes)
    
    print("\n" + "=" * 60)
    print("ЗАГРУЗКА ИСТОРИЧЕСКИХ ДАННЫХ")
    print("=" * 60)
    print(f"Инструментов: {len(instruments)}")
    print(f"Таймфреймов: {len(valid_timeframes)} (включая минутные 1m, 3m, 5m)")
    print(f"Всего задач: {total_tasks}")
    if limit:
        print(f"РЕЖИМ ТЕСТИРОВАНИЯ: Загрузка последних {limit} свечей для каждого таймфрейма")
        print("ВАЖНО: Минутные таймфреймы включены для обучения ИИ модели")
    else:
        print(f"Период: {years} года (для мелких таймфреймов период ограничен)")
        print("\nВНИМАНИЕ: Загрузка может занять длительное время!")
        print("Для минутных таймфреймов период ограничен до 6 месяцев.")
    print("=" * 60 + "\n")
    
    success_count = 0
    error_count = 0
    
    # Используем tqdm для прогресс-бара
    # ЛОГИКА ЗАГРУЗКИ: Для каждого инструмента загружаем данные по всем таймфреймам
    # и сразу записываем в БД. Это позволяет:
    # 1. Не накапливать все данные в памяти
    # 2. Видеть прогресс по каждой задаче
    # 3. В случае ошибки не терять уже загруженные данные
    with tqdm(total=total_tasks, desc="Загрузка данных", unit="задача") as pbar:
        for instrument in instruments:
            symbol = instrument.symbol
            logger.info(f"\n{'='*60}")
            logger.info(f"Обработка инструмента: {symbol}")
            logger.info(f"{'='*60}")
            
            for timeframe, tf_name in valid_timeframes:
                try:
                    # Преобразуем таймфрейм в формат провайдера
                    provider_timeframe = TIMEFRAME_MAPPING[tf_name]
                    
                    # ШАГ 1: Получаем данные из альтернативных источников (CCXT, Binance API, yfinance)
                    if limit:
                        # Режим тестирования: загружаем только последние N свечей
                        logger.info(f"Загрузка последних {limit} свечей для {symbol} на таймфрейме {tf_name} ({provider_timeframe})...")
                        df = provider.get_recent_data(symbol, provider_timeframe, limit=limit)
                    else:
                        # Обычный режим: загружаем за период
                        period_years = get_timeframe_period(tf_name, years)
                        logger.info(f"Загрузка данных для {symbol} на таймфрейме {tf_name} ({provider_timeframe}) за период {period_years} года...")
                        df = provider.get_historical_data(symbol, provider_timeframe, years=period_years)
                    
                    if df is not None and not df.empty:
                        # ШАГ 2: Преобразуем DataFrame в формат для БД
                        df_for_db = convert_dataframe_for_db(df)
                        
                        # ШАГ 3: Сразу сохраняем в БД (таблица candles)
                        # Используем название таймфрейма из БД (колонка 'code')
                        success = exporter.insert_price_data(symbol, tf_name, df_for_db)
                        
                        if success:
                            success_count += 1
                            logger.info(f"✓ {symbol} {tf_name}: {len(df)} свечей загружено и сохранено в БД")
                        else:
                            error_count += 1
                            logger.warning(f"✗ {symbol} {tf_name}: не удалось сохранить в БД")
                    else:
                        error_count += 1
                        logger.warning(f"✗ {symbol} {tf_name}: не удалось загрузить данные")
                    
                except Exception as e:
                    error_count += 1
                    logger.error(f"✗ Ошибка при загрузке данных для {symbol} {tf_name}: {e}")
                
                # Обновляем прогресс-бар
                pbar.update(1)
    
    print("\n" + "=" * 60)
    print("РЕЗУЛЬТАТЫ ЗАГРУЗКИ")
    print("=" * 60)
    print(f"Успешно загружено: {success_count}")
    print(f"Ошибок: {error_count}")
    print(f"Всего задач: {total_tasks}")
    print("=" * 60 + "\n")


def main():
    """
    Главная функция приложения.
    
    Загружает данные из базы данных, получает исторические данные
    из альтернативных источников и сохраняет их в БД.
    """
    try:
        logger.info("Запуск приложения Trading Bot")
        print("\n" + "=" * 60)
        print("TRADING BOT - Консольное приложение")
        print("=" * 60 + "\n")
        
        # Создаем объект для получения данных
        data_fetcher = DataFetcher()
        exporter = DataExporter()
        
        # Определяем, какие инструменты использовать
        USE_MARKET_CAP_FILTER = True
        MARKET_CAP_RATIO = 5.0
        
        if USE_MARKET_CAP_FILTER:
            # Получаем список монет с капитализацией до 5 раз ниже Ethereum
            logger.info("Получение списка монет по капитализации через CoinGecko...")
            try:
                gecko_fetcher = CoinGeckoFetcher()
                filtered_symbols = gecko_fetcher.get_filtered_symbols(ratio=MARKET_CAP_RATIO, limit=100)
                
                if not filtered_symbols:
                    logger.warning("Не удалось получить список монет через CoinGecko, используем все инструменты из БД")
                    instruments = data_fetcher.get_instruments()
                else:
                    logger.info(f"Найдено {len(filtered_symbols)} монет с капитализацией <= ETH/{MARKET_CAP_RATIO}")
                    
                    # ВАЖНО: Фильтруем только те символы, что доступны на Binance
                    logger.info("Проверка доступности символов на Binance...")
                    binance_checker = BinanceSymbolChecker()
                    available_symbols = binance_checker.filter_available_symbols(filtered_symbols)
                    
                    if not available_symbols:
                        logger.warning("Нет доступных символов на Binance, используем все инструменты из БД")
                        instruments = data_fetcher.get_instruments()
                    else:
                        logger.info(f"Доступно на Binance: {len(available_symbols)} символов из {len(filtered_symbols)}")
                        
                        # Добавляем новые инструменты в БД, если их там нет
                        from crypto_trading_bot.database.db_connection import DatabaseManager
                        db = DatabaseManager()
                        
                        added_count = 0
                        for symbol in available_symbols:
                            try:
                                query = """
                                    INSERT INTO instruments (symbol)
                                    VALUES (%s)
                                    ON CONFLICT (symbol) DO NOTHING;
                                """
                                db.execute_query(query, (symbol,))
                                db.connection.commit()
                                added_count += 1
                            except Exception as e:
                                logger.warning(f"Не удалось добавить инструмент {symbol}: {e}")
                        
                        db.close()
                        
                        if added_count > 0:
                            logger.info(f"Добавлено {added_count} новых инструментов в БД")
                        
                        # Получаем инструменты из БД (включая только что добавленные)
                        all_instruments = data_fetcher.get_instruments()
                        
                        # Фильтруем только те, что доступны на Binance
                        instruments = [
                            inst for inst in all_instruments 
                            if inst.symbol in available_symbols
                        ]
                        
                        logger.info(f"Используем {len(instruments)} инструментов (доступны на Binance)")
                    
            except Exception as e:
                logger.error(f"Ошибка при получении списка монет через CoinGecko: {e}")
                logger.info("Используем все инструменты из БД")
                instruments = data_fetcher.get_instruments()
        else:
            # Используем все инструменты из БД
            logger.info("Загрузка инструментов из базы данных...")
            instruments = data_fetcher.get_instruments()
        
        print_instruments(instruments)
        
        # Загружаем таймфреймы из БД
        logger.info("Загрузка таймфреймов из базы данных...")
        timeframes = data_fetcher.get_timeframes()
        print_timeframes(timeframes)
        
        # Выводим сводную информацию
        print_summary(instruments, timeframes)
        
        # Запускаем GUI приложение
        # Фоновое обновление данных будет запущено автоматически в приложении
        print("\n" + "=" * 60)
        print("ЗАПУСК GUI ПРИЛОЖЕНИЯ")
        print("=" * 60)
        print("Приложение запускается...")
        print("Фоновое обновление данных будет запущено автоматически")
        print("=" * 60 + "\n")
        
        from gui.tradingview_app import main as gui_main
        gui_main()
        
    except Exception as e:
        logger.error(f"Ошибка при выполнении приложения: {e}")
        print(f"\nОШИБКА: {e}\n")
        raise


if __name__ == "__main__":
    main()
