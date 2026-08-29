"""DiNapoli-style DMA: SMA(period) with DISPLAY displacement only."""
from __future__ import annotations

from typing import Any

import numpy as np

from .bars import BarArrays, contiguous_ok, displayed_at_for
from .math_core import sma, slope_last
from .types import IndicatorSample
from .version import INDICATOR_ENGINE_VERSION


def compute_dma_series(
    arrays: BarArrays,
    *,
    period: int,
    display_shift: int,
    atr: np.ndarray | None = None,
) -> list[IndicatorSample]:
    """
    SMA uses only closed bars through index i.
    CALCULATED_AT = AVAILABLE_AT = close_time[i]
    DISPLAYED_AT = open_time[i + display_shift] when that bar exists (chart only).
    """
    ma = sma(arrays.close, period)
    samples: list[IndicatorSample] = []
    for i in range(len(arrays.close)):
        calc_at = arrays.close_time[i]
        disp = displayed_at_for(arrays.close_time, arrays.open_time, i, display_shift)
        if i < period - 1 or np.isnan(ma[i]):
            samples.append(
                IndicatorSample(
                    calculated_at=calc_at,
                    available_at=calc_at,
                    displayed_at=disp,
                    values={"dma": None},
                    signal_primitives={},
                    valid=False,
                    invalid_reason="warmup",
                )
            )
            continue
        if not contiguous_ok(arrays.gap_flags, i - period + 1, i):
            samples.append(
                IndicatorSample(
                    calculated_at=calc_at,
                    available_at=calc_at,
                    displayed_at=disp,
                    values={"dma": None},
                    signal_primitives={},
                    valid=False,
                    invalid_reason="insufficient_contiguous_history",
                )
            )
            continue

        dma_v = float(ma[i])
        price = float(arrays.close[i])
        prev_price = float(arrays.close[i - 1]) if i > 0 else None
        prev_dma = float(ma[i - 1]) if i > 0 and not np.isnan(ma[i - 1]) else None

        price_above = price > dma_v
        price_below = price < dma_v
        cross_up = False
        cross_down = False
        if prev_price is not None and prev_dma is not None:
            cross_up = prev_price <= prev_dma and price > dma_v
            cross_down = prev_price >= prev_dma and price < dma_v

        dist_abs = price - dma_v
        dist_pct = (dist_abs / dma_v * 100.0) if dma_v != 0 else None
        dist_atr = None
        if atr is not None and i < len(atr) and not np.isnan(atr[i]) and atr[i] != 0:
            dist_atr = dist_abs / float(atr[i])

        samples.append(
            IndicatorSample(
                calculated_at=calc_at,
                available_at=calc_at,
                displayed_at=disp,
                values={"dma": dma_v},
                signal_primitives={
                    "PRICE_ABOVE_DMA": price_above,
                    "PRICE_BELOW_DMA": price_below,
                    "PRICE_CROSS_UP_DMA": cross_up,
                    "PRICE_CROSS_DOWN_DMA": cross_down,
                    "DMA_SLOPE": slope_last(ma, i),
                    "DISTANCE_PRICE_DMA_ABS": dist_abs,
                    "DISTANCE_PRICE_DMA_PCT": dist_pct,
                    "DISTANCE_PRICE_DMA_ATR": dist_atr,
                },
                valid=True,
            )
        )
    return samples


def dma_meta(period: int, display_shift: int) -> dict[str, Any]:
    return {
        "indicator_engine_version": INDICATOR_ENGINE_VERSION,
        "family": "DMA",
        "period": period,
        "display_shift": display_shift,
        "authority": "DINAPOLI_STYLE_DISPLAY_DISPLACEMENT",
    }
