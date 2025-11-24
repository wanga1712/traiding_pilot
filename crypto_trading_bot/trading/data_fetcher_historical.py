import pytz
from datetime import datetime
import time
from prettytable import PrettyTable
from tqdm import tqdm  # Импортируем tqdm для прогресс-бара
from loguru import logger

from crypto_trading_bot.trading.exchange_connection import HuobiConnector
from crypto_trading_bot.config.config import CONFIG
from crypto_trading_bot.database.data_import import DataImport  # Импортируем класс для получения данных из БД
from crypto_trading_bot.database.data_export import DataExporter

class HuobiHistoricalData(HuobiConnector):
    def __init__(self):
        super().__init__()

        self.data_import = DataImport()  # Создаем объект для работы с DataImport
        self.trade_symbols = self.data_import.get_instruments()  # Получаем символы из DataImport
        self.timeframes = self.data_import.get_timeframes()  # Получаем таймфреймы из DataImport

        # Параметры для контроля лимита запросов
        self.max_requests_per_interval = 500  # Максимальное количество запросов за интервал
        self.interval_seconds = 180  # Интервал в секундах (3 минуты)
        self.request_count = 0  # Счётчик запросов для текущего интервала

    def get_historical_data(self, symbol, period, max_batches=10):
        """
        Получает исторические данные по торговым свечам для заданного инструмента партиями.

        Параметры:
        symbol (str): Символ торгового инструмента (например, 'btcusdt').
        period (str): Период времени для свечей (например, '1min', '5min', '1hour').
        max_batches (int): Максимальное количество партий данных, которые нужно загрузить (по умолчанию 10).

        Возвращает:
        list: Список данных о свечах, объединённый из всех партий.
        """
        try:
            all_data = []  # Список для хранения всех данных
            current_end = None  # Текущая точка окончания для API-запроса

            for batch in range(max_batches):
                # Формируем параметры запроса для API
                params = {
                    'symbol': symbol,  # Символ торгового инструмента
                    'period': period,  # Период времени для свечей
                    'size': 2000,  # Запрашиваем максимум данных за один запрос
                }

                # Если текущая точка окончания задана, добавляем её в параметры
                if current_end:
                    params['to'] = current_end

                # Путь для запроса к API
                path = '/market/history/kline'
                params['path'] = path  # Добавляем путь в параметры для подписи запроса

                # Логируем параметры запроса перед отправкой
                # logger.info(f"Запрос к API с параметрами: {params}")

                # Выполняем запрос к API через родительский метод _get
                response = self._get(path, params)

                # Проверяем, успешен ли запрос
                if not response or response.get('status') != 'ok':
                    logger.warning(
                        f"Ошибка при получении данных для символа {symbol} и периода {period}. Ответ: {response}")
                    break

                # Извлекаем данные из ответа
                data = response.get('data', [])
                if not data:
                    logger.info(f"Данных больше нет для символа {symbol} и периода {period}.")
                    break

                # Добавляем текущую партию данных в общий список
                all_data.extend(data)

                # Логируем успешную загрузку данных
                # logger.info(f"Загружено {len(data)} записей для символа {symbol} и периода {period}.")

                # Обновляем текущую точку окончания для следующей партии
                current_end = data[-1]['id']  # Берём ID последней свечи

                # Если данных меньше 2000, мы достигли конца истории
                if len(data) < 2000:
                    logger.info(f"Достигнут конец данных для символа {symbol} и периода {period}.")
                    break

            # Возвращаем все данные, объединённые из партий
            return all_data

        except Exception as e:
            # Логируем сообщение об ошибке
            logger.error(f"Ошибка при получении исторических данных: {e}")
            return []  # Возвращаем пустой список в случае ошибки

    def display_data(self, data, symbol):
        """
        Отображает данные о свечах в виде таблицы.

        Параметры:
        data (list): Список данных о свечах, полученных из API. Каждый элемент списка должен быть словарем с данными о свече (например, время, цена открытия, цена закрытия и т.д.).
        symbol (str): Символ торгового инструмента (например, 'btcusdt').

        Описание:
        Метод преобразует данные о свечах в удобочитаемый формат и выводит их в виде таблицы с указанием времени, цен и объема торгов.
        """
        if not data:
            # Если данных нет, выводим предупреждение и завершаем выполнение метода
            logger.warning(f"Нет данных для символа: {symbol}")
            return

        # Получаем локальный часовой пояс из конфигурации (например, для Москвы или другого города)
        local_tz = pytz.timezone(CONFIG['TRADE']['TIMEZONE'])

        # Создаем таблицу с использованием PrettyTable
        table = PrettyTable()
        table.field_names = ["Символ", "Дата и время", "Минимальная цена", "Максимальная цена",
                             "Цена открытия", "Цена закрытия", "Объем торгов", "Число сделок"]

        # Заполнение таблицы данными из полученного списка
        for tick in data:
            # Преобразуем время из Unix timestamp (время в секундах с 1970 года) в локальное время
            utc_time = datetime.utcfromtimestamp(tick['id']).replace(tzinfo=pytz.utc)
            local_time = utc_time.astimezone(local_tz).strftime(
                '%Y-%m-%d %H:%M:%S')  # Преобразуем в формат 'ГГГГ-ММ-ДД ЧЧ:ММ:СС'

            # Извлекаем информацию о свечах
            low = tick['low']  # Минимальная цена за период
            high = tick['high']  # Максимальная цена за период
            open_price = tick['open']  # Цена открытия
            close = tick['close']  # Цена закрытия
            volume = tick['vol']  # Объем торгов
            amount = tick['amount']  # Число сделок (или другое количество)

            # Добавляем строку в таблицу
            table.add_row([symbol, local_time, low, high, open_price, close, volume, amount])

        # Выводим таблицу на экран
        print(table)

    def fetch_and_store_data_with_progress(self):
        """
        Получает данные по всем символам и таймфреймам, а затем добавляет их в базу данных с прогресс-баром.

        Описание:
        - Метод использует символы и таймфреймы из базы данных.
        - Получает данные через API партиями (максимум 2000 записей за запрос).
        - Добавляет их в базу данных через `DataExporter`.
        - Визуализирует прогресс выполнения с помощью `tqdm`.
        """
        # Создаем объект DataExporter для записи данных в базу
        data_exporter = DataExporter()

        # Считаем общее количество комбинаций символов и таймфреймов
        total_tasks = len(self.trade_symbols) * len(self.timeframes)

        # Инициализируем прогресс-бар
        with tqdm(total=total_tasks, desc="Загрузка и сохранение данных", unit="комбинация") as pbar:
            # Перебираем символы
            for symbol_id, symbol in self.trade_symbols:
                # Перебираем таймфреймы
                for timeframe_id, timeframe in self.timeframes:
                    # Получение данных через API (вся история будет получена партиями)
                    historical_data = self.get_historical_data(
                        symbol=symbol,
                        period=timeframe
                    )

                    if not historical_data:
                        logger.warning(f"Нет данных для символа {symbol} и таймфрейма {timeframe}")
                        continue  # Переход к следующей комбинации символа и таймфрейма

                    # Сохранение данных в базу через DataExporter
                    data_exporter.insert_price_data(symbol, timeframe, historical_data)

                    # Обновляем прогресс-бар
                    pbar.update(1)


    def get_available_instruments(self):
        """
        Получает список доступных торговых инструментов (пар).
        """
        try:
            path = "/v1/common/currencys"  # Эндпоинт для получения доступных валют
            params = {'path': path}  # Передаем параметр path для подписи
            response = self._get(path, params)

            if response and 'data' in response:
                instruments = response['data']
                logger.info(f"Доступные инструменты: {instruments}")

                # Формируем список торговых пар, добавляя 'usdt' к каждому инструменту
                trading_pairs = [f"{instrument}usdt" for instrument in instruments]
                logger.info(f"Торговые пары с USDT: {trading_pairs}")
                return trading_pairs
            else:
                logger.warning("Не удалось получить список доступных инструментов.")
                return []

        except Exception as e:
            logger.error(f"Ошибка при получении списка инструментов: {e}")
            return []

    def get_24h_trade_volume(self, symbol):
        """
        Получает объем торгов за последние 24 часа для конкретного символа.
        """
        try:
            path = "/market/detail/merged"  # Эндпоинт для получения данных о торговле
            params = {
                'symbol': symbol,
            }
            params['path'] = path
            response = self._get(path, params)

            if response and 'tick' in response:
                volume = response['tick']['vol']  # Получаем объем торгов
                return volume
            else:
                return 0
        except Exception as e:
            return 0  # Просто возвращаем 0, если произошла ошибка, без вывода

    def filter_instruments_by_volume(self, instruments, min_volume):
        """
        Фильтрует инструменты по минимальному объему торгов за 24 часа.
        """
        filtered_instruments = []

        # Используем tqdm для прогресс-бара
        for symbol in tqdm(instruments, desc="Фильтрация инструментов", unit="пар", ncols=100):
            volume = self.get_24h_trade_volume(symbol)
            if volume >= min_volume:
                filtered_instruments.append(symbol)

        return filtered_instruments

    def get_filtered_instruments(self, min_volume=1000000):
        """
        Получаем список всех инструментов, отфильтрованных по минимальному объему торгов за 24 часа.
        """
        instruments = CONFIG['TRADE']['SYMBOLS']  # Список инструментов из конфигурации

        # Фильтруем инструменты по объему, используя прогресс-бар
        filtered_instruments = self.filter_instruments_by_volume(instruments, min_volume)

        # Формируем итоговый список, отфильтрованный по объему
        return filtered_instruments


# Запуск программы
if __name__ == "__main__":
    # Создаем объект класса и получаем/выводим данные
    huobi_historical = HuobiHistoricalData()
    # Получение данных с биржи по API и внесение их в БД
    huobi_historical.fetch_and_store_data_with_progress()

    # huobi_historical.fetch_and_display_data()
    # huobi_historical.get_available_instruments()

    # # Получаем отфильтрованный список инструментов с объемом > 1 млн USD
    # filtered_instruments = huobi_historical.get_filtered_instruments(min_volume=1000000)
    #
    # # Выводим отфильтрованный список торговых пар
    # logger.info(f"Отфильтрованные инструменты: {filtered_instruments}")