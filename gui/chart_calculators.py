"""
Расчеты для графиков.

Содержит функции для расчета ширины свечей и подготовки данных для отрисовки.
"""

import numpy as np
from matplotlib.dates import date2num

from gui.ui_config import UIConfig


def calculate_candle_width(timeframe_code, df):
    """
    Рассчитывает ширину свечи в днях для корректного отображения.
    """
    if len(df) > 1:
        time_diffs = df.index.to_series().diff().dropna()
        if len(time_diffs) > 0:
            avg_time_diff = time_diffs.mean()
            return avg_time_diff.total_seconds() / 86400.0 * 0.7

    if '1m' in timeframe_code:
        return 1.0 / 60.0 / 24.0 * 0.7
    if '3m' in timeframe_code:
        return 3.0 / 60.0 / 24.0 * 0.7
    if '5m' in timeframe_code:
        return 5.0 / 60.0 / 24.0 * 0.7
    if '15m' in timeframe_code:
        return 15.0 / 60.0 / 24.0 * 0.7
    if '30m' in timeframe_code:
        return 30.0 / 60.0 / 24.0 * 0.7
    if '1h' in timeframe_code:
        return 1.0 / 24.0 * 0.7
    if '1d' in timeframe_code or '1D' in timeframe_code:
        return 0.7
    if '1w' in timeframe_code:
        return 7.0 * 0.7
    if '1mo' in timeframe_code:
        return 30.0 * 0.7
    return 0.6


def prepare_plot_payload(df, timeframe_code):
    """
    Готовит массивы данных для отрисовки свечей и объемов.
    """
    width_days = calculate_candle_width(timeframe_code, df)
    timestamps = np.array([date2num(ts) for ts in df.index])
    opens = df['Open'].astype(float).values
    closes = df['Close'].astype(float).values
    highs = df['High'].astype(float).values
    lows = df['Low'].astype(float).values
    volumes = df['Volume'].astype(float).values

    colors = np.where(closes >= opens, UIConfig.CANDLE_BULLISH_COLOR, UIConfig.CANDLE_BEARISH_COLOR)

    max_draw = 500
    if len(timestamps) > max_draw:
        step = len(timestamps) // max_draw
        indices = list(range(0, len(timestamps), step))[:max_draw]
        timestamps = timestamps[indices]
        opens = opens[indices]
        closes = closes[indices]
        highs = highs[indices]
        lows = lows[indices]
        volumes = volumes[indices]
        colors = colors[indices]

    return {
        'timestamps': timestamps,
        'opens': opens,
        'closes': closes,
        'highs': highs,
        'lows': lows,
        'volumes': volumes,
        'colors': colors,
        'width_days': width_days
    }

