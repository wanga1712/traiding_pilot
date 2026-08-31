"""Extended MA / DMA feature extraction with display alignment."""
from __future__ import annotations

from typing import Any

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.bars import BarArrays, contiguous_ok, displayed_at_for
from crypto_trading_bot.research_v2.indicator_engine.math_core import ema, sma, slope_last, wma
from crypto_trading_bot.research_v2.indicator_engine.types import IndicatorSample


def _ma_fn(kind: str):
    return {"SMA": sma, "EMA": ema, "WMA": wma}[kind]


def compute_dma_feature_series(
    arrays: BarArrays,
    *,
    ma_type: str,
    period: int,
    display_shift: int,
    atr: np.ndarray | None = None,
) -> list[IndicatorSample]:
    """Full DMA feature set per bar with explicit MA_VALUE + display-aligned form."""
    fn = _ma_fn(ma_type)
    ma = fn(arrays.close, period)
    key = "ma"
    samples: list[IndicatorSample] = []
    for i in range(len(arrays.close)):
        calc_at = arrays.close_time[i]
        disp = displayed_at_for(arrays.close_time, arrays.open_time, i, display_shift)
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
        prev_mv = float(ma[i - 1]) if i > 0 and not np.isnan(ma[i - 1]) else None
        prev_price = float(arrays.close[i - 1]) if i > 0 else None
        slope1 = slope_last(ma, i)
        slope3 = float(ma[i] - ma[i - 3]) if i >= 3 and not np.isnan(ma[i - 3]) else None
        prev_slope1 = slope_last(ma, i - 1) if i > 1 else None

        dist = price - mv
        dist_pct = (dist / mv * 100.0) if mv else None
        dist_atr = (dist / float(atr[i])) if atr is not None and i < len(atr) and not np.isnan(atr[i]) and atr[i] else None

        cross_up = cross_down = False
        if prev_price is not None and prev_mv is not None:
            cross_up = prev_price <= prev_mv and price > mv
            cross_down = prev_price >= prev_mv and price < mv

        turn_up = turn_down = False
        if slope1 is not None and prev_slope1 is not None:
            turn_up = prev_slope1 <= 0 and slope1 > 0
            turn_down = prev_slope1 >= 0 and slope1 < 0

        da_val = mv
        if display_shift > 0 and i >= display_shift and not np.isnan(ma[i - display_shift]):
            da_val = float(ma[i - display_shift])

        prim: dict[str, Any] = {
            "MA_VALUE": mv,
            "DISPLAY_ALIGNED_MA_VALUE": da_val,
            "PRICE_MINUS_MA": dist,
            "PRICE_MINUS_MA_PCT": dist_pct,
            "PRICE_MINUS_MA_ATR": dist_atr,
            "MA_SLOPE_1": slope1,
            "MA_SLOPE_3": slope3,
            "PRICE_CROSS_UP_MA": cross_up,
            "PRICE_CROSS_DOWN_MA": cross_down,
            "MA_SLOPE_TURN_UP": turn_up,
            "MA_SLOPE_TURN_DOWN": turn_down,
        }
        samples.append(IndicatorSample(calc_at, calc_at, disp, {key: mv}, prim, True))
    return samples
