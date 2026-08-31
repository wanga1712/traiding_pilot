"""Volatility: ATR, Bollinger, realized vol, range stats — segment-aware ATR."""
from __future__ import annotations

import numpy as np

from .bars import BarArrays, contiguous_ok, displayed_at_for
from .math_core import rma, rolling_std, sma, true_range
from .segments import segment_start_for
from .types import IndicatorSample


def compute_atr_series(arrays: BarArrays, *, period: int = 14) -> list[IndicatorSample]:
    tr = true_range(arrays.high, arrays.low, arrays.close, gap_flags=arrays.gap_flags)
    atr = rma(tr, period, gap_flags=arrays.gap_flags)
    samples: list[IndicatorSample] = []
    for i in range(len(arrays.close)):
        calc_at = arrays.close_time[i]
        disp = displayed_at_for(arrays.close_time, arrays.open_time, i, 0)
        seg_start = segment_start_for(arrays.gap_flags, i)
        if i - seg_start + 1 < period or np.isnan(atr[i]):
            samples.append(
                IndicatorSample(calc_at, calc_at, disp, {"atr": None, "atr_norm": None}, valid=False, invalid_reason="warmup")
            )
            continue
        if not contiguous_ok(arrays.gap_flags, seg_start, i):
            samples.append(
                IndicatorSample(
                    calc_at, calc_at, disp, {"atr": None, "atr_norm": None}, valid=False, invalid_reason="insufficient_contiguous_history"
                )
            )
            continue
        av = float(atr[i])
        price = float(arrays.close[i])
        samples.append(
            IndicatorSample(
                calc_at, calc_at, disp,
                {"atr": av, "atr_norm": av / price if price else None},
                {}, True,
            )
        )
    return samples


def compute_bollinger_series(
    arrays: BarArrays,
    *,
    period: int = 20,
    std_mult: float = 2.0,
) -> list[IndicatorSample]:
    mid = sma(arrays.close, period)
    sd = rolling_std(arrays.close, period)
    samples: list[IndicatorSample] = []
    for i in range(len(arrays.close)):
        calc_at = arrays.close_time[i]
        disp = displayed_at_for(arrays.close_time, arrays.open_time, i, 0)
        if i < period - 1 or np.isnan(mid[i]) or np.isnan(sd[i]):
            samples.append(
                IndicatorSample(
                    calc_at, calc_at, disp,
                    {"mid": None, "upper": None, "lower": None, "width": None, "pct_b": None},
                    valid=False, invalid_reason="warmup",
                )
            )
            continue
        if not contiguous_ok(arrays.gap_flags, i - period + 1, i):
            samples.append(
                IndicatorSample(
                    calc_at, calc_at, disp,
                    {"mid": None, "upper": None, "lower": None, "width": None, "pct_b": None},
                    valid=False, invalid_reason="insufficient_contiguous_history",
                )
            )
            continue
        m, s = float(mid[i]), float(sd[i])
        upper = m + std_mult * s
        lower = m - std_mult * s
        width = (upper - lower) / m if m else None
        pct_b = None if upper == lower else (float(arrays.close[i]) - lower) / (upper - lower)
        samples.append(
            IndicatorSample(
                calc_at, calc_at, disp,
                {"mid": m, "upper": upper, "lower": lower, "width": width, "pct_b": pct_b},
                {}, True,
            )
        )
    return samples


def compute_realized_vol_series(arrays: BarArrays, *, period: int = 20) -> list[IndicatorSample]:
    logret = np.full(len(arrays.close), np.nan)
    for i in range(1, len(arrays.close)):
        if arrays.close[i - 1] > 0 and arrays.close[i] > 0:
            logret[i] = np.log(arrays.close[i] / arrays.close[i - 1])
    vol = rolling_std(logret, period)
    tr = true_range(arrays.high, arrays.low, arrays.close, gap_flags=arrays.gap_flags)
    samples: list[IndicatorSample] = []
    for i in range(len(arrays.close)):
        calc_at = arrays.close_time[i]
        disp = displayed_at_for(arrays.close_time, arrays.open_time, i, 0)
        if i < period or np.isnan(vol[i]):
            samples.append(
                IndicatorSample(
                    calc_at, calc_at, disp,
                    {"realized_vol": None, "tr": None, "range_abs": None},
                    valid=False, invalid_reason="warmup",
                )
            )
            continue
        rng = float(arrays.high[i] - arrays.low[i])
        window_tr = tr[i - period + 1 : i + 1]
        mean_tr = float(np.nanmean(window_tr))
        samples.append(
            IndicatorSample(
                calc_at, calc_at, disp,
                {
                    "realized_vol": float(vol[i]),
                    "tr": float(tr[i]),
                    "range_abs": rng,
                    "range_expansion": float(tr[i]) / mean_tr if mean_tr else None,
                    "range_contraction": mean_tr / float(tr[i]) if tr[i] else None,
                },
                {}, True,
            )
        )
    return samples
