"""Extended MA / DMA feature extraction with true display-aligned features."""
from __future__ import annotations

from typing import Any

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.bars import BarArrays, contiguous_ok, displayed_at_for
from crypto_trading_bot.research_v2.indicator_engine.math_core import ema, sma, slope_last, wma
from crypto_trading_bot.research_v2.indicator_engine.types import IndicatorSample

from .aligned_features import cross_down, cross_up, source_index, source_sample_valid


def _ma_fn(kind: str):
    return {"SMA": sma, "EMA": ema, "WMA": wma}[kind]


def _ma_at(ma: np.ndarray, i: int) -> float | None:
    if i < 0 or i >= len(ma) or np.isnan(ma[i]):
        return None
    return float(ma[i])


def _index_valid(
    i: int,
    *,
    period: int,
    ma: np.ndarray,
    gap_flags: np.ndarray,
) -> bool:
    if i < period - 1 or np.isnan(ma[i]):
        return False
    return contiguous_ok(gap_flags, i - period + 1, i)


def _build_ma_features_at(
    *,
    i: int,
    price: float,
    prev_price: float | None,
    ma: np.ndarray,
    display_shift: int,
    atr_i: float | None,
    valid_flags: list[bool],
) -> dict[str, Any]:
    mv = _ma_at(ma, i)
    if mv is None:
        return {}

    dist = price - mv
    dist_pct = (dist / mv * 100.0) if mv else None
    dist_atr = (dist / atr_i) if atr_i and atr_i != 0 else None
    prev_mv = _ma_at(ma, i - 1)
    slope1 = (mv - prev_mv) if prev_mv is not None else None
    ma3 = _ma_at(ma, i - 3)
    slope3 = (mv - ma3) if ma3 is not None else None
    prev_slope1 = None
    if i > 1:
        pm, ppm = _ma_at(ma, i - 1), _ma_at(ma, i - 2)
        if pm is not None and ppm is not None:
            prev_slope1 = pm - ppm

    out: dict[str, Any] = {
        "MA_VALUE": mv,
        "PRICE_MINUS_MA": dist,
        "PRICE_MINUS_MA_PCT": dist_pct,
        "PRICE_MINUS_MA_ATR": dist_atr,
        "MA_SLOPE_1": slope1,
        "MA_SLOPE_3": slope3,
        "PRICE_CROSS_UP_MA": cross_up(prev_price, price, prev_mv, mv),
        "PRICE_CROSS_DOWN_MA": cross_down(prev_price, price, prev_mv, mv),
        "MA_SLOPE_TURN_UP": bool(slope1 is not None and prev_slope1 is not None and prev_slope1 <= 0 and slope1 > 0),
        "MA_SLOPE_TURN_DOWN": bool(slope1 is not None and prev_slope1 is not None and prev_slope1 >= 0 and slope1 < 0),
    }

    if display_shift == 0:
        out.update(
            {
                "DISPLAY_ALIGNED_MA_VALUE": mv,
                "DISPLAY_ALIGNED_PRICE_MINUS_MA": dist,
                "DISPLAY_ALIGNED_PRICE_MINUS_MA_PCT": dist_pct,
                "DISPLAY_ALIGNED_PRICE_MINUS_MA_ATR": dist_atr,
                "DISPLAY_ALIGNED_MA_SLOPE_1": slope1,
                "DISPLAY_ALIGNED_MA_SLOPE_3": slope3,
                "DISPLAY_ALIGNED_PRICE_CROSS_UP_MA": out["PRICE_CROSS_UP_MA"],
                "DISPLAY_ALIGNED_PRICE_CROSS_DOWN_MA": out["PRICE_CROSS_DOWN_MA"],
                "DISPLAY_ALIGNED_MA_SLOPE_TURN_UP": out["MA_SLOPE_TURN_UP"],
                "DISPLAY_ALIGNED_MA_SLOPE_TURN_DOWN": out["MA_SLOPE_TURN_DOWN"],
            }
        )
        return out

    if not source_sample_valid(valid_flags, i, display_shift):
        out.update({k: None for k in (
            "DISPLAY_ALIGNED_MA_VALUE",
            "DISPLAY_ALIGNED_PRICE_MINUS_MA",
            "DISPLAY_ALIGNED_PRICE_MINUS_MA_PCT",
            "DISPLAY_ALIGNED_PRICE_MINUS_MA_ATR",
            "DISPLAY_ALIGNED_MA_SLOPE_1",
            "DISPLAY_ALIGNED_MA_SLOPE_3",
            "DISPLAY_ALIGNED_PRICE_CROSS_UP_MA",
            "DISPLAY_ALIGNED_PRICE_CROSS_DOWN_MA",
            "DISPLAY_ALIGNED_MA_SLOPE_TURN_UP",
            "DISPLAY_ALIGNED_MA_SLOPE_TURN_DOWN",
        )})
        return out

    src = source_index(i, display_shift)
    assert src is not None
    da_mv = _ma_at(ma, src)
    if da_mv is None:
        return out
    da_prev_mv = _ma_at(ma, src - 1) if src > 0 else None
    da_prev_src = source_index(i - 1, display_shift) if i > 0 else None
    da_prev_mv_alt = _ma_at(ma, da_prev_src) if da_prev_src is not None else None

    da_dist = price - da_mv
    da_slope1 = (da_mv - da_prev_mv) if da_prev_mv is not None else None
    da_ma3 = _ma_at(ma, src - 3) if src is not None else None
    da_slope3 = (da_mv - da_ma3) if da_ma3 is not None else None
    da_ps1 = None
    if src > 1:
        a, b = _ma_at(ma, src - 1), _ma_at(ma, src - 2)
        if a is not None and b is not None:
            da_ps1 = a - b
    out.update(
        {
            "DISPLAY_ALIGNED_MA_VALUE": da_mv,
            "DISPLAY_ALIGNED_PRICE_MINUS_MA": da_dist,
            "DISPLAY_ALIGNED_PRICE_MINUS_MA_PCT": (da_dist / da_mv * 100.0) if da_mv else None,
            "DISPLAY_ALIGNED_PRICE_MINUS_MA_ATR": (da_dist / atr_i) if atr_i and atr_i != 0 else None,
            "DISPLAY_ALIGNED_MA_SLOPE_1": da_slope1,
            "DISPLAY_ALIGNED_MA_SLOPE_3": da_slope3,
            "DISPLAY_ALIGNED_PRICE_CROSS_UP_MA": cross_up(prev_price, price, da_prev_mv_alt, da_mv),
            "DISPLAY_ALIGNED_PRICE_CROSS_DOWN_MA": cross_down(prev_price, price, da_prev_mv_alt, da_mv),
            "DISPLAY_ALIGNED_MA_SLOPE_TURN_UP": bool(
                da_slope1 is not None and da_ps1 is not None and da_ps1 <= 0 and da_slope1 > 0
            ),
            "DISPLAY_ALIGNED_MA_SLOPE_TURN_DOWN": bool(
                da_slope1 is not None and da_ps1 is not None and da_ps1 >= 0 and da_slope1 < 0
            ),
        }
    )
    return out


def compute_dma_feature_series(
    arrays: BarArrays,
    *,
    ma_type: str,
    period: int,
    display_shift: int,
    atr: np.ndarray | None = None,
) -> list[IndicatorSample]:
    fn = _ma_fn(ma_type)
    ma = fn(arrays.close, period)
    key = "ma"
    n = len(arrays.close)
    valid_flags = [
        _index_valid(i, period=period, ma=ma, gap_flags=arrays.gap_flags) for i in range(n)
    ]
    samples: list[IndicatorSample] = []
    for i in range(n):
        calc_at = arrays.close_time[i]
        disp = displayed_at_for(arrays.close_time, arrays.open_time, i, display_shift)
        if not valid_flags[i]:
            reason = "warmup" if i < period - 1 or np.isnan(ma[i]) else "insufficient_contiguous_history"
            samples.append(
                IndicatorSample(calc_at, calc_at, disp, {key: None}, valid=False, invalid_reason=reason)
            )
            continue
        mv = float(ma[i])
        price = float(arrays.close[i])
        prev_price = float(arrays.close[i - 1]) if i > 0 else None
        atr_i = float(atr[i]) if atr is not None and i < len(atr) and not np.isnan(atr[i]) else None
        prim = _build_ma_features_at(
            i=i,
            price=price,
            prev_price=prev_price,
            ma=ma,
            display_shift=display_shift,
            atr_i=atr_i,
            valid_flags=valid_flags,
        )
        samples.append(IndicatorSample(calc_at, calc_at, disp, {key: mv}, prim, True))
    return samples
