"""DiNapoli Detrended Oscillator reference — DNO = Close - SMA(N)."""
from __future__ import annotations

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.bars import BarArrays, contiguous_ok, displayed_at_for
from crypto_trading_bot.research_v2.indicator_engine.math_core import sma
from crypto_trading_bot.research_v2.indicator_engine.segments import same_segment
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


def _index_valid(i: int, *, period: int, dno: np.ndarray, gap_flags: np.ndarray) -> bool:
    if i < period - 1 or np.isnan(dno[i]):
        return False
    return contiguous_ok(gap_flags, i - period + 1, i)


def compute_dno_feature_series(
    arrays: BarArrays,
    *,
    period: int = DNO_DEFAULT_PERIOD,
    display_shift: int = 0,
    atr: np.ndarray | None = None,
) -> list[IndicatorSample]:
    dno, _ = compute_dno_series(arrays, period=period)
    n = len(arrays.close)
    valid_flags = [_index_valid(i, period=period, dno=dno, gap_flags=arrays.gap_flags) for i in range(n)]
    samples: list[IndicatorSample] = []

    for i in range(n):
        calc_at = arrays.close_time[i]
        disp = displayed_at_for(arrays.close_time, arrays.open_time, i, display_shift)
        if not valid_flags[i]:
            samples.append(
                IndicatorSample(calc_at, calc_at, disp, {"dno": None}, valid=False, invalid_reason="warmup")
            )
            continue
        dv = float(dno[i])
        prev = float(dno[i - 1]) if i > 0 and same_segment(arrays.gap_flags, i - 1, i) and not np.isnan(dno[i - 1]) else None
        ma3 = float(dno[i - 3]) if i >= 3 and same_segment(arrays.gap_flags, i - 3, i) and not np.isnan(dno[i - 3]) else None
        atr_i = float(atr[i]) if atr is not None and i < len(atr) and not np.isnan(atr[i]) else None
        prim = {
            "DNO_VALUE": dv,
            "DNO_SLOPE_1": (dv - prev) if prev is not None else None,
            "DNO_SLOPE_3": (dv - ma3) if ma3 is not None else None,
            "DNO_ZERO_CROSS_UP": bool(prev is not None and prev <= 0 and dv > 0),
            "DNO_ZERO_CROSS_DOWN": bool(prev is not None and prev >= 0 and dv < 0),
            "DNO_DISTANCE_FROM_ZERO": abs(dv),
            "DNO_ABS": abs(dv),
            "DNO_ATR_NORMALIZED": (dv / atr_i) if atr_i and atr_i != 0 else None,
        }
        samples.append(
            IndicatorSample(calc_at, calc_at, disp, {"dno": dv}, prim, True)
        )
    return samples
