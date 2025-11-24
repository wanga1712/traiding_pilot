"""
Валидация данных для графика.

Содержит функции для проверки и валидации данных перед отрисовкой.
"""

from loguru import logger


class ChartDataValidator:
    """
    Класс для валидации данных графика.
    """
    
    def validate_data(self, df, instrument_symbol: str, timeframe_code: str):
        """
        Валидирует данные DataFrame.
        
        Возвращает:
            pd.DataFrame или None если данные невалидны
        """
        if df is None or df.empty:
            logger.warning(f"DataFrame пустой для {instrument_symbol} на {timeframe_code}")
            return None
        
        if df.isnull().any().any():
            logger.warning("В данных есть NaN, удаляем...")
            df = df.dropna()
            if df.empty:
                logger.error("После удаления NaN DataFrame пустой")
                return None
        
        if (df[['Open', 'High', 'Low', 'Close']] <= 0).any().any():
            logger.error("В данных есть неположительные значения!")
            return None
        
        return df
    
    def limit_candles(self, df, timeframe_code: str):
        """
        Ограничивает количество свечей для отображения.
        """
        max_candles = {
            '1m': 500,  # Увеличено для расчета DMA(25x5) = минимум 30 свечей
            '3m': 500,  # Увеличено для расчета DMA(25x5)
            '5m': 500,  # Увеличено для расчета DMA(25x5)
            '15m': 500, '30m': 500,
            '1h': 500, '2h': 400, '4h': 300, '6h': 300, '12h': 300,
            '1d': 500, '1w': 200, '1mo': 100,
        }
        
        limit = max_candles.get(timeframe_code, 500)
        if len(df) > limit:
            df = df.tail(limit)
            logger.debug(f"Ограничено до последних {limit} свечей для таймфрейма {timeframe_code}")
        
        return df
    
    def prepare_columns(self, df):
        """
        Подготавливает колонки DataFrame для отрисовки.
        """
        df.rename(columns={
            'open': 'Open',
            'high': 'High',
            'low': 'Low',
            'close': 'Close',
            'volume': 'Volume'
        }, inplace=True)
        
        required_columns = ['Open', 'High', 'Low', 'Close', 'Volume']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            logger.error(f"Отсутствуют колонки: {missing_columns}")
            return None
        
        return df

