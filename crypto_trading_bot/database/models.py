class Instrument:
    def __init__(self, id, symbol):
        self.id = id
        self.symbol = symbol

class Timeframe:
    def __init__(self, id, name):
        """
        Инициализация объекта Timeframe.
        
        Параметры:
            id (int): ID таймфрейма.
            name (str): Название таймфрейма (может быть interval_name, name, timeframe_name).
        """
        self.id = id
        # Поддерживаем разные названия атрибутов для совместимости
        self.interval_name = name
        self.name = name
        self.timeframe_name = name

class PriceData:
    def __init__(self, timestamp, open_price, close_price, high_price, low_price, volume, trades):
        self.timestamp = timestamp
        self.open_price = open_price
        self.close_price = close_price
        self.high_price = high_price
        self.low_price = low_price
        self.volume = volume
        self.trades = trades

class Indicator:
    def __init__(self, indicator_type, value):
        self.indicator_type = indicator_type
        self.value = value