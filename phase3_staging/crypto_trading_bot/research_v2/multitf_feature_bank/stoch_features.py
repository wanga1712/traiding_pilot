"""Stochastic feature extraction with full display-aligned state."""
from __future__ import annotations

from typing import Any

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.bars import BarArrays, contiguous_ok, displayed_at_for
from crypto_trading_bot.research_v2.indicator_engine.dinapoli_stochastic import compute_dinapoli_stoch_arrays
from crypto_trading_bot.research_v2.indicator_engine.math_core import sma
from crypto_trading_bot.research_v2.indicator_engine.stochastic import _stoch_raw
from crypto_trading_bot.research_v2.indicator_engine.types import IndicatorSample

from .aligned_features import cross_down, cross_up, source_index, source_sample_valid


def _v(arr: np.ndarray, i: int) -> float | None:
    if i < 0 or i >= len(arr) or np.isnan(arr[i]):
        return None
    return float(arr[i])


_DISPLAY_ALIGNED_KEYS = (
    "DISPLAY_ALIGNED_RAW_K",
    "DISPLAY_ALIGNED_K",
    "DISPLAY_ALIGNED_D",
    "DISPLAY_ALIGNED_K_MINUS_D",
    "DISPLAY_ALIGNED_K_MINUS_D_SLOPE",
    "DISPLAY_ALIGNED_K_SLOPE",
    "DISPLAY_ALIGNED_D_SLOPE",
    "DISPLAY_ALIGNED_K_CROSS_UP_D",
    "DISPLAY_ALIGNED_K_CROSS_DOWN_D",
    "DISPLAY_ALIGNED_DIST_TO_OVERSOLD",
    "DISPLAY_ALIGNED_DIST_TO_OVERBOUGHT",
    "DISPLAY_ALIGNED_OVERBOUGHT",
    "DISPLAY_ALIGNED_OVERSOLD",
)


def _stoch_feats_at(
    i: int,
    raw: np.ndarray,
    k: np.ndarray,
    d: np.ndarray,
    *,
    display_shift: int,
    overbought: float,
    oversold: float,
    valid_flags: list[bool],
) -> dict[str, Any]:
    rk, kv, dv = _v(raw, i), _v(k, i), _v(d, i)
    if kv is None or dv is None:
        return {}
    k_prev, d_prev = _v(k, i - 1), _v(d, i - 1)

    out: dict[str, Any] = {
        "RAW_K": rk,
        "K": kv,
        "D": dv,
        "K_MINUS_D": kv - dv,
        "K_MINUS_D_SLOPE": (kv - dv) - (k_prev - d_prev) if k_prev is not None and d_prev is not None else None,
        "K_SLOPE": (kv - k_prev) if k_prev is not None else None,
        "D_SLOPE": (dv - d_prev) if d_prev is not None else None,
        "K_CROSS_UP_D": cross_up(k_prev, kv, d_prev, dv),
        "K_CROSS_DOWN_D": cross_down(k_prev, kv, d_prev, dv),
        "DIST_TO_OVERSOLD": kv - oversold,
        "DIST_TO_OVERBOUGHT": overbought - kv,
        "OVERBOUGHT_80": kv >= overbought,
        "OVERSOLD_20": kv <= oversold,
    }

    if display_shift == 0:
        out.update(
            {
                "DISPLAY_ALIGNED_RAW_K": rk,
                "DISPLAY_ALIGNED_K": kv,
                "DISPLAY_ALIGNED_D": dv,
                "DISPLAY_ALIGNED_K_MINUS_D": kv - dv,
                "DISPLAY_ALIGNED_K_MINUS_D_SLOPE": out["K_MINUS_D_SLOPE"],
                "DISPLAY_ALIGNED_K_SLOPE": out["K_SLOPE"],
                "DISPLAY_ALIGNED_D_SLOPE": out["D_SLOPE"],
                "DISPLAY_ALIGNED_K_CROSS_UP_D": out["K_CROSS_UP_D"],
                "DISPLAY_ALIGNED_K_CROSS_DOWN_D": out["K_CROSS_DOWN_D"],
                "DISPLAY_ALIGNED_DIST_TO_OVERSOLD": out["DIST_TO_OVERSOLD"],
                "DISPLAY_ALIGNED_DIST_TO_OVERBOUGHT": out["DIST_TO_OVERBOUGHT"],
                "DISPLAY_ALIGNED_OVERBOUGHT": out["OVERBOUGHT_80"],
                "DISPLAY_ALIGNED_OVERSOLD": out["OVERSOLD_20"],
            }
        )
        return out

    if not source_sample_valid(valid_flags, i, display_shift):
        out.update({key: None for key in _DISPLAY_ALIGNED_KEYS})
        return out

    src = source_index(i, display_shift)
    assert src is not None
    sr, sk, sd = _v(raw, src), _v(k, src), _v(d, src)
    sk_prev, sd_prev = _v(k, src - 1), _v(d, src - 1)
    prev_src = source_index(i - 1, display_shift) if i > 0 else None
    psk = _v(k, prev_src) if prev_src is not None else None
    psd = _v(d, prev_src) if prev_src is not None else None

    if sk is not None and sd is not None:
        out.update(
            {
                "DISPLAY_ALIGNED_RAW_K": sr,
                "DISPLAY_ALIGNED_K": sk,
                "DISPLAY_ALIGNED_D": sd,
                "DISPLAY_ALIGNED_K_MINUS_D": sk - sd,
                "DISPLAY_ALIGNED_K_MINUS_D_SLOPE": (sk - sd) - (sk_prev - sd_prev)
                if sk_prev is not None and sd_prev is not None
                else None,
                "DISPLAY_ALIGNED_K_SLOPE": (sk - sk_prev) if sk_prev is not None else None,
                "DISPLAY_ALIGNED_D_SLOPE": (sd - sd_prev) if sd_prev is not None else None,
                "DISPLAY_ALIGNED_K_CROSS_UP_D": cross_up(psk, sk, psd, sd),
                "DISPLAY_ALIGNED_K_CROSS_DOWN_D": cross_down(psk, sk, psd, sd),
                "DISPLAY_ALIGNED_DIST_TO_OVERSOLD": sk - oversold,
                "DISPLAY_ALIGNED_DIST_TO_OVERBOUGHT": overbought - sk,
                "DISPLAY_ALIGNED_OVERBOUGHT": sk >= overbought,
                "DISPLAY_ALIGNED_OVERSOLD": sk <= oversold,
            }
        )
    else:
        out.update({key: None for key in _DISPLAY_ALIGNED_KEYS})
    return out


def _standard_stoch_valid(
    i: int,
    *,
    k_period: int,
    k_smooth: int,
    d_period: int,
    k: np.ndarray,
    d: np.ndarray,
    gap_flags: np.ndarray,
) -> bool:
    warmup = k_period + k_smooth + d_period - 3
    if i < warmup or np.isnan(k[i]) or np.isnan(d[i]):
        return False
    need_start = i - warmup
    return need_start >= 0 and contiguous_ok(gap_flags, max(0, need_start), i)


def _dinapoli_stoch_valid(
    i: int,
    *,
    k_period: int,
    k: np.ndarray,
    d: np.ndarray,
    gap_flags: np.ndarray,
) -> bool:
    warmup = k_period
    if i < warmup or np.isnan(k[i]) or np.isnan(d[i]):
        return False
    return contiguous_ok(gap_flags, max(0, k_period - 1), i)


def compute_stoch_feature_series(
    arrays: BarArrays,
    *,
    k_period: int = 14,
    k_smooth: int = 3,
    d_period: int = 3,
    display_shift: int = 0,
    overbought: float = 80.0,
    oversold: float = 20.0,
    formula_version: str = "STOCH_CANONICAL_V1",
    slowing: int | None = None,
) -> list[IndicatorSample]:
    if formula_version == "DINAPOLI_PREFERRED_STOCH_REFERENCE_V1":
        return compute_dinapoli_stoch_feature_series(
            arrays,
            k_period=k_period,
            slowing=slowing or 3,
            d_period=d_period,
            display_shift=display_shift,
            overbought=overbought,
            oversold=oversold,
        )

    raw = _stoch_raw(arrays.high, arrays.low, arrays.close, k_period)
    k = sma(raw, k_smooth)
    d = sma(k, d_period)
    n = len(arrays.close)
    valid_flags = [
        _standard_stoch_valid(
            i,
            k_period=k_period,
            k_smooth=k_smooth,
            d_period=d_period,
            k=k,
            d=d,
            gap_flags=arrays.gap_flags,
        )
        for i in range(n)
    ]
    samples: list[IndicatorSample] = []
    warmup = k_period + k_smooth + d_period - 3
    for i in range(n):
        calc_at = arrays.close_time[i]
        disp = displayed_at_for(arrays.close_time, arrays.open_time, i, display_shift)
        if not valid_flags[i]:
            reason = "warmup" if i < warmup else "insufficient_contiguous_history"
            samples.append(
                IndicatorSample(calc_at, calc_at, disp, {"k": None, "d": None}, valid=False, invalid_reason=reason)
            )
            continue
        kv, dv = float(k[i]), float(d[i])
        prim = _stoch_feats_at(
            i, raw, k, d, display_shift=display_shift, overbought=overbought, oversold=oversold, valid_flags=valid_flags
        )
        samples.append(
            IndicatorSample(
                calc_at,
                calc_at,
                disp,
                {"k": kv, "d": dv, "raw_k": _v(raw, i)},
                prim,
                True,
            )
        )
    return samples


def compute_dinapoli_stoch_feature_series(
    arrays: BarArrays,
    *,
    k_period: int = 8,
    slowing: int = 3,
    d_period: int = 3,
    display_shift: int = 0,
    overbought: float = 80.0,
    oversold: float = 20.0,
) -> list[IndicatorSample]:
    raw, k, d = compute_dinapoli_stoch_arrays(
        arrays.high, arrays.low, arrays.close, k_period=k_period, slowing=slowing, d_period=d_period
    )
    n = len(arrays.close)
    valid_flags = [
        _dinapoli_stoch_valid(i, k_period=k_period, k=k, d=d, gap_flags=arrays.gap_flags) for i in range(n)
    ]
    samples: list[IndicatorSample] = []
    warmup = k_period
    for i in range(n):
        calc_at = arrays.close_time[i]
        disp = displayed_at_for(arrays.close_time, arrays.open_time, i, display_shift)
        if not valid_flags[i]:
            reason = "warmup" if i < warmup else "insufficient_contiguous_history"
            samples.append(
                IndicatorSample(calc_at, calc_at, disp, {"k": None, "d": None}, valid=False, invalid_reason=reason)
            )
            continue
        kv, dv = float(k[i]), float(d[i])
        prim = _stoch_feats_at(
            i, raw, k, d, display_shift=display_shift, overbought=overbought, oversold=oversold, valid_flags=valid_flags
        )
        samples.append(
            IndicatorSample(
                calc_at,
                calc_at,
                disp,
                {"k": kv, "d": dv, "raw_k": _v(raw, i)},
                prim,
                True,
            )
        )
    return samples
