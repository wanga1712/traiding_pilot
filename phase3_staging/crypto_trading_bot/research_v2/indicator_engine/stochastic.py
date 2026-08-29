"""Causal Stochastic Oscillator (+ optional DISPLAY displacement)."""
from __future__ import annotations

import numpy as np

from .bars import BarArrays, contiguous_ok, displayed_at_for
from .math_core import slope_last, sma
from .types import IndicatorSample


def _stoch_raw(high: np.ndarray, low: np.ndarray, close: np.ndarray, k_period: int) -> np.ndarray:
    out = np.full(len(close), np.nan, dtype=float)
    for i in range(k_period - 1, len(close)):
        hh = float(np.max(high[i - k_period + 1 : i + 1]))
        ll = float(np.min(low[i - k_period + 1 : i + 1]))
        if hh == ll:
            out[i] = 50.0
        else:
            out[i] = (float(close[i]) - ll) / (hh - ll) * 100.0
    return out


def compute_stochastic_series(
    arrays: BarArrays,
    *,
    k_period: int = 14,
    k_smooth: int = 3,
    d_period: int = 3,
    display_shift: int = 0,
    overbought: float = 80.0,
    oversold: float = 20.0,
) -> list[IndicatorSample]:
    raw = _stoch_raw(arrays.high, arrays.low, arrays.close, k_period)
    k = sma(raw, k_smooth)
    d = sma(k, d_period)
    warmup = k_period + k_smooth + d_period - 3
    samples: list[IndicatorSample] = []

    for i in range(len(arrays.close)):
        calc_at = arrays.close_time[i]
        disp = displayed_at_for(arrays.close_time, arrays.open_time, i, display_shift)
        need_start = i - (k_period + k_smooth + d_period - 3)
        if i < warmup or np.isnan(k[i]) or np.isnan(d[i]):
            samples.append(
                IndicatorSample(
                    calculated_at=calc_at,
                    available_at=calc_at,
                    displayed_at=disp,
                    values={"k": None, "d": None},
                    valid=False,
                    invalid_reason="warmup",
                )
            )
            continue
        if need_start < 0 or not contiguous_ok(arrays.gap_flags, max(0, need_start), i):
            samples.append(
                IndicatorSample(
                    calculated_at=calc_at,
                    available_at=calc_at,
                    displayed_at=disp,
                    values={"k": None, "d": None},
                    valid=False,
                    invalid_reason="insufficient_contiguous_history",
                )
            )
            continue

        kv, dv = float(k[i]), float(d[i])
        k_prev = float(k[i - 1]) if i > 0 and not np.isnan(k[i - 1]) else None
        d_prev = float(d[i - 1]) if i > 0 and not np.isnan(d[i - 1]) else None

        prim: dict = {
            "OVERBOUGHT": kv >= overbought,
            "OVERSOLD": kv <= oversold,
            "SLOPE_K": slope_last(k, i),
            "SLOPE_D": slope_last(d, i),
            "DISTANCE_TO_OVERBOUGHT": overbought - kv,
            "DISTANCE_TO_OVERSOLD": kv - oversold,
            "K_CROSS_UP_D": False,
            "K_CROSS_DOWN_D": False,
            "K_CROSS_UP_LEVEL": False,
            "K_CROSS_DOWN_LEVEL": False,
        }
        if k_prev is not None and d_prev is not None:
            prim["K_CROSS_UP_D"] = k_prev <= d_prev and kv > dv
            prim["K_CROSS_DOWN_D"] = k_prev >= d_prev and kv < dv
            prim["K_CROSS_UP_LEVEL"] = k_prev <= oversold and kv > oversold
            prim["K_CROSS_DOWN_LEVEL"] = k_prev >= overbought and kv < overbought

        samples.append(
            IndicatorSample(
                calculated_at=calc_at,
                available_at=calc_at,
                displayed_at=disp,
                values={"k": kv, "d": dv},
                signal_primitives=prim,
                valid=True,
            )
        )
    return samples
