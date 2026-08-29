"""Causal RSI (Wilder)."""
from __future__ import annotations

import numpy as np

from .bars import BarArrays, contiguous_ok, displayed_at_for
from .math_core import rma, slope_last
from .types import IndicatorSample


def compute_rsi_series(
    arrays: BarArrays,
    *,
    period: int = 14,
    overbought: float = 70.0,
    oversold: float = 30.0,
) -> list[IndicatorSample]:
    n = len(arrays.close)
    delta = np.diff(arrays.close, prepend=np.nan)
    gain = np.where(np.isnan(delta), np.nan, np.maximum(delta, 0.0))
    loss = np.where(np.isnan(delta), np.nan, np.maximum(-delta, 0.0))
    # Wilder starts after period changes (index period)
    avg_gain = np.full(n, np.nan)
    avg_loss = np.full(n, np.nan)
    rsi = np.full(n, np.nan)
    if n > period:
        avg_gain[period] = float(np.mean(gain[1 : period + 1]))
        avg_loss[period] = float(np.mean(loss[1 : period + 1]))
        for i in range(period + 1, n):
            avg_gain[i] = (avg_gain[i - 1] * (period - 1) + float(gain[i])) / period
            avg_loss[i] = (avg_loss[i - 1] * (period - 1) + float(loss[i])) / period
        for i in range(period, n):
            if avg_loss[i] == 0:
                rsi[i] = 100.0
            else:
                rs = avg_gain[i] / avg_loss[i]
                rsi[i] = 100.0 - (100.0 / (1.0 + rs))

    samples: list[IndicatorSample] = []
    for i in range(n):
        calc_at = arrays.close_time[i]
        disp = displayed_at_for(arrays.close_time, arrays.open_time, i, 0)
        if i < period or np.isnan(rsi[i]):
            samples.append(
                IndicatorSample(
                    calculated_at=calc_at,
                    available_at=calc_at,
                    displayed_at=disp,
                    values={"rsi": None},
                    valid=False,
                    invalid_reason="warmup",
                )
            )
            continue
        if not contiguous_ok(arrays.gap_flags, i - period, i):
            samples.append(
                IndicatorSample(
                    calculated_at=calc_at,
                    available_at=calc_at,
                    displayed_at=disp,
                    values={"rsi": None},
                    valid=False,
                    invalid_reason="insufficient_contiguous_history",
                )
            )
            continue
        rv = float(rsi[i])
        prev = float(rsi[i - 1]) if i > 0 and not np.isnan(rsi[i - 1]) else None
        prim = {
            "OVERBOUGHT": rv >= overbought,
            "OVERSOLD": rv <= oversold,
            "RSI_SLOPE": slope_last(rsi, i),
            "RSI_CROSS_UP_30": False,
            "RSI_CROSS_DOWN_70": False,
            "RSI_CROSS_UP_50": False,
            "RSI_CROSS_DOWN_50": False,
        }
        if prev is not None:
            prim["RSI_CROSS_UP_30"] = prev <= 30 and rv > 30
            prim["RSI_CROSS_DOWN_70"] = prev >= 70 and rv < 70
            prim["RSI_CROSS_UP_50"] = prev <= 50 and rv > 50
            prim["RSI_CROSS_DOWN_50"] = prev >= 50 and rv < 50
        samples.append(
            IndicatorSample(
                calculated_at=calc_at,
                available_at=calc_at,
                displayed_at=disp,
                values={"rsi": rv},
                signal_primitives=prim,
                valid=True,
            )
        )
    return samples
