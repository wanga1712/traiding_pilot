"""DiNapoli Preferred Stochastic reference — modified recursive smoothing (not SMA).

Parameters: K_PERIOD=8, SLOWING=3, D_PERIOD=3

FastK[t] = 100 * (Close[t] - LowestLow_8) / (HighestHigh_8 - LowestLow_8)

Modified smoothing (NOT SMA(RAW_K,3) nor SMA(K,3)):
  K[t] = K[t-1] + (FastK[t] - K[t-1]) / SLOWING
  D[t] = D[t-1] + (K[t] - D[t-1]) / D_PERIOD

Initialization convention (documented):
  - First FastK available at index k_period - 1.
  - K[k_period-1] = FastK[k_period-1]  (seed)
  - D[k_period-1] = K[k_period-1]      (seed)
  - Recursive smoothing from k_period onward.

Reference status: DINAPOLI_REFERENCE_IMPLEMENTATION (reconstructed from public parameters).
"""
from __future__ import annotations

import numpy as np

from .bars import BarArrays, contiguous_ok, displayed_at_for
from .math_core import slope_last
from .stochastic import _stoch_raw
from .types import IndicatorSample

K_PERIOD = 8
SLOWING = 3
D_PERIOD = 3

INIT_CONVENTION = "seed_k_and_d_at_first_fastk"


def compute_dinapoli_stoch_arrays(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    *,
    k_period: int = K_PERIOD,
    slowing: int = SLOWING,
    d_period: int = D_PERIOD,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    fast_k = _stoch_raw(high, low, close, k_period)
    n = len(close)
    k = np.full(n, np.nan, dtype=float)
    d = np.full(n, np.nan, dtype=float)

    first = k_period - 1
    if first < n and not np.isnan(fast_k[first]):
        k[first] = float(fast_k[first])
        d[first] = float(k[first])

    for i in range(first + 1, n):
        if np.isnan(fast_k[i]) or np.isnan(k[i - 1]):
            continue
        k[i] = k[i - 1] + (float(fast_k[i]) - k[i - 1]) / slowing
        if np.isnan(d[i - 1]):
            d[i] = k[i]
        else:
            d[i] = d[i - 1] + (k[i] - d[i - 1]) / d_period

    return fast_k, k, d


def compute_dinapoli_stochastic_series(
    arrays: BarArrays,
    *,
    k_period: int = K_PERIOD,
    slowing: int = SLOWING,
    d_period: int = D_PERIOD,
    display_shift: int = 0,
    overbought: float = 80.0,
    oversold: float = 20.0,
) -> list[IndicatorSample]:
    raw, k, d = compute_dinapoli_stoch_arrays(
        arrays.high, arrays.low, arrays.close, k_period=k_period, slowing=slowing, d_period=d_period
    )
    # Crosses/slopes need prior bar → first index k_period (one bar after seed)
    warmup = k_period
    samples: list[IndicatorSample] = []

    for i in range(len(arrays.close)):
        calc_at = arrays.close_time[i]
        disp = displayed_at_for(arrays.close_time, arrays.open_time, i, display_shift)
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
        need_start = max(0, k_period - 1)
        if not contiguous_ok(arrays.gap_flags, need_start, i):
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
        k_prev = float(k[i - 1])
        d_prev = float(d[i - 1])

        prim: dict = {
            "OVERBOUGHT": kv >= overbought,
            "OVERSOLD": kv <= oversold,
            "SLOPE_K": slope_last(k, i),
            "SLOPE_D": slope_last(d, i),
            "DISTANCE_TO_OVERBOUGHT": overbought - kv,
            "DISTANCE_TO_OVERSOLD": kv - oversold,
            "K_CROSS_UP_D": k_prev <= d_prev and kv > dv,
            "K_CROSS_DOWN_D": k_prev >= d_prev and kv < dv,
        }

        samples.append(
            IndicatorSample(
                calculated_at=calc_at,
                available_at=calc_at,
                displayed_at=disp,
                values={"k": kv, "d": dv, "raw_k": float(raw[i]) if not np.isnan(raw[i]) else None},
                signal_primitives=prim,
                valid=True,
            )
        )
    return samples
