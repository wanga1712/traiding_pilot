"""
Модуль для визуализации данных о ценах и индикаторах.

Содержит класс DataVisualizer для построения графиков свечей
и технических индикаторов.
"""
import mplfinance as mpf
import pandas as pd
from io import BytesIO
import base64
from loguru import logger
from datetime import datetime


class DataVisualizer:
    """
    Класс для визуализации торговых данных.
    
    Предоставляет методы для построения графиков свечей и наложения
    технических индикаторов на графики.
    """
    
    def __init__(self, db_manager):
        """
        Инициализация объекта DataVisualizer.
        
        Параметры:
            db_manager: Объект для работы с базой данных (DataFetcher).
        """
        self.db_manager = db_manager

    def plot_graph(self, selected_instrument, selected_timeframe, indicator_name=None, start_date=None, end_date=None):
        """
        Строит график свечей с возможностью наложения индикаторов.
        
        Параметры:
            selected_instrument (str): Символ инструмента.
            selected_timeframe (str): Название таймфрейма.
            indicator_name (str или list, optional): Тип индикатора или список индикаторов.
            start_date (datetime, optional): Начальная дата для фильтрации данных.
            end_date (datetime, optional): Конечная дата для фильтрации данных.
        
        Возвращает:
            str или None: Base64-строка изображения графика или None в случае ошибки.
        """
        try:
            # Получаем ID инструмента и таймфрейма
            instrument_id = self.get_instrument_id(selected_instrument)
            timeframe_id = self.get_timeframe_id(selected_timeframe)

            # Получаем данные по ценам для выбранного инструмента и таймфрейма
            price_data = self.db_manager.get_price_data(instrument_id, timeframe_id)

            # Фильтруем данные по новому диапазону (если start_date и end_date переданы)
            if start_date and end_date:
                price_data = [data for data in price_data if start_date <= data.timestamp <= end_date]

            # Преобразуем данные в DataFrame для использования в mplfinance
            df = pd.DataFrame({
                'Timestamp': [data.timestamp for data in price_data],
                'Open': [data.open_price for data in price_data],
                'High': [data.high_price for data in price_data],
                'Low': [data.low_price for data in price_data],
                'Close': [data.close_price for data in price_data],
                'Volume': [data.volume for data in price_data],  # Объемы торгов
                'Trades': [data.trades for data in price_data]  # Количество ордеров
            })

            df['Timestamp'] = pd.to_datetime(df['Timestamp'])
            df.set_index('Timestamp', inplace=True)

            # Преобразуем все колонки в числовой тип (float), чтобы избежать ошибок
            df['Open'] = pd.to_numeric(df['Open'], errors='coerce')
            df['High'] = pd.to_numeric(df['High'], errors='coerce')
            df['Low'] = pd.to_numeric(df['Low'], errors='coerce')
            df['Close'] = pd.to_numeric(df['Close'], errors='coerce')
            df['Volume'] = pd.to_numeric(df['Volume'], errors='coerce')
            df['Trades'] = pd.to_numeric(df['Trades'], errors='coerce')

            # Убираем строки с NaN значениями, если они есть
            df.dropna(inplace=True)

            # Настройки для отображения графика
            mpf_style = mpf.make_mpf_style(base_mpf_style='charles', rc={'font.size': 8})

            # Создаем дополнительно ось для объемов
            volume_plot = mpf.make_addplot(df['Volume'], panel=1, color='b', secondary_y=False)  # Добавляем объемы

            # Если индикатор выбран, получаем его данные
            indicator_plot = None
            if indicator_name:
                indicator_data = self.db_manager.get_indicator_data(instrument_id, timeframe_id, indicator_name)

                # Выводим данные индикатора в лог для отладки
                logger.debug(f"Indicator data for {indicator_name}: {indicator_data}")

                if indicator_data:
                    # Извлекаем только значения индикатора, убедившись, что это числа
                    indicator_values = [float(value) for _, value in indicator_data if isinstance(value, (int, float))]
                    if indicator_values:
                        # Добавляем индикатор как дополнительную линию на график
                        indicator_plot = mpf.make_addplot(indicator_values, panel=0, color='r', secondary_y=False)

            # Используем mpf.plot с добавлением объемов и индикатора, если он есть
            fig, axes = mpf.plot(df,
                                 type='line',
                                 style=mpf_style,
                                 title=f'{selected_instrument} Candlestick Chart',
                                 ylabel='Price',
                                 addplot=[volume_plot, indicator_plot] if indicator_plot else [volume_plot],
                                 returnfig=True,
                                 figsize=(16, 8))  # Увеличиваем размер графика

            # Сохранение графика в base64 для отображения в HTML
            img_buf = BytesIO()
            fig.savefig(img_buf, format='png')
            img_buf.seek(0)
            img_base64 = base64.b64encode(img_buf.read()).decode('utf-8')

            return img_base64

        except Exception as e:
            logger.error(f"Error occurred: {str(e)}")
            return None

    def get_instrument_id(self, symbol):
        """
        Получает ID инструмента по символу.
        
        Параметры:
            symbol (str): Символ инструмента.
        
        Возвращает:
            int или None: ID инструмента или None, если не найден.
        """
        instruments = self.db_manager.get_instruments()
        for instrument in instruments:
            if instrument.symbol == symbol:
                return instrument.id
        return None

    def get_timeframe_id(self, interval_name):
        """
        Получает ID таймфрейма по названию.
        
        Параметры:
            interval_name (str): Название таймфрейма.
        
        Возвращает:
            int или None: ID таймфрейма или None, если не найден.
        """
        timeframes = self.db_manager.get_timeframes()
        for timeframe in timeframes:
            if timeframe.interval_name == interval_name:
                return timeframe.id
        return None
