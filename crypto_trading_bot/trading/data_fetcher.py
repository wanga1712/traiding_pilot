from loguru import logger
import datetime
import pytz
import time
import json
from prettytable import PrettyTable

from crypto_trading_bot.trading.exchange_connection import HuobiConnector
from crypto_trading_bot.config.config import CONFIG


class HuobiMarketData(HuobiConnector):
    def __init__(self):
        super().__init__()  # Вызываем родительский класс для инициализации API ключей и URL
        self.trade_symbols = CONFIG['TRADE']['SYMBOLS']
        self.start_date = CONFIG['TRADE']['START_DATE']
        self.timeframes = CONFIG['TRADE']['TIMEFRAMES']

    def get_market_data(self, symbol: str):
        """Получение рыночных данных для указанного символа (например, BTC-USDT)."""
        try:
            # Параметры запроса
            params = {
                'symbol': symbol  # Передаем символ для получения данных
            }

            # Убедитесь, что добавлен 'path' для подписи
            path = '/market/detail'
            params['path'] = path  # Добавляем 'path' в параметры для подписи

            # Получаем данные через родительский метод _get
            response_data = self._get(path, params)

            if response_data:
                # Проверка наличия ключа 'tick' в ответе
                if 'tick' in response_data:
                    tick = response_data['tick']

                    # Преобразуем timestamp в UTC
                    timestamp = response_data['ts']
                    utc_time = datetime.datetime.utcfromtimestamp(timestamp / 1000)  # Преобразуем в UTC

                    # Переводим в локальное время (например, Московское время)
                    local_timezone = pytz.timezone('Europe/Moscow')  # Установите ваш часовой пояс
                    local_time = utc_time.replace(tzinfo=pytz.utc).astimezone(local_timezone)

                    # Извлекаем данные из 'tick'
                    low = tick['low']
                    high = tick['high']
                    open_price = tick['open']
                    close = tick['close']
                    volume = tick['vol']
                    amount = tick['amount']

                    # Создание таблицы для вывода
                    table = PrettyTable()

                    # Определяем поля таблицы
                    table.field_names = ["Символ", "Дата и время", "Минимальная цена", "Максимальная цена",
                                         "Цена открытия",
                                         "Цена закрытия", "Объем торгов", "Число сделок"]

                    # Добавляем данные в таблицу
                    table.add_row([symbol, local_time, low, high, open_price, close, volume, amount])

                    # Выводим таблицу в консоль
                    print(table)

                else:
                    logger.warning(f"Отсутствуют данные 'tick' для {symbol}")
            else:
                logger.warning(f"Данные для {symbol} не получены.")
        except Exception as e:
            logger.error(f"Ошибка при получении рыночных данных для {symbol}: {e}")

    def get_all_market_data(self):
        """Получение рыночных данных для нескольких инструментов (например, BTC-USDT, ETH-USDT)."""
        for symbol in self.trade_symbols:
            self.get_market_data(symbol)

    def get_order_book_with_averaging(self, symbol: str, depth_type: str = 'step0', price_step: float = 10):
        """Получение данных стакана с усреднением для указанного символа."""
        try:
            logger.info(f"Запрос данных стакана для символа: {symbol}")

            # Параметры запроса
            params = {
                'symbol': symbol,
                'type': depth_type  # Указываем тип стакана (например, 'step0', 'step1')
            }

            # Путь запроса
            path = '/market/depth'
            params['path'] = path  # Добавляем путь в параметры для подписи

            # Получаем данные через родительский метод _get
            response_data = self._get(path, params)

            if response_data and 'tick' in response_data:
                tick = response_data['tick']

                # Извлекаем данные о глубине стакана
                bids = tick.get('bids', [])  # Заявки на покупку
                asks = tick.get('asks', [])  # Заявки на продажу

                # Функция для группировки данных по ценовым уровням
                def group_orders(orders, step):
                    grouped = {}
                    for price, qty in orders:
                        # Определяем диапазон, к которому относится цена
                        rounded_price = round(price / step) * step
                        if rounded_price not in grouped:
                            grouped[rounded_price] = 0
                        grouped[rounded_price] += qty
                    return grouped

                # Группируем заявки
                grouped_bids = group_orders(bids, price_step)
                grouped_asks = group_orders(asks, price_step)

                # Получаем текущее время (в UTC)
                utc_now = datetime.datetime.utcnow()

                # Переводим в локальное время (например, Московское)
                local_timezone = pytz.timezone('Europe/Moscow')
                local_time = utc_now.replace(tzinfo=pytz.utc).astimezone(local_timezone)

                # Приводим дату и время в читаемый формат
                date_str = local_time.strftime('%Y-%m-%d')
                time_str = local_time.strftime('%H:%M:%S')

                # Создаем таблицу для вывода стакана
                table = PrettyTable()
                table.field_names = ["Дата", "Время", "Цена (Покупка)", "Объем (Покупка)", "Цена (Продажа)",
                                     "Объем (Продажа)"]

                # Сортируем уровни цен
                bid_levels = sorted(grouped_bids.items(), key=lambda x: x[0], reverse=True)
                ask_levels = sorted(grouped_asks.items(), key=lambda x: x[0])

                # Максимальное количество строк для вывода
                max_rows = max(len(bid_levels), len(ask_levels))

                # Объединяем bids и asks в строки
                for i in range(max_rows):
                    bid_price, bid_qty = bid_levels[i] if i < len(bid_levels) else ("-", "-")
                    ask_price, ask_qty = ask_levels[i] if i < len(ask_levels) else ("-", "-")
                    table.add_row([date_str, time_str, bid_price, bid_qty, ask_price, ask_qty])

                # Выводим данные о стакане
                logger.info(f"Получены данные стакана для {symbol} (с усреднением, шаг {price_step}):")
                logger.info(f"\n{table}")

            else:
                logger.warning(f"Данные стакана для {symbol} не получены.")
        except Exception as e:
            logger.error(f"Ошибка при получении данных стакана для {symbol}: {e}")

    def get_all_order_books(self):
        """Получение данных стаканов для нескольких инструментов (например, BTC-USDT, ETH-USDT)."""
        for symbol in self.trade_symbols:
            logger.info(f"Запуск получения стакана для {symbol}")
            self.get_order_book_with_averaging(symbol)


    def get_current_price(self):
        """Получение текущей цены инструмента"""
        try:
            prices = {}
            for symbol in self.trade_symbols:
                path = '/market/detail/merged'  # Путь для текущей цены
                params = {
                    'symbol': symbol,  # Инструмент (например, btcusdt)
                    'Timestamp': int(time.time()),  # Используем UNIX-время
                    'path': path  # Добавляем 'path' для генерации подписи
                }
                response = self._get(path, params)
                price = response['tick']['close'] if 'tick' in response else None
                prices[symbol] = price  # Сохраняем цену для каждого инструмента
                logger.info(f"Текущая цена для инструмента {symbol} = {price}")

            return prices  # Возвращаем словарь с ценами для всех инструментов
        except Exception as e:
            logger.error(f"Error fetching current price: {e}")
            raise


if __name__ == "__main__":
    # # Пример параметров
    # trade_symbols = ['btcusdt', 'ethusdt']
    # timeframes = ['1m', '10m', '1d']
    # start_date = time.strptime('2024-01-01', '%Y-%m-%d')  # Примерная дата начала

    # Создаем объект класса и получаем данные
    market_data_fetcher = HuobiMarketData()

    # Получаем данные для одного инструмента
    # market_data_fetcher.get_market_data('ethusdt')

    # Получаем данные для нескольких символов
    market_data_fetcher.get_all_market_data()

    # Получаем данные для стакана
    market_data_fetcher.get_all_order_books()

    # # Получаем текущие цены
    # market_data_fetcher.get_current_price()
    #
    # # Собираем данные для всех инструментов и таймфреймов
    # market_data_fetcher.collect_data()
