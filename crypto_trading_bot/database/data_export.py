from loguru import logger
from datetime import datetime
import pytz
import pandas as pd

from crypto_trading_bot.database.db_connection import DatabaseManager
from crypto_trading_bot.database.data_import import DataImport
from crypto_trading_bot.config.config import CONFIG  # Предполагаем, что конфигурация импортируется отсюда

class DataExporter:
    """
    Класс для экспорта данных в базу данных.

    Атрибуты:
        db_manager (DatabaseManager): Объект для работы с базой данных.
    """

    def __init__(self):
        """
        Инициализация класса DataExporter, который использует DatabaseManager для работы с базой данных.
        """
        self.db_manager = DatabaseManager()  # Инициализируем объект для работы с базой данных.
        self.db_import = DataImport()

    def export_symbols_to_db(self):
        """
        Получает символы из конфигурации и записывает их в таблицу instruments в базе данных.
        """
        symbols = CONFIG['TRADE']['SYMBOLS']  # Получаем список символов из конфигурации

        # Для каждого символа добавляем его в таблицу instruments
        for symbol in symbols:
            query = """
                INSERT INTO instruments (symbol)
                VALUES (%s)
                ON CONFLICT (symbol) DO NOTHING;  -- Добавляем символ, если его нет в таблице
            """
            try:
                # Выполняем запрос к базе данных
                self.db_manager.cursor.execute(query, (symbol,))
                self.db_manager.connection.commit()  # Подтверждаем изменения в базе данных
                logger.info(f"Символ {symbol} успешно добавлен в базу данных.")
            except Exception as e:
                logger.error(f"Ошибка при добавлении символа {symbol}: {e}")
                self.db_manager.connection.rollback()  # Откатываем изменения при ошибке

    def insert_price_data(self, symbol, timeframe, data):
        """
        Добавляет данные о свечах в таблицу candles, проверяя существующие записи.

        Параметры:
            symbol (str): Символ инструмента (например, 'btcusdt').
            timeframe (str): Название таймфрейма (например, '1min', '1h').
            data (list или pd.DataFrame): Список данных о свечах или DataFrame из Yahoo Finance.
        """
        try:
            # Получаем id инструмента из таблицы instruments
            query_instrument = "SELECT id FROM instruments WHERE LOWER(symbol) = LOWER(%s);"
            result = self.db_manager.fetch_one(query_instrument, (symbol,))
            if not result:
                logger.error(f"Инструмент {symbol} не найден в базе данных")
                return False
            instrument_id = result[0]

            # Получаем id таймфрейма из таблицы timeframes (пробуем разные варианты)
            timeframe_queries = [
                "SELECT id FROM timeframes WHERE code = %s;",
                "SELECT id FROM timeframes WHERE api_value = %s;",
                "SELECT id FROM timeframes WHERE interval_name = %s;",
                "SELECT id FROM timeframes WHERE name = %s;",
                "SELECT id FROM timeframes WHERE timeframe_name = %s;"
            ]
            timeframe_id = None
            for query in timeframe_queries:
                try:
                    result = self.db_manager.fetch_one(query, (timeframe,))
                    if result:
                        timeframe_id = result[0]
                        break
                except:
                    continue
            
            if not timeframe_id:
                logger.error(f"Таймфрейм {timeframe} не найден в базе данных")
                return False

            # Обрабатываем данные в зависимости от типа
            if isinstance(data, pd.DataFrame):
                # Данные из Yahoo Finance (DataFrame)
                return self._insert_dataframe(symbol, instrument_id, timeframe_id, data)
            else:
                # Данные в формате списка словарей
                return self._insert_list_data(symbol, instrument_id, timeframe_id, data)
                
        except Exception as e:
            logger.error(f"Ошибка при добавлении данных о свечах для символа {symbol} и таймфрейма {timeframe}: {e}")
            return False
    
    def _insert_dataframe(self, symbol: str, instrument_id: int, timeframe_id: int, df: pd.DataFrame) -> bool:
        """
        Сохраняет данные из DataFrame (Yahoo Finance) в базу данных.
        
        Параметры:
            symbol (str): Символ инструмента.
            instrument_id (int): ID инструмента.
            timeframe_id (int): ID таймфрейма.
            df (pd.DataFrame): DataFrame с данными о ценах.
        
        Возвращает:
            bool: True если данные успешно сохранены.
        """
        inserted_count = 0
        skipped_count = 0
        
        try:
            for index, row in df.iterrows():
                # Преобразуем индекс (datetime) в timestamp
                if isinstance(index, pd.Timestamp):
                    timestamp = index.to_pydatetime()
                else:
                    timestamp = pd.to_datetime(index).to_pydatetime()
                
                # Проверяем, есть ли уже данные
                query_check = """
                    SELECT 1 FROM candles
                    WHERE instrument_id = %s AND timeframe_id = %s AND candle_time = %s;
                """
                existing = self.db_manager.fetch_one(query_check, (instrument_id, timeframe_id, timestamp))
                
                if not existing:
                    # Вставляем новые данные
                    query_insert = """
                        INSERT INTO candles (instrument_id, timeframe_id, candle_time, open, high, low, close, volume)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                    """
                    self.db_manager.execute_query(
                        query_insert,
                        (
                            instrument_id, timeframe_id, timestamp,
                            float(row['Open']), float(row['High']),
                            float(row['Low']), float(row['Close']),
                            float(row.get('Volume', 0))
                        )
                    )
                    self.db_manager.connection.commit()
                    inserted_count += 1
                else:
                    skipped_count += 1
            
            logger.info(f"Для {symbol}: добавлено {inserted_count} свечей, пропущено {skipped_count} (уже существуют)")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка при сохранении DataFrame для {symbol}: {e}")
            return False
    
    def _insert_list_data(self, symbol: str, instrument_id: int, timeframe_id: int, data: list) -> bool:
        """
        Сохраняет данные из списка словарей в базу данных.
        
        Параметры:
            symbol (str): Символ инструмента.
            instrument_id (int): ID инструмента.
            timeframe_id (int): ID таймфрейма.
            data (list): Список словарей с данными о свечах.
        
        Возвращает:
            bool: True если данные успешно сохранены.
        """
        try:
            for tick in data:
                # Преобразуем время в timestamp
                if 'timestamp' in tick:
                    timestamp = tick['timestamp']
                elif 'id' in tick:
                    timestamp = datetime.utcfromtimestamp(tick['id']).replace(tzinfo=pytz.utc)
                else:
                    logger.warning(f"Не найден timestamp в данных: {tick}")
                    continue

                # Проверяем, есть ли уже данные
                query_check = """
                    SELECT 1 FROM candles
                    WHERE instrument_id = %s AND timeframe_id = %s AND candle_time = %s;
                """
                existing = self.db_manager.fetch_one(query_check, (instrument_id, timeframe_id, timestamp))

                if not existing:
                    open_price = tick.get('open', tick.get('Open', 0))
                    close_price = tick.get('close', tick.get('Close', 0))
                    high_price = tick.get('high', tick.get('High', 0))
                    low_price = tick.get('low', tick.get('Low', 0))
                    volume = round(tick.get('vol', tick.get('Volume', tick.get('volume', 0))), 2)

                    query_insert = """
                        INSERT INTO candles (instrument_id, timeframe_id, candle_time, open, high, low, close, volume)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                    """
                    self.db_manager.execute_query(
                        query_insert,
                        (instrument_id, timeframe_id, timestamp, open_price,
                         high_price, low_price, close_price, volume)
                    )
                    self.db_manager.connection.commit()
            
            return True
        except Exception as e:
            logger.error(f"Ошибка при сохранении списка данных для {symbol}: {e}")
            return False


    def update_last_indicator_timestamp(self, instrument_symbol, timeframe, new_timestamp):
        """
        Обновляет временную метку последнего вычисления индикатора для данного инструмента и таймфрейма.
        """
        # Получаем id инструмента и id таймфрейма
        instrument_id = self.db_import.get_instrument_id(instrument_symbol)
        timeframe_id = self.db_import.get_timeframe_id(timeframe)

        # SQL-запрос для обновления временной метки
        query = """
        UPDATE indicators
        SET timestamp = %s
        WHERE instrument_id = %s AND timeframe_id = %s
        """
        params = (new_timestamp, instrument_id, timeframe_id)

        # Выполняем запрос
        self.db_manager.db_connection.execute(query, params)

    def save_indicator(self, instrument_id, timeframe_id, indicator_type, value, timestamp):
        query = """
        INSERT INTO indicators (instrument_id, timeframe_id, indicator_type, value, timestamp)
        VALUES (%s, %s, %s, %s, %s)
        """
        try:
            # Логируем запрос перед его выполнением
            logger.debug(
                f"Executing query: {query} with values {instrument_id}, {timeframe_id}, {indicator_type}, {value}, {timestamp}")
            self.db_manager.cursor.execute(query, (instrument_id, timeframe_id, indicator_type, value, timestamp))
            self.db_manager.connection.commit()
            logger.debug(f"Saved indicator: {indicator_type} for {instrument_id} at {timestamp}")
        except Exception as e:
            logger.error(f"Error saving indicator {indicator_type} for {instrument_id} at {timestamp}: {e}")


# Использование
if __name__ == '__main__':
    data_exporter = DataExporter()  # Создаем экземпляр класса
    # data_exporter.export_symbols_to_db()  # Записываем символы в базу данных
