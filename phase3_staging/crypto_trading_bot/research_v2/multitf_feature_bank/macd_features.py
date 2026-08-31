"""MACD feature extraction — histogram contract + display-aligned state."""
from __future__ import annotations

from typing import Any

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.bars import BarArrays, contiguous_ok, displayed_at_for
from crypto_trading_bot.research_v2.indicator_engine.macd import compute_macd_series
from crypto_trading_bot.research_v2.indicator_engine.types import IndicatorSample

from .aligned_features import cross_down, cross_up, source_index


def _v(arr: np.ndarray, i: int) -> float | None:
    if i < 0 or i >= len(arr) or np.isnan(arr[i]):
        return None
    return float(arr[i])


def _macd_feats_at(
    i: int,
    macd: np.ndarray,
    signal: np.ndarray,
    hist: np.ndarray,
    *,
    display_shift: int,
) -> dict[str, Any]:
    m, s, h = _v(macd, i), _v(signal, i), _v(hist, i)
    if m is None or s is None or h is None:
        return {}
    m_prev, s_prev, h_prev = _v(macd, i - 1), _v(signal, i - 1), _v(hist, i - 1)

    out: dict[str, Any] = {
        "MACD": m,
        "SIGNAL": s,
        "HIST": h,
        "MACD_MINUS_SIGNAL": m - s,
        "MACD_SLOPE": (m - m_prev) if m_prev is not None else None,
        "SIGNAL_SLOPE": (s - s_prev) if s_prev is not None else None,
        "HIST_SLOPE": (h - h_prev) if h_prev is not None else None,
        "MACD_CROSS_UP_SIGNAL": cross_up(m_prev, m, s_prev, s),
        "MACD_CROSS_DOWN_SIGNAL": cross_down(m_prev, m, s_prev, s),
        "HIST_CROSS_UP_ZERO": bool(h_prev is not None and h_prev <= 0 and h > 0),
        "HIST_CROSS_DOWN_ZERO": bool(h_prev is not None and h_prev >= 0 and h < 0),
        "HIST_CONTRACTING_NEGATIVE": bool(h < 0 and h_prev is not None and h_prev < 0 and abs(h) < abs(h_prev)),
        "HIST_CONTRACTING_POSITIVE": bool(h > 0 and h_prev is not None and h_prev > 0 and h < h_prev),
    }

    src = source_index(i, display_shift)
    if src is None and display_shift > 0:
        return out

    si = src if src is not None else i
    dm, ds, dh = _v(macd, si), _v(signal, si), _v(hist, si)
    dm_prev, ds_prev, dh_prev = _v(macd, si - 1), _v(signal, si - 1), _v(hist, si - 1)
    prev_src = source_index(i - 1, display_shift) if i > 0 else None
    pm, ps = (_v(macd, prev_src), _v(signal, prev_src)) if prev_src is not None else (None, None)
    ph_prev = _v(hist, prev_src - 1) if prev_src is not None and prev_src > 0 else None
    ph = _v(hist, prev_src) if prev_src is not None else None

    if dm is not None and ds is not None and dh is not None:
        out.update(
            {
                "DISPLAY_ALIGNED_MACD": dm,
                "DISPLAY_ALIGNED_SIGNAL": ds,
                "DISPLAY_ALIGNED_HIST": dh,
                "DISPLAY_ALIGNED_MACD_MINUS_SIGNAL": dm - ds,
                "DISPLAY_ALIGNED_MACD_SLOPE": (dm - dm_prev) if dm_prev is not None else None,
                "DISPLAY_ALIGNED_SIGNAL_SLOPE": (ds - ds_prev) if ds_prev is not None else None,
                "DISPLAY_ALIGNED_HIST_SLOPE": (dh - dh_prev) if dh_prev is not None else None,
                "DISPLAY_ALIGNED_MACD_CROSS_UP_SIGNAL": cross_up(pm, dm, ps, ds),
                "DISPLAY_ALIGNED_MACD_CROSS_DOWN_SIGNAL": cross_down(pm, dm, ps, ds),
                "DISPLAY_ALIGNED_HIST_CROSS_UP_ZERO": bool(ph is not None and ph <= 0 and dh > 0),
                "DISPLAY_ALIGNED_HIST_CROSS_DOWN_ZERO": bool(ph is not None and ph >= 0 and dh < 0),
                "DISPLAY_ALIGNED_HIST_CONTRACTING_NEGATIVE": bool(
                    dh < 0 and dh_prev is not None and dh_prev < 0 and abs(dh) < abs(dh_prev)
                ),
                "DISPLAY_ALIGNED_HIST_CONTRACTING_POSITIVE": bool(
                    dh > 0 and dh_prev is not None and dh_prev > 0 and dh < dh_prev
                ),
            }
        )
    return out


def compute_macd_feature_series(
    arrays: BarArrays,
    *,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    display_shift: int = 0,
) -> list[IndicatorSample]:
    base = compute_macd_series(
        arrays, fast=fast, slow=slow, signal=signal, display_shift=display_shift
    )
    # Rebuild arrays from base samples for aligned layer
    n = len(base)
    macd = np.full(n, np.nan)
    sig = np.full(n, np.nan)
    hist = np.full(n, np.nan)
    for i, s in enumerate(base):
        if s.valid:
            macd[i] = s.values.get("macd")  # type: ignore
            sig[i] = s.values.get("signal")  # type: ignore
            hist[i] = s.values.get("histogram")  # type: ignore

    out: list[IndicatorSample] = []
    for i, s in enumerate(base):
        if not s.valid:
            out.append(s)
            continue
        prim = _macd_feats_at(i, macd, sig, hist, display_shift=display_shift)
        out.append(
            IndicatorSample(
                s.calculated_at,
                s.available_at,
                s.displayed_at,
                {"macd": macd[i], "signal": sig[i], "histogram": hist[i]},
                prim,
                True,
            )
        )
    return out
