"""
Конвертация данных для графика.

Содержит функции для преобразования данных из БД в DataFrame.
"""

import pandas as pd
import pytz
from datetime import datetime
from loguru import logger


class ChartDataConverter:
    """
    Класс для конвертации данных в DataFrame.
    """
    
    def process_price_data(self, price_data, instrument_symbol: str, timeframe_code: str):
        """
        Обрабатывает данные цен из БД и преобразует в DataFrame.
        
        Возвращает:
            pd.DataFrame или None в случае ошибки
        """
        if not price_data:
            logger.warning(f"Нет данных для {instrument_symbol} на таймфрейме {timeframe_code}")
            return None
        
        logger.debug(f"Получено {len(price_data)} записей из БД")
        
        timestamps = []
        for i, data in enumerate(price_data):
            ts = data[0]
            
            try:
                if hasattr(ts, 'year') and hasattr(ts, 'month') and hasattr(ts, 'day'):
                    ts_converted = pd.Timestamp(ts)
                elif isinstance(ts, str):
                    ts_converted = pd.to_datetime(ts)
                elif isinstance(ts, (int, float)):
                    if ts > 1e12:
                        ts_converted = pd.Timestamp.fromtimestamp(ts / 1e6, tz='UTC')
                    elif ts > 1e10:
                        ts_converted = pd.Timestamp.fromtimestamp(ts / 1000.0, tz='UTC')
                    else:
                        ts_converted = pd.Timestamp.fromtimestamp(ts, tz='UTC')
                else:
                    ts_converted = pd.to_datetime(ts)
                
                if ts_converted.year < 2020:
                    logger.error(f"ПОДОЗРИТЕЛЬНАЯ ДАТА: {ts_converted}")
                
                timestamps.append(ts_converted)
            except Exception as e:
                logger.error(f"Ошибка преобразования timestamp {ts}: {e}")
                continue
        
        if not timestamps:
            logger.error("Не удалось преобразовать ни одного timestamp")
            return None
        
        df = pd.DataFrame({
            'timestamp': timestamps,
            'open': [float(data[1]) for data in price_data],
            'close': [float(data[2]) for data in price_data],
            'high': [float(data[3]) for data in price_data],
            'low': [float(data[4]) for data in price_data],
            'volume': [float(data[5]) for data in price_data]
        })
        
        df.set_index('timestamp', inplace=True)
        
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
        
        df.sort_index(inplace=True)
        
        return df
    
    def convert_timezone(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Конвертирует timezone индекса DataFrame в локальный часовой пояс.
        """
        try:
            local_now = datetime.now()
            local_tz = local_now.astimezone().tzinfo
            
            if local_tz is None or str(local_tz) == 'None':
                import time
                local_tz_offset = -time.timezone if (time.daylight == 0) else -time.altzone
                
                if local_tz_offset == 10800:
                    local_tz = pytz.timezone('Europe/Moscow')
                elif local_tz_offset == 14400:
                    local_tz = pytz.timezone('Europe/Samara')
                elif local_tz_offset == 7200:
                    local_tz = pytz.timezone('Europe/Kaliningrad')
                else:
                    local_tz = pytz.timezone('Europe/Moscow')
            else:
                if not isinstance(local_tz, pytz.BaseTzInfo):
                    local_tz = pytz.timezone('Europe/Moscow')
        except Exception as e:
            logger.warning(f"Ошибка определения часового пояса: {e}, используем Москву")
            local_tz = pytz.timezone('Europe/Moscow')
        
        if df.index.tz is None:
            df.index = df.index.tz_localize('UTC').tz_convert(local_tz)
        else:
            df.index = df.index.tz_convert(local_tz)
        
        df.index = df.index.tz_localize(None)
        
        return df
