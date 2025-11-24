from loguru import logger

from crypto_trading_bot.database.db_connection import DatabaseManager

class DataImport:
    """
    Класс для импорта данных в базу данных и получения информации из нее.
    """

    def __init__(self):
        """
        Инициализация класса для работы с базой данных.

        :param db_manager: Объект DatabaseManager для выполнения операций с базой данных.
        """
        self.db_manager = DatabaseManager()

    def get_instruments(self):
        """
        Получает все инструменты из таблицы instruments.
        """
        try:
            # logger.info(
            #     f"Подключение к базе данных с хостом {self.db_manager.db_host}, базой {self.db_manager.db_name}")
            query = "SELECT id, symbol FROM instruments;"
            self.db_manager.cursor.execute(query)
            instruments = self.db_manager.cursor.fetchall()

            # logger.info(f"Получены инструменты: {instruments}")
            return instruments
        except Exception as e:
            logger.error(f"Ошибка при получении инструментов: {e}")
            self.db_manager.connection.rollback()
            return []

    def get_timeframes(self):
        """
        Получает все таймфреймы из таблицы timeframes.
        """
        try:
            # Сначала получаем структуру таблицы
            structure_query = """
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'timeframes'
                ORDER BY ordinal_position;
            """
            self.db_manager.cursor.execute(structure_query)
            columns = [row[0] for row in self.db_manager.cursor.fetchall()]
            
            if not columns:
                logger.warning("Таблица timeframes не найдена или пуста")
                return []
            
            logger.info(f"Структура таблицы timeframes: {columns}")
            
            # Определяем названия колонок
            id_col = columns[0]  # Первая колонка - обычно id
            name_col = None
            
            # Ищем колонку с названием
            for col in columns:
                if col.lower() in ['name', 'interval_name', 'timeframe_name', 'interval', 'timeframe']:
                    name_col = col
                    break
            
            # Если не нашли, используем вторую колонку
            if not name_col and len(columns) > 1:
                name_col = columns[1]
            
            if not name_col:
                logger.error("Не удалось определить колонку с названием таймфрейма")
                return []
            
            # Делаем запрос с правильными названиями колонок
            query = f"SELECT {id_col}, {name_col} FROM timeframes;"
            self.db_manager.cursor.execute(query)
            timeframes = self.db_manager.cursor.fetchall()
            
            logger.info(f"Получены таймфреймы: {timeframes}")
            return timeframes
            
        except Exception as e:
            logger.error(f"Ошибка при получении таймфреймов: {e}")
            # Делаем rollback при ошибке
            try:
                self.db_manager.connection.rollback()
            except:
                pass
            return []

    def get_indicator_types(self):
        """
        Получает все уникальные типы индикаторов из таблицы indicators.

        :return: Список уникальных типов индикаторов.
        """
        try:
            query = "SELECT DISTINCT indicator_type FROM indicators;"
            self.db_manager.cursor.execute(query)
            indicator_types = self.db_manager.cursor.fetchall()
            # logger.info(f"Получены типы индикаторов: {indicator_types}")
            return [row[0] for row in indicator_types]  # Преобразуем результат в список
        except Exception as e:
            logger.error(f"Ошибка при получении типов индикаторов: {e}")
            return []

    def get_price_data(self, instrument_id, timeframe_id):
        """
        Получаем данные по ценам из таблицы candles для заданных инструмента и таймфрейма.
        """
        try:
            query = """
                SELECT candle_time, open, close, high, low, volume
                FROM candles
                WHERE instrument_id = %s AND timeframe_id = %s
                ORDER BY candle_time;
            """
            self.db_manager.cursor.execute(query, (instrument_id, timeframe_id))
            price_data = self.db_manager.cursor.fetchall()
            return price_data
        except Exception as e:
            logger.error(f"Ошибка при получении данных по ценам: {e}")
            return []

    def get_last_indicator_timestamp(self, instrument_id, timeframe_id):
        query = """
        SELECT timestamp FROM indicators
        WHERE instrument_id = %s AND timeframe_id = %s AND indicator_type = %s
        ORDER BY timestamp DESC LIMIT 1
        """
        self.db_manager.cursor.execute(query, (instrument_id, timeframe_id))
        result = self.db_manager.cursor.fetchone()

        # Добавим проверку, что результат не пустой
        if result:
            return result[0]  # Если результат есть, возвращаем первый элемент (timestamp)
        else:
            return None  # Если результата нет, возвращаем None

    def get_indicator_data(self, instrument_id, timeframe_id, indicator_type):
        """
        Получает данные об индикаторах для заданного инструмента, таймфрейма и типа индикатора.

        :param instrument_id: ID инструмента.
        :param timeframe_id: ID таймфрейма.
        :param indicator_type: Тип индикатора.
        :return: Список кортежей (indicator_type, value).
        """
        try:
            query = """
                SELECT indicator_type, value
                FROM indicators
                WHERE instrument_id = %s AND timeframe_id = %s AND indicator_type = %s;
            """
            self.db_manager.cursor.execute(query, (instrument_id, timeframe_id, indicator_type))
            indicator_data = self.db_manager.cursor.fetchall()

            # Логируем данные, чтобы увидеть, что возвращает база данных
            logger.debug(f"Полученные данные для индикатора {indicator_type}: {indicator_data}")

            return indicator_data
        except Exception as e:
            logger.error(f"Ошибка при получении данных об индикаторах: {e}")
            return []

    def get_combined_data(self, instrument_id, timeframe_id, indicator_type):
        """
        Получает данные цен и индикаторов для заданного инструмента, таймфрейма и типа индикатора.

        :param instrument_id: ID инструмента.
        :param timeframe_id: ID таймфрейма.
        :param indicator_type: Тип индикатора.
        :return: Список кортежей (timestamp, open_price, close_price, high_price, low_price, volume, trades, indicator_value).
        """
        try:
            query = """
                SELECT 
                    pd.timestamp, pd.open_price, pd.close_price, pd.high_price, 
                    pd.low_price, pd.volume, pd.trades, ind.value AS indicator_value
                FROM price_data pd
                JOIN indicators ind ON pd.instrument_id = ind.instrument_id 
                    AND pd.timeframe_id = ind.timeframe_id
                WHERE pd.instrument_id = %s AND pd.timeframe_id = %s AND ind.indicator_type = %s
                ORDER BY pd.timestamp;
            """
            self.db_manager.cursor.execute(query, (instrument_id, timeframe_id, indicator_type))
            combined_data = self.db_manager.cursor.fetchall()
            return combined_data
        except Exception as e:
            logger.error(f"Ошибка при получении комбинированных данных: {e}")
            return []


# Использование
if __name__ == '__main__':
    # Создайте экземпляр класса DataImport
    data_import = DataImport()

    # Установите нужные значения для параметров
    instrument_id = 570  # Пример ID инструмента
    timeframe_id = 1  # Пример ID таймфрейма
    indicator_type = 'EMA 9'  # Пример типа индикатора

    # Вызовите функцию get_indicator_data
    indicator_data = data_import.get_indicator_data(instrument_id, timeframe_id, indicator_type)

    # Выведите результат в консоль
    print(indicator_data)