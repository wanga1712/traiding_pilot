"""Trend MAs: SMA / EMA / WMA with cross and distance primitives."""
from __future__ import annotations

import numpy as np

from .bars import BarArrays, contiguous_ok, displayed_at_for
from .math_core import ema, sma, slope_last, wma
from .types import IndicatorSample


def _ma_fn(kind: str):
    return {"SMA": sma, "EMA": ema, "WMA": wma}[kind]


def compute_ma_series(
    arrays: BarArrays,
    *,
    kind: str,
    period: int,
) -> list[IndicatorSample]:
    fn = _ma_fn(kind)
    ma = fn(arrays.close, period)
    key = kind.lower()
    samples: list[IndicatorSample] = []
    for i in range(len(arrays.close)):
        calc_at = arrays.close_time[i]
        disp = displayed_at_for(arrays.close_time, arrays.open_time, i, 0)
        if i < period - 1 or np.isnan(ma[i]):
            samples.append(
                IndicatorSample(calc_at, calc_at, disp, {key: None}, valid=False, invalid_reason="warmup")
            )
            continue
        if not contiguous_ok(arrays.gap_flags, i - period + 1, i):
            samples.append(
                IndicatorSample(
                    calc_at, calc_at, disp, {key: None}, valid=False, invalid_reason="insufficient_contiguous_history"
                )
            )
            continue
        mv = float(ma[i])
        price = float(arrays.close[i])
        prim = {
            "PRICE_ABOVE_MA": price > mv,
            "PRICE_BELOW_MA": price < mv,
            "PRICE_CROSS_UP_MA": False,
            "PRICE_CROSS_DOWN_MA": False,
            "MA_SLOPE": slope_last(ma, i),
            "DISTANCE_PRICE_MA_ABS": price - mv,
            "DISTANCE_PRICE_MA_PCT": (price - mv) / mv * 100.0 if mv else None,
        }
        if i > 0 and not np.isnan(ma[i - 1]):
            pp, pm = float(arrays.close[i - 1]), float(ma[i - 1])
            prim["PRICE_CROSS_UP_MA"] = pp <= pm and price > mv
            prim["PRICE_CROSS_DOWN_MA"] = pp >= pm and price < mv
        samples.append(IndicatorSample(calc_at, calc_at, disp, {key: mv}, prim, True))
    return samples


def compute_ma_pair_distance(
    arrays: BarArrays,
    *,
    kind: str,
    fast: int,
    slow: int,
) -> list[IndicatorSample]:
    fn = _ma_fn(kind)
    f = fn(arrays.close, fast)
    s = fn(arrays.close, slow)
    samples: list[IndicatorSample] = []
    for i in range(len(arrays.close)):
        calc_at = arrays.close_time[i]
        disp = displayed_at_for(arrays.close_time, arrays.open_time, i, 0)
        if np.isnan(f[i]) or np.isnan(s[i]):
            samples.append(
                IndicatorSample(calc_at, calc_at, disp, {"fast": None, "slow": None}, valid=False, invalid_reason="warmup")
            )
            continue
        fv, sv = float(f[i]), float(s[i])
        prim = {
            "MA_CROSS_UP": False,
            "MA_CROSS_DOWN": False,
            "DISTANCE_BETWEEN_MAS_ABS": fv - sv,
            "DISTANCE_BETWEEN_MAS_PCT": (fv - sv) / sv * 100.0 if sv else None,
        }
        if i > 0 and not np.isnan(f[i - 1]) and not np.isnan(s[i - 1]):
            prim["MA_CROSS_UP"] = f[i - 1] <= s[i - 1] and fv > sv
            prim["MA_CROSS_DOWN"] = f[i - 1] >= s[i - 1] and fv < sv
        samples.append(IndicatorSample(calc_at, calc_at, disp, {"fast": fv, "slow": sv}, prim, True))
    return samples
