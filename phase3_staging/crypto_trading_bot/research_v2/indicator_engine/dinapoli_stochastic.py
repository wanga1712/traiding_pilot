"""DiNapoli Preferred Stochastic reference — modified recursive smoothing with SMA seed."""
from __future__ import annotations

import numpy as np

from .bars import BarArrays, contiguous_ok, displayed_at_for
from .math_core import slope_last
from .segments import iter_segments, same_segment, segment_start_for
from .stochastic import _stoch_raw
from .types import IndicatorSample

K_PERIOD = 8
SLOWING = 3
D_PERIOD = 3

INIT_CONVENTION = "sma_seed_fastk_window_then_k_window_for_d"
THRESHOLD_PROFILE = "PROJECT_GENERIC_80_20"


def dinapoli_stoch_warmup_indices(
    *,
    k_period: int = K_PERIOD,
    slowing: int = SLOWING,
    d_period: int = D_PERIOD,
) -> dict[str, int]:
    fastk_first = k_period - 1
    k_seed_index = fastk_first + slowing - 1
    d_seed_index = k_seed_index + d_period - 1
    first_full_feature_index = d_seed_index + 1
    return {
        "fastk_first": fastk_first,
        "k_seed_index": k_seed_index,
        "d_seed_index": d_seed_index,
        "first_full_feature_index": first_full_feature_index,
    }


def _fast_k_segmented(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    *,
    k_period: int,
    gap_flags: np.ndarray,
) -> np.ndarray:
    raw = np.full(len(close), np.nan, dtype=float)
    for start, end in iter_segments(gap_flags, len(close)):
        seg_raw = _stoch_raw(high[start : end + 1], low[start : end + 1], close[start : end + 1], k_period)
        for j in range(len(seg_raw)):
            i = start + j
            if not np.isnan(seg_raw[j]) and same_segment(gap_flags, i - k_period + 1, i):
                raw[i] = float(seg_raw[j])
    return raw


def compute_dinapoli_stoch_arrays(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    *,
    k_period: int = K_PERIOD,
    slowing: int = SLOWING,
    d_period: int = D_PERIOD,
    gap_flags: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    flags = gap_flags if gap_flags is not None else np.zeros(len(close), dtype=bool)
    fast_k = _fast_k_segmented(high, low, close, k_period=k_period, gap_flags=flags)
    n = len(close)
    k = np.full(n, np.nan, dtype=float)
    d = np.full(n, np.nan, dtype=float)
    idx = dinapoli_stoch_warmup_indices(k_period=k_period, slowing=slowing, d_period=d_period)

    for start, end in iter_segments(flags, n):
        fastk_first = start + k_period - 1
        k_seed = fastk_first + slowing - 1
        d_seed = k_seed + d_period - 1
        if k_seed > end or d_seed > end:
            continue
        fk_window = fast_k[fastk_first : k_seed + 1]
        if np.any(np.isnan(fk_window)):
            continue
        k[k_seed] = float(np.mean(fk_window))
        for t in range(k_seed + 1, end + 1):
            if np.isnan(fast_k[t]) or np.isnan(k[t - 1]):
                continue
            k[t] = k[t - 1] + (float(fast_k[t]) - k[t - 1]) / slowing
        k_window = k[k_seed : d_seed + 1]
        if np.any(np.isnan(k_window)):
            continue
        d[d_seed] = float(np.mean(k_window))
        for t in range(d_seed + 1, end + 1):
            if np.isnan(k[t]) or np.isnan(d[t - 1]):
                continue
            d[t] = d[t - 1] + (float(k[t]) - d[t - 1]) / d_period

    return fast_k, k, d


def _full_feature_index(
    i: int,
    *,
    k: np.ndarray,
    d: np.ndarray,
    gap_flags: np.ndarray,
    first_full: int,
) -> bool:
    if i < first_full or np.isnan(k[i]) or np.isnan(d[i]):
        return False
    if i > 0 and (np.isnan(k[i - 1]) or np.isnan(d[i - 1])):
        return False
    return same_segment(gap_flags, i - 1, i)


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
        arrays.high,
        arrays.low,
        arrays.close,
        k_period=k_period,
        slowing=slowing,
        d_period=d_period,
        gap_flags=arrays.gap_flags,
    )
    warm = dinapoli_stoch_warmup_indices(k_period=k_period, slowing=slowing, d_period=d_period)
    first_full = warm["first_full_feature_index"]
    samples: list[IndicatorSample] = []

    for i in range(len(arrays.close)):
        calc_at = arrays.close_time[i]
        disp = displayed_at_for(arrays.close_time, arrays.open_time, i, display_shift)
        if not _full_feature_index(i, k=k, d=d, gap_flags=arrays.gap_flags, first_full=first_full):
            reason = "warmup" if i < first_full else "insufficient_contiguous_history"
            samples.append(
                IndicatorSample(
                    calculated_at=calc_at,
                    available_at=calc_at,
                    displayed_at=disp,
                    values={"k": None, "d": None},
                    valid=False,
                    invalid_reason=reason,
                )
            )
            continue
        if not contiguous_ok(arrays.gap_flags, segment_start_for(arrays.gap_flags, i), i):
            samples.append(
                IndicatorSample(
                    calc_at, calc_at, disp, {"k": None, "d": None}, valid=False, invalid_reason="insufficient_contiguous_history"
                )
            )
            continue

        kv, dv = float(k[i]), float(d[i])
        k_prev, d_prev = float(k[i - 1]), float(d[i - 1])
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
                calc_at,
                calc_at,
                disp,
                {"k": kv, "d": dv, "raw_k": float(raw[i]) if not np.isnan(raw[i]) else None},
                prim,
                True,
            )
        )
    return samples
