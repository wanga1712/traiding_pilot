import pandas as pd
import numpy as np
from tqdm import tqdm
from loguru import logger
from datetime import datetime

from crypto_trading_bot.database.data_export import DataExporter
from crypto_trading_bot.database.data_import import DataImport

# Получаем текущую временную метку
timestamp = datetime.now()

class IndicatorCalculatorDi:
    def __init__(self):
        # Инициализация объектов для экспорта и импорта данных
        self.db_export = DataExporter()
        self.db_import = DataImport()

    def convert_to_dataframe(self, price_data):
        """
        Преобразует данные из базы данных в pandas DataFrame для удобства обработки.
        """
        # Преобразуем данные в DataFrame, указывая индексы колонок
        df = pd.DataFrame(price_data,
                          columns=["timestamp", "open_price", "close_price", "high_price", "low_price", "volume",
                                   "trades"])

        # Преобразуем колонку "timestamp" в datetime
        df["timestamp"] = pd.to_datetime(df["timestamp"])

        # Преобразуем все числовые столбцы в тип float
        df["open_price"] = df["open_price"].astype(float)
        df["close_price"] = df["close_price"].astype(float)
        df["high_price"] = df["high_price"].astype(float)
        df["low_price"] = df["low_price"].astype(float)
        df["volume"] = df["volume"].astype(float)
        df["trades"] = df["trades"].astype(float)

        # Устанавливаем "timestamp" как индекс
        df.set_index("timestamp", inplace=True)

        return df

    def calculate_and_save_indicators(self):
        """
        Получает данные из базы данных, рассчитывает индикаторы и сохраняет их в базу.
        """
        # Получаем список всех инструментов и таймфреймов
        instruments = self.db_import.get_instruments()  # Теперь вызываем без аргументов
        timeframes = self.db_import.get_timeframes()

        # Создаем общий прогресс-бар для всех инструментов и таймфреймов
        total = len(instruments) * len(timeframes)  # Общее количество инструментов и таймфреймов
        with tqdm(total=total, desc="Saving indicators", unit="instrument-timeframe") as pbar:
            # Для каждого инструмента и таймфрейма:
            for instrument in instruments:
                instrument_symbol = instrument[1]  # Символ инструмента
                for timeframe in timeframes:
                    timeframe_str = timeframe[1]  # Строка для таймфрейма

                    # Получаем исторические данные для инструмента и таймфрейма
                    instrument_id = instrument[0]
                    timeframe_id = timeframe[0]
                    price_data = self.db_import.get_price_data(instrument_id, timeframe_id)

                    if price_data:
                        df = self.convert_to_dataframe(price_data)

                        # Рассчитываем индикаторы
                        indicators = self.calculate_indicators_for_data(df)

                        if not indicators:
                            logger.warning(f"No indicators calculated for {instrument_symbol} at {timeframe_str}")
                            continue

                        # Сохраняем индикаторы в базу данных
                        for indicator_name, indicator_value in indicators:
                            try:
                                # Преобразуем в обычный float, если это необходимо
                                if isinstance(indicator_value, list):
                                    indicator_value = float(
                                        indicator_value[-1])  # Используем последнее значение в списке
                                elif isinstance(indicator_value, pd.Series):
                                    indicator_value = indicator_value.iloc[-1]
                                indicator_value = float(indicator_value)

                                # Сохраняем индикатор
                                timestamp = df.index[-1]  # Получаем последний временной штамп
                                self.db_export.save_indicator(instrument_id, timeframe_id, indicator_name,
                                                              indicator_value, timestamp)
                            except Exception as e:
                                logger.error(f"Error while saving {indicator_name}: {e}")

                    # Обновляем прогресс-бар после обработки каждого инструмента и таймфрейма
                    pbar.update(1)

    def calculate_indicators_for_data(self, df):
        """
        Рассчитывает все индикаторы для переданных данных.
        """
        # logger.debug(f"Calculating indicators for {df.index[-1]}")
        sma_14 = self.calculate_sma(df, 14)
        sma_50 = self.calculate_sma(df, 50)
        ema_9 = self.calculate_ema(df, 9)
        rsi_14 = self.calculate_rsi(df, 14)
        ama_14 = self.calculate_ama(df, 14)
        macd, signal_line, macd_histogram = self.calculate_macd(df)
        stoch_k, stoch_d = self.calculate_stochastic(df, 14, 3)
        prediction_signal = self.calculate_prediction_signal(df)

        op, xop, cop = self.calculate_op_xop_cop(df)
        support_levels, resistance_levels = self.calculate_fibonacci_levels_support_resisstance(df)

        cci = self.calculate_cci(df)
        obv = self.calculate_obv(df)
        atr = self.calculate_atr(df)
        williams_r = self.calculate_williams_r(df)
        # pivot_points = self.calculate_pivot_points(df)
        # ichimoku = self.calculate_ichimoku(df)

        # Печать для отладки
        # logger.debug(f"Calculated indicators for {df.index[-1]}")

        return [
            ("SMA 14", sma_14.iloc[-1]),
            ("SMA 50", sma_50.iloc[-1]),
            ("EMA 9", ema_9.iloc[-1]),
            ("RSI 14", rsi_14.iloc[-1]),
            ("AMA 14", ama_14.iloc[-1]),
            ("MACD", macd.iloc[-1]),
            ("Signal Line", signal_line.iloc[-1]),
            ("MACD Histogram", macd_histogram.iloc[-1]),
            ("Stochastic %K", stoch_k.iloc[-1]),
            ("Stochastic %D", stoch_d.iloc[-1]),
            ("Prediction Signal", prediction_signal),
            ("OP", op),
            ("XOP", xop),
            ("COP", cop),
            ("Support", support_levels),
            ("Resistance", resistance_levels),
            ("CCI", cci.iloc[-1]),
            ("OBV", obv[-1]),
            ("ATR", atr.iloc[-1]),
            ("Williams %R", williams_r.iloc[-1])
        ]

    # def convert_to_dataframe(self, price_data):
    #     """
    #     Преобразует данные из базы данных в pandas DataFrame для удобства обработки.
    #     """
    #     # Предположим, что каждый элемент в price_data — это кортеж, например:
    #     # (timestamp, open, close, high, low, volume, trades)
    #
    #     # Преобразуем данные в DataFrame, указывая индексы колонок
    #     df = pd.DataFrame(price_data, columns=["timestamp", "open", "close", "high", "low", "volume", "trades"])
    #
    #     # Преобразуем колонку "timestamp" в datetime
    #     df["timestamp"] = pd.to_datetime(df["timestamp"])
    #
    #     # Устанавливаем "timestamp" как индекс
    #     df.set_index("timestamp", inplace=True)
    #
    #     return df

    def calculate_sma(self, df, window):
        """Вычисляем простую скользящую среднюю (SMA)"""
        return df['close_price'].rolling(window=window).mean()

    def calculate_ema(self, df, window):
        """Вычисляем экспоненциальную скользящую среднюю (EMA)"""
        return df['close_price'].ewm(span=window, adjust=False).mean()

    def calculate_rsi(self, df, window):
        """Вычисляем индекс относительной силы (RSI)"""
        delta = df['close_price'].diff()
        gain = (delta.where(delta > 0, 0)).fillna(0)
        loss = (-delta.where(delta < 0, 0)).fillna(0)

        avg_gain = gain.rolling(window=window).mean()
        avg_loss = loss.rolling(window=window).mean()

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def calculate_ama(self, df, window):
        """Вычисление адаптивной скользящей средней (AMA)"""
        # Волатильность: сумма абсолютных изменений закрытия за период
        volatility = df['close_price'].diff().abs().rolling(window=window).sum()

        # Тренд: разница между первой и последней ценой за период
        trend = df['close_price'].diff(window).abs()

        # Приводим значения к типу float перед вычислением efficiency_ratio
        efficiency_ratio = (trend.astype(float)) / (volatility.astype(float))

        smoothing_constant = (efficiency_ratio * (2 / (window + 1)) + (1 - efficiency_ratio) * (2 / (window + 1)))

        # Начальная скользящая средняя
        ama = df['close_price'].iloc[0]

        # Применяем AMA по каждой точке
        ama_values = [ama]
        for i in range(1, len(df)):
            ama = ama + smoothing_constant.iloc[i] * (df['close_price'].iloc[i] - ama)
            ama_values.append(ama)

        return pd.Series(ama_values, index=df.index)

    def calculate_macd(self, df, short_window=12, long_window=26, signal_window=9):
        """Вычисление адаптивного MACD с применением стандартных окон"""

        # Вычисление короткой и длинной экспоненциальной скользящей средней (EMA)
        short_ema = df['close_price'].ewm(span=short_window, adjust=False).mean()
        long_ema = df['close_price'].ewm(span=long_window, adjust=False).mean()

        # MACD линия - разница между короткой и длинной EMA
        macd_line = short_ema - long_ema

        # Сигнальная линия - 9-дневная EMA от MACD линии
        signal_line = macd_line.ewm(span=signal_window, adjust=False).mean()

        # Гистограмма MACD - разница между MACD линией и сигнальной линией
        macd_histogram = macd_line - signal_line

        return macd_line, signal_line, macd_histogram

    def calculate_stochastic(self, df, window=14, smooth_window=3):
        """Вычисление стохастического осциллятора по Дину Поли"""

        # Расчет %K
        low_min = df['low_price'].rolling(window=window).min()
        high_max = df['high_price'].rolling(window=window).max()

        stoch_k = 100 * (df['close_price'] - low_min) / (high_max - low_min)

        # Сглаживание %K для получения %D
        stoch_d = stoch_k.rolling(window=smooth_window).mean()

        return stoch_k, stoch_d

    def calculate_prediction_signal(self, df, short_window=9, long_window=21):
        """
        Рассчитывает индикатор предсказателя (Prediction Indicator) по Дину Поли.
        Используется разница между двумя скользящими средними (SMA).
        """
        # Рассчитываем две скользящие средние
        sma_short = self.calculate_sma(df, short_window)
        sma_long = self.calculate_sma(df, long_window)

        # Разница между короткой и длинной скользящей средней
        prediction_signal = sma_short - sma_long

        # Можно добавить логику для определения сигнала (например, если разница положительна, это сигнал на покупку, если отрицательна - на продажу)
        return prediction_signal

    def calculate_op_xop_cop(self, df):
        """
        Рассчитывает точки OP, XOP и COP по методике Дина Поли.
        """
        # Для OP, XOP и COP мы используем уровни Фибоначчи и последние цены
        last_high = df['high_price'].iloc[-1]  # Последний максимум
        last_low = df['low_price'].iloc[-1]  # Последний минимум
        last_close = df['close_price'].iloc[-1]  # Последняя цена закрытия

        # OP (Opening Point) - это точка начала тренда
        op = last_close  # OP определяется как последняя цена закрытия

        # XOP (Extended Opening Point) - это продолжение тренда
        # Для этого вычисляем продолжение по уровню Фибоначчи, например, 161.8%
        fibonacci_extension = 1.618 * (last_high - last_low)
        xop = last_high + fibonacci_extension

        # COP (Change of Polarity) - это точка смены полярности тренда
        # Используем коррекцию Фибоначчи, например, 50% от движения
        fibonacci_retracement = 0.5 * (last_high - last_low)
        cop = last_high - fibonacci_retracement  # Примерная точка разворота тренда

        return op, xop, cop

    def calculate_fibonacci_levels_support_resisstance(self, df, lookback_period=50):
        """
        Рассчитывает уровни поддержки и сопротивления на основе уровней Фибоначчи.
        """
        # Выбираем данные за последние 'lookback_period' баров
        df_lookback = df[-lookback_period:]

        # Находим локальные максимумы и минимумы за последние несколько периодов
        max_price = df_lookback['high_price'].max()
        min_price = df_lookback['low_price'].min()

        # Диапазон (Range)
        price_range = max_price - min_price

        # Уровни Фибоначчи (сопротивление)
        resistance_23_6 = max_price - price_range * 0.236
        resistance_38_2 = max_price - price_range * 0.382
        resistance_50 = max_price - price_range * 0.5
        resistance_61_8 = max_price - price_range * 0.618

        # Уровни Фибоначчи (поддержка)
        support_23_6 = min_price + price_range * 0.236
        support_38_2 = min_price + price_range * 0.382
        support_50 = min_price + price_range * 0.5
        support_61_8 = min_price + price_range * 0.618

        # Возвращаем найденные уровни поддержки и сопротивления
        support_levels = [support_23_6, support_38_2, support_50, support_61_8]
        resistance_levels = [resistance_23_6, resistance_38_2, resistance_50, resistance_61_8]

        return support_levels, resistance_levels

    def calculate_fibonacci_levels(self, df):
        highest_price = df['high_price'].max()
        lowest_price = df['low_price'].min()
        diff = highest_price - lowest_price
        level_1 = highest_price - diff * 0.236
        level_2 = highest_price - diff * 0.382
        level_3 = highest_price - diff * 0.5
        level_4 = highest_price - diff * 0.618
        return [level_1, level_2, level_3, level_4], [highest_price, lowest_price]

    def calculate_cci(self, df, period=20):
        # Commodity Channel Index
        typical_price = (df['high_price'] + df['low_price'] + df['close_price']) / 3
        moving_avg = typical_price.rolling(window=period).mean()
        mean_deviation = typical_price.rolling(window=period).apply(lambda x: np.mean(np.abs(x - x.mean())))
        cci = (typical_price - moving_avg) / (0.015 * mean_deviation)
        return cci

    def calculate_obv(self, df):
        obv = [0]
        for i in range(1, len(df)):
            if df['close_price'].iloc[i] > df['close_price'].iloc[i - 1]:
                obv.append(obv[-1] + df['volume'].iloc[i])
            elif df['close_price'].iloc[i] < df['close_price'].iloc[i - 1]:
                obv.append(obv[-1] - df['volume'].iloc[i])
            else:
                obv.append(obv[-1])
        return obv

    def calculate_atr(self, df, period=14):
        high_low = df['high_price'] - df['low_price']
        high_close = (df['high_price'] - df['close_price'].shift()).abs()
        low_close = (df['low_price'] - df['close_price'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        return atr

    def calculate_williams_r(self, df, period=14):
        highest_high = df['high_price'].rolling(window=period).max()
        lowest_low = df['low_price'].rolling(window=period).min()
        williams_r = ((highest_high - df['close_price']) / (highest_high - lowest_low)) * -100
        return williams_r

    # def calculate_pivot_points(self, df):
    #     high = df['high_price'].iloc[-1]
    #     low = df['low_price'].iloc[-1]
    #     close = df['close_price'].iloc[-1]
    #     pivot = (high + low + close) / 3
    #     resistance_1 = 2 * pivot - low
    #     support_1 = 2 * pivot - high
    #     return pivot, support_1, resistance_1
    #
    # def calculate_ichimoku(self, df):
    #     nine_period_high = df['high_price'].rolling(window=9).max()
    #     nine_period_low = df['low_price'].rolling(window=9).min()
    #     senkou_span_a = ((nine_period_high + nine_period_low) / 2).shift(26)
    #     senkou_span_b = ((df['high_price'].rolling(window=52).max() + df['low_price'].rolling(window=52).min()) / 2).shift(26)
    #     return senkou_span_a, senkou_span_b

    def run(self):
        """
        Запускает процесс получения данных, расчета индикаторов и их сохранения.
        """
        self.calculate_and_save_indicators()


# Использование
if __name__ == '__main__':
    indicator_calculator = IndicatorCalculatorDi()
    indicator_calculator.run()
