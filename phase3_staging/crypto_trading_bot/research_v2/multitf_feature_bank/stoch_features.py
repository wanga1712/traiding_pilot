"""Stochastic feature extraction with full display-aligned state."""
from __future__ import annotations

from typing import Any

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.bars import BarArrays, contiguous_ok, displayed_at_for
from crypto_trading_bot.research_v2.indicator_engine.math_core import sma
from crypto_trading_bot.research_v2.indicator_engine.stochastic import _stoch_raw
from crypto_trading_bot.research_v2.indicator_engine.types import IndicatorSample

from .aligned_features import cross_down, cross_up, source_index


def _v(arr: np.ndarray, i: int) -> float | None:
    if i < 0 or i >= len(arr) or np.isnan(arr[i]):
        return None
    return float(arr[i])


def _stoch_feats_at(
    i: int,
    raw: np.ndarray,
    k: np.ndarray,
    d: np.ndarray,
    *,
    display_shift: int,
    overbought: float,
    oversold: float,
) -> dict[str, Any]:
    rk, kv, dv = _v(raw, i), _v(k, i), _v(d, i)
    if kv is None or dv is None:
        return {}
    k_prev, d_prev = _v(k, i - 1), _v(d, i - 1)
    kd_slope = (kv - d_prev) if d_prev is not None else None  # K_MINUS_D_SLOPE uses prior D

    src = source_index(i, display_shift)
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

    if src is None:
        return out

    sr, sk, sd = _v(raw, src), _v(k, src), _v(d, src)
    sk_prev, sd_prev = _v(k, src - 1), _v(d, src - 1)
    da_k_prev, da_d_prev = _v(k, src - 1), _v(d, src - 1) if src > 0 else (None, None)
    # display-aligned cross at t uses price[t] analog: K[t] vs D[t-shift] with prev at t-1
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
    elif display_shift == 0:
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


def compute_stoch_feature_series(
    arrays: BarArrays,
    *,
    k_period: int = 14,
    k_smooth: int = 3,
    d_period: int = 3,
    display_shift: int = 0,
    overbought: float = 80.0,
    oversold: float = 20.0,
) -> list[IndicatorSample]:
    raw = _stoch_raw(arrays.high, arrays.low, arrays.close, k_period)
    k = sma(raw, k_smooth)
    d = sma(k, d_period)
    warmup = k_period + k_smooth + d_period - 3
    samples: list[IndicatorSample] = []
    for i in range(len(arrays.close)):
        calc_at = arrays.close_time[i]
        disp = displayed_at_for(arrays.close_time, arrays.open_time, i, display_shift)
        if i < warmup or np.isnan(k[i]) or np.isnan(d[i]):
            samples.append(
                IndicatorSample(calc_at, calc_at, disp, {"k": None, "d": None}, valid=False, invalid_reason="warmup")
            )
            continue
        need_start = i - warmup
        if need_start < 0 or not contiguous_ok(arrays.gap_flags, max(0, need_start), i):
            samples.append(
                IndicatorSample(
                    calc_at, calc_at, disp, {"k": None, "d": None}, valid=False, invalid_reason="insufficient_contiguous_history"
                )
            )
            continue
        kv, dv = float(k[i]), float(d[i])
        prim = _stoch_feats_at(i, raw, k, d, display_shift=display_shift, overbought=overbought, oversold=oversold)
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
