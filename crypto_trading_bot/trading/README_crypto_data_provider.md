# Модуль получения исторических данных криптовалют

## Описание

Модуль `crypto_data_provider.py` предоставляет универсальный интерфейс для получения исторических данных криптовалют (OHLCV) из нескольких бесплатных источников, доступных из России.

## Поддерживаемые источники данных

1. **CCXT (Binance)** — универсальная библиотека для работы с криптобиржами
   - Работает из России
   - Поддерживает все основные таймфреймы
   - Период до 2 лет

2. **Binance API** — прямой доступ к публичному API Binance
   - Бесплатный публичный API
   - Работает из России (если не заблокирован)
   - Максимум 1000 свечей за запрос

3. **yfinance (Yahoo Finance)** — альтернативный источник данных
   - Бесплатный
   - Работает из России
   - Ограничения по таймфреймам (для минутных — максимум 7 дней)

## Установка зависимостей

```bash
pip install ccxt yfinance requests pandas
```

Или установите все зависимости проекта:

```bash
pip install -r requirements.txt
```

## Быстрый старт

### Пример 1: Получение данных для одной криптовалюты

```python
from crypto_trading_bot.trading.crypto_data_provider import CryptoDataProvider
from loguru import logger

# Создаем провайдер данных
provider = CryptoDataProvider()

# Получаем данные для BTC за последние 2 года на дневном таймфрейме
symbol = 'BTCUSDT'
timeframe = '1day'

df = provider.get_historical_data(symbol, timeframe, years=2)

if df is not None:
    logger.info(f"Загружено {len(df)} свечей")
    logger.info(f"\nПервые 5 строк:\n{df.head()}")
else:
    logger.error("Не удалось загрузить данные")
```

### Пример 2: Построение свечного графика

```python
from crypto_trading_bot.trading.crypto_data_provider import CryptoDataProvider
import mplfinance as mpf

provider = CryptoDataProvider()

# Получаем данные специально для свечного графика
df = provider.get_data_for_candlestick_chart('BTCUSDT', '1day', years=2)

if df is not None:
    # Строим свечной график
    mpf.plot(
        df,
        type='candle',
        style='charles',
        title='BTCUSDT - Свечной график',
        volume=True,
        mav=(20, 50),  # Скользящие средние
        savefig='btcusdt_candlestick.png'
    )
```

### Пример 3: Получение данных для нескольких криптовалют

```python
from crypto_trading_bot.trading.crypto_data_provider import CryptoDataProvider

provider = CryptoDataProvider()

symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT']
timeframe = '1day'

results = {}
for symbol in symbols:
    df = provider.get_historical_data(symbol, timeframe, years=2)
    if df is not None:
        results[symbol] = df
        print(f"{symbol}: {len(df)} свечей загружено")
```

### Пример 4: Разные таймфреймы

```python
from crypto_trading_bot.trading.crypto_data_provider import CryptoDataProvider

provider = CryptoDataProvider()

symbol = 'BTCUSDT'
timeframes = ['1day', '4hour', '1hour']

for timeframe in timeframes:
    df = provider.get_historical_data(symbol, timeframe, years=1)
    if df is not None:
        print(f"{timeframe}: {len(df)} свечей")
```

## Поддерживаемые символы

По умолчанию поддерживаются:
- BTCUSDT (Bitcoin)
- ETHUSDT (Ethereum)
- BNBUSDT (Binance Coin)
- ADAUSDT (Cardano)
- SOLUSDT (Solana)
- XRPUSDT (Ripple)

Для других символов модуль автоматически преобразует формат (например, `BTCUSDT` → `BTC/USDT` для CCXT).

## Поддерживаемые таймфреймы

- `1min` — 1 минута
- `5min` — 5 минут
- `15min` — 15 минут
- `30min` — 30 минут
- `1hour` — 1 час
- `4hour` — 4 часа
- `1day` — 1 день
- `1week` — 1 неделя

## Формат данных

Модуль возвращает `pandas.DataFrame` со следующими колонками:

- `timestamp` — индекс (datetime)
- `open` — цена открытия
- `high` — максимальная цена
- `low` — минимальная цена
- `close` — цена закрытия
- `volume` — объем торгов
- `trades` — количество сделок (если доступно)

## Автоматический fallback

Модуль автоматически пробует загрузить данные из разных источников по очереди:

1. Сначала пробует CCXT (Binance)
2. Если не получилось — пробует Binance API напрямую
3. Если не получилось — пробует yfinance

Это обеспечивает максимальную надежность получения данных.

## Ограничения

- **yfinance**: Для минутных таймфреймов (1m, 5m, 15m, 30m) максимальный период — 7 дней
- **Binance API**: Максимум 1000 свечей за один запрос (модуль автоматически делает несколько запросов)
- **CCXT**: Зависит от лимитов биржи (обычно 1000 свечей за запрос)

## Интеграция с базой данных

Данные можно сохранить в базу данных через `DataExporter`:

```python
from crypto_trading_bot.trading.crypto_data_provider import CryptoDataProvider
from crypto_trading_bot.database.data_export import DataExporter

provider = CryptoDataProvider()
exporter = DataExporter()

# Получаем данные
df = provider.get_historical_data('BTCUSDT', '1day', years=2)

# Сохраняем в БД
if df is not None:
    # Преобразуем DataFrame в формат для DataExporter
    data_list = []
    for idx, row in df.iterrows():
        data_list.append({
            'id': int(idx.timestamp() * 1000),  # timestamp в миллисекундах
            'open': row['open'],
            'high': row['high'],
            'low': row['low'],
            'close': row['close'],
            'vol': row['volume'],
            'amount': row.get('trades', 0)
        })
    
    exporter.insert_price_data('BTCUSDT', '1day', data_list)
```

## Примеры использования

См. файл `example_crypto_data_usage.py` для подробных примеров использования модуля.

## Примечания

- Все источники данных бесплатные и не требуют API ключей для получения исторических данных
- Модуль автоматически соблюдает rate limits источников данных
- Данные возвращаются в едином формате независимо от источника
- Модуль логирует все операции через loguru

## Поддержка

При возникновении проблем проверьте:
1. Установлены ли все зависимости (`ccxt`, `yfinance`, `requests`, `pandas`)
2. Доступен ли интернет
3. Не заблокированы ли источники данных в вашем регионе

