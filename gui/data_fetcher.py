"""
Модуль для получения данных из базы данных.

Содержит класс DataFetcher для удобного доступа к данным о инструментах,
таймфреймах, ценах и индикаторах.
"""
from crypto_trading_bot.database.data_import import DataImport
from crypto_trading_bot.database.models import Instrument, Timeframe, PriceData, Indicator


class DataFetcher:
    """
    Класс для получения данных из базы данных.
    
    Предоставляет удобные методы для доступа к данным о торговых инструментах,
    таймфреймах, исторических ценах и технических индикаторах.
    """
    
    def __init__(self):
        """
        Инициализация объекта DataFetcher.
        
        Создает экземпляр DataImport для работы с базой данных.
        """
        self.data_import = DataImport()

    def get_instruments(self):
        """
        Получает список всех доступных торговых инструментов.
        
        Возвращает:
            list[Instrument]: Список объектов Instrument с id и symbol.
        """
        instruments_data = self.data_import.get_instruments()
        return [Instrument(id, symbol) for id, symbol in instruments_data]

    def get_timeframes(self):
        """
        Получает список всех доступных таймфреймов.
        
        Возвращает:
            list[Timeframe]: Список объектов Timeframe с id и interval_name.
        """
        timeframes_data = self.data_import.get_timeframes()
        # Поддерживаем разные форматы данных из БД
        result = []
        for tf_data in timeframes_data:
            if isinstance(tf_data, tuple) and len(tf_data) >= 2:
                tf_id = tf_data[0]
                tf_name = tf_data[1]
                result.append(Timeframe(tf_id, tf_name))
            elif hasattr(tf_data, 'id') and hasattr(tf_data, 'interval_name'):
                result.append(Timeframe(tf_data.id, tf_data.interval_name))
        return result

    def get_price_data(self, instrument_id, timeframe_id):
        """
        Получает исторические данные о ценах для указанного инструмента и таймфрейма.
        
        Параметры:
            instrument_id (int): ID торгового инструмента.
            timeframe_id (int): ID таймфрейма.
        
        Возвращает:
            list[PriceData]: Список объектов PriceData с данными о ценах.
        """
        price_data_raw = self.data_import.get_price_data(instrument_id, timeframe_id)
        return [PriceData(*data) for data in price_data_raw]

    def get_indicator_types(self):
        """
        Получает все уникальные типы индикаторов из базы данных.
        
        Возвращает:
            list[str]: Список названий типов индикаторов.
        """
        indicator_types = self.data_import.get_indicator_types()
        return [row for row in indicator_types]

    def get_indicator_data(self, instrument_id, timeframe_id, indicator_type):
        """
        Получает данные об индикаторах для заданного инструмента, таймфрейма и типа индикатора.
        
        Параметры:
            instrument_id (int): ID торгового инструмента.
            timeframe_id (int): ID таймфрейма.
            indicator_type (str): Тип индикатора (например, 'EMA 9', 'RSI').
        
        Возвращает:
            list[tuple]: Список кортежей (indicator_type, value) с данными индикатора.
        """
        return self.data_import.get_indicator_data(instrument_id, timeframe_id, indicator_type)

    def get_instrument_id(self, symbol):
        """
        Получает ID инструмента по его символу.
        
        Параметры:
            symbol (str): Символ инструмента (например, 'BTCUSDT').
        
        Возвращает:
            int или None: ID инструмента, если найден, иначе None.
        """
        instruments = self.get_instruments()
        for instrument in instruments:
            if instrument.symbol == symbol:
                return instrument.id
        return None

    def get_timeframe_id(self, interval_name):
        """
        Получает ID таймфрейма по его названию.
        
        Параметры:
            interval_name (str): Название таймфрейма (например, '1day', '1hour').
        
        Возвращает:
            int или None: ID таймфрейма, если найден, иначе None.
        """
        timeframes = self.get_timeframes()
        for timeframe in timeframes:
            if timeframe.interval_name == interval_name:
                return timeframe.id
        return None
