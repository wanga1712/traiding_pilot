"""DiNapoli Detrended Oscillator reference — DNO = Close - SMA(N)."""
from __future__ import annotations

from typing import Any

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.bars import BarArrays, contiguous_ok, displayed_at_for
from crypto_trading_bot.research_v2.indicator_engine.math_core import sma
from crypto_trading_bot.research_v2.indicator_engine.segments import iter_segments, same_segment, segment_start_for
from crypto_trading_bot.research_v2.indicator_engine.types import IndicatorSample

DNO_REFERENCE_VERSION = "DINAPOLI_DETRENDED_OSCILLATOR_REFERENCE_V1"
DNO_DEFAULT_PERIOD = 7
REFERENCE_STATUS = "DINAPOLI_NONPROPRIETARY_REFERENCE"


def compute_dno_series(
    arrays: BarArrays,
    *,
    period: int = DNO_DEFAULT_PERIOD,
    display_shift: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (dno, sma) arrays aligned to close."""
    ma = sma(arrays.close, period)
    dno = arrays.close - ma
    return dno, ma


def compute_masked_dno_series(
    arrays: BarArrays,
    *,
    period: int = DNO_DEFAULT_PERIOD,
) -> np.ndarray:
    """
    Segment-masked DNO for extrema/predictor use.

    First N-1 bars of each segment are NaN; cross-gap SMA values never participate.
    """
    dno_raw, _ = compute_dno_series(arrays, period=period)
    masked = np.full_like(dno_raw, np.nan, dtype=float)
    gap_flags = arrays.gap_flags
    for start, end in iter_segments(gap_flags, len(dno_raw)):
        for i in range(start, end + 1):
            if i < start + period - 1:
                continue
            if i - period + 1 < start:
                continue
            if contiguous_ok(gap_flags, i - period + 1, i):
                masked[i] = dno_raw[i]
    return masked


def masked_dno_valid(
    i: int,
    masked_dno: np.ndarray,
    gap_flags: np.ndarray,
    *,
    period: int,
) -> bool:
    if i < 0 or i >= len(masked_dno) or np.isnan(masked_dno[i]):
        return False
    seg_start = segment_start_for(gap_flags, i)
    if i < seg_start + period - 1:
        return False
    return contiguous_ok(gap_flags, max(seg_start, i - period + 1), i)


def dno_primitives_at(
    arrays: BarArrays,
    idx: int,
    *,
    period: int = DNO_DEFAULT_PERIOD,
    masked_dno: np.ndarray | None = None,
    atr: np.ndarray | None = None,
) -> dict[str, Any]:
    """Signal primitives for one bar using segment-masked DNO semantics."""
    dno = masked_dno if masked_dno is not None else compute_masked_dno_series(arrays, period=period)
    gap_flags = arrays.gap_flags
    if not masked_dno_valid(idx, dno, gap_flags, period=period):
        return {}
    dv = float(dno[idx])
    prev_ok = idx > 0 and masked_dno_valid(idx - 1, dno, gap_flags, period=period) and same_segment(
        gap_flags, idx - 1, idx
    )
    prev = float(dno[idx - 1]) if prev_ok else None
    ma3_ok = (
        idx >= 3
        and masked_dno_valid(idx - 3, dno, gap_flags, period=period)
        and same_segment(gap_flags, idx - 3, idx)
    )
    ma3 = float(dno[idx - 3]) if ma3_ok else None
    atr_i = float(atr[idx]) if atr is not None and idx < len(atr) and not np.isnan(atr[idx]) else None
    return {
        "DNO_VALUE": dv,
        "DNO_SLOPE_1": (dv - prev) if prev is not None else None,
        "DNO_SLOPE_3": (dv - ma3) if ma3 is not None else None,
        "DNO_ZERO_CROSS_UP": bool(prev is not None and prev <= 0 and dv > 0),
        "DNO_ZERO_CROSS_DOWN": bool(prev is not None and prev >= 0 and dv < 0),
        "DNO_DISTANCE_FROM_ZERO": abs(dv),
        "DNO_ABS": abs(dv),
        "DNO_ATR_NORMALIZED": (dv / atr_i) if atr_i and atr_i != 0 else None,
    }


def compute_dno_feature_series(
    arrays: BarArrays,
    *,
    period: int = DNO_DEFAULT_PERIOD,
    display_shift: int = 0,
    atr: np.ndarray | None = None,
) -> list[IndicatorSample]:
    masked = compute_masked_dno_series(arrays, period=period)
    n = len(arrays.close)
    samples: list[IndicatorSample] = []

    for i in range(n):
        calc_at = arrays.close_time[i]
        disp = displayed_at_for(arrays.close_time, arrays.open_time, i, display_shift)
        prim = dno_primitives_at(arrays, i, period=period, masked_dno=masked, atr=atr)
        if not prim:
            samples.append(
                IndicatorSample(calc_at, calc_at, disp, {"dno": None}, valid=False, invalid_reason="warmup")
            )
            continue
        samples.append(
            IndicatorSample(calc_at, calc_at, disp, {"dno": prim["DNO_VALUE"]}, prim, True)
        )
    return samples
