"""Core moving averages and rolling helpers (vectorized)."""
from __future__ import annotations

import numpy as np


def sma(x: np.ndarray, period: int) -> np.ndarray:
    """Simple moving average. Windows containing NaN remain NaN (no poison via cumsum)."""
    out = np.full(len(x), np.nan, dtype=float)
    if period <= 0 or len(x) < period:
        return out
    xf = x.astype(float)
    for i in range(period - 1, len(xf)):
        window = xf[i - period + 1 : i + 1]
        if np.any(np.isnan(window)):
            continue
        out[i] = float(np.mean(window))
    return out


def ema(x: np.ndarray, period: int, *, adjust: bool = False) -> np.ndarray:
    """Standard recursive EMA; first value = SMA of first `period` bars (TradingView/common)."""
    out = np.full(len(x), np.nan, dtype=float)
    if period <= 0 or len(x) < period:
        return out
    alpha = 2.0 / (period + 1.0)
    seed = float(np.mean(x[:period]))
    out[period - 1] = seed
    for i in range(period, len(x)):
        out[i] = alpha * float(x[i]) + (1.0 - alpha) * out[i - 1]
    return out


def wma(x: np.ndarray, period: int) -> np.ndarray:
    out = np.full(len(x), np.nan, dtype=float)
    if period <= 0 or len(x) < period:
        return out
    weights = np.arange(1, period + 1, dtype=float)
    wsum = weights.sum()
    for i in range(period - 1, len(x)):
        window = x[i - period + 1 : i + 1]
        out[i] = float(np.dot(window, weights) / wsum)
    return out


def true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    tr = np.full(len(close), np.nan, dtype=float)
    if len(close) == 0:
        return tr
    tr[0] = float(high[0] - low[0])
    for i in range(1, len(close)):
        tr[i] = max(
            float(high[i] - low[i]),
            abs(float(high[i] - close[i - 1])),
            abs(float(low[i] - close[i - 1])),
        )
    return tr


def rma(x: np.ndarray, period: int) -> np.ndarray:
    """Wilder RMA / smoothed MA used by RSI/ATR/ADX."""
    out = np.full(len(x), np.nan, dtype=float)
    if period <= 0 or len(x) < period:
        return out
    out[period - 1] = float(np.mean(x[:period]))
    for i in range(period, len(x)):
        out[i] = (out[i - 1] * (period - 1) + float(x[i])) / period
    return out


def rolling_std(x: np.ndarray, period: int) -> np.ndarray:
    out = np.full(len(x), np.nan, dtype=float)
    if period <= 1 or len(x) < period:
        return out
    for i in range(period - 1, len(x)):
        out[i] = float(np.std(x[i - period + 1 : i + 1], ddof=0))
    return out


def slope_last(series: np.ndarray, i: int) -> float | None:
    if i <= 0 or i >= len(series):
        return None
    a, b = series[i - 1], series[i]
    if np.isnan(a) or np.isnan(b):
        return None
    return float(b - a)


def cross_up(a_prev: float, a_now: float, b_prev: float, b_now: float) -> bool:
    return a_prev <= b_prev and a_now > b_now


def cross_down(a_prev: float, a_now: float, b_prev: float, b_now: float) -> bool:
    return a_prev >= b_prev and a_now < b_now
