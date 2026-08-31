"""MACD feature extraction — histogram contract + display-aligned state."""
from __future__ import annotations

from typing import Any

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.bars import BarArrays, contiguous_ok, displayed_at_for
from crypto_trading_bot.research_v2.indicator_engine.dinapoli_macd import compute_dinapoli_macd_arrays
from crypto_trading_bot.research_v2.indicator_engine.macd import compute_macd_series
from crypto_trading_bot.research_v2.indicator_engine.types import IndicatorSample

from .aligned_features import cross_down, cross_up, source_index, source_sample_valid


def _v(arr: np.ndarray, i: int) -> float | None:
    if i < 0 or i >= len(arr) or np.isnan(arr[i]):
        return None
    return float(arr[i])


_DISPLAY_ALIGNED_KEYS = (
    "DISPLAY_ALIGNED_MACD",
    "DISPLAY_ALIGNED_SIGNAL",
    "DISPLAY_ALIGNED_HIST",
    "DISPLAY_ALIGNED_MACD_MINUS_SIGNAL",
    "DISPLAY_ALIGNED_MACD_SLOPE",
    "DISPLAY_ALIGNED_SIGNAL_SLOPE",
    "DISPLAY_ALIGNED_HIST_SLOPE",
    "DISPLAY_ALIGNED_MACD_CROSS_UP_SIGNAL",
    "DISPLAY_ALIGNED_MACD_CROSS_DOWN_SIGNAL",
    "DISPLAY_ALIGNED_HIST_CROSS_UP_ZERO",
    "DISPLAY_ALIGNED_HIST_CROSS_DOWN_ZERO",
    "DISPLAY_ALIGNED_HIST_CONTRACTING_NEGATIVE",
    "DISPLAY_ALIGNED_HIST_CONTRACTING_POSITIVE",
)


def _macd_feats_at(
    i: int,
    macd: np.ndarray,
    signal: np.ndarray,
    hist: np.ndarray,
    *,
    display_shift: int,
    valid_flags: list[bool],
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

    if display_shift == 0:
        out.update(
            {
                "DISPLAY_ALIGNED_MACD": m,
                "DISPLAY_ALIGNED_SIGNAL": s,
                "DISPLAY_ALIGNED_HIST": h,
                "DISPLAY_ALIGNED_MACD_MINUS_SIGNAL": m - s,
                "DISPLAY_ALIGNED_MACD_SLOPE": out["MACD_SLOPE"],
                "DISPLAY_ALIGNED_SIGNAL_SLOPE": out["SIGNAL_SLOPE"],
                "DISPLAY_ALIGNED_HIST_SLOPE": out["HIST_SLOPE"],
                "DISPLAY_ALIGNED_MACD_CROSS_UP_SIGNAL": out["MACD_CROSS_UP_SIGNAL"],
                "DISPLAY_ALIGNED_MACD_CROSS_DOWN_SIGNAL": out["MACD_CROSS_DOWN_SIGNAL"],
                "DISPLAY_ALIGNED_HIST_CROSS_UP_ZERO": out["HIST_CROSS_UP_ZERO"],
                "DISPLAY_ALIGNED_HIST_CROSS_DOWN_ZERO": out["HIST_CROSS_DOWN_ZERO"],
                "DISPLAY_ALIGNED_HIST_CONTRACTING_NEGATIVE": out["HIST_CONTRACTING_NEGATIVE"],
                "DISPLAY_ALIGNED_HIST_CONTRACTING_POSITIVE": out["HIST_CONTRACTING_POSITIVE"],
            }
        )
        return out

    if not source_sample_valid(valid_flags, i, display_shift):
        out.update({key: None for key in _DISPLAY_ALIGNED_KEYS})
        return out

    src = source_index(i, display_shift)
    assert src is not None
    dm, ds, dh = _v(macd, src), _v(signal, src), _v(hist, src)
    dm_prev, ds_prev, dh_prev = _v(macd, src - 1), _v(signal, src - 1), _v(hist, src - 1)
    prev_src = source_index(i - 1, display_shift) if i > 0 else None
    pm, ps = (_v(macd, prev_src), _v(signal, prev_src)) if prev_src is not None else (None, None)
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
    else:
        out.update({key: None for key in _DISPLAY_ALIGNED_KEYS})
    return out


def _standard_macd_valid(i: int, *, slow: int, signal: int, macd: np.ndarray, signal_line: np.ndarray, gap_flags: np.ndarray) -> bool:
    warmup = slow + signal - 2
    if i < warmup or np.isnan(macd[i]) or np.isnan(signal_line[i]):
        return False
    start = i - (slow + signal - 2)
    return start >= 0 and contiguous_ok(gap_flags, max(0, start), i)


def _dinapoli_macd_valid(i: int, *, macd: np.ndarray, signal_line: np.ndarray, gap_flags: np.ndarray) -> bool:
    warmup = 1
    if i < warmup or np.isnan(macd[i]) or np.isnan(signal_line[i]):
        return False
    return contiguous_ok(gap_flags, 0, i)


def compute_macd_feature_series(
    arrays: BarArrays,
    *,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    display_shift: int = 0,
    formula_version: str = "MACD_CANONICAL_V1",
) -> list[IndicatorSample]:
    if formula_version == "DINAPOLI_MACD_REFERENCE_V1":
        return compute_dinapoli_macd_feature_series(arrays, display_shift=display_shift)

    base = compute_macd_series(arrays, fast=fast, slow=slow, signal=signal, display_shift=display_shift)
    n = len(base)
    macd = np.full(n, np.nan)
    sig = np.full(n, np.nan)
    hist = np.full(n, np.nan)
    valid_flags: list[bool] = []
    for i, s in enumerate(base):
        valid_flags.append(s.valid)
        if s.valid:
            macd[i] = s.values.get("macd")  # type: ignore
            sig[i] = s.values.get("signal")  # type: ignore
            hist[i] = s.values.get("histogram")  # type: ignore

    out: list[IndicatorSample] = []
    for i, s in enumerate(base):
        if not s.valid:
            out.append(s)
            continue
        prim = _macd_feats_at(i, macd, sig, hist, display_shift=display_shift, valid_flags=valid_flags)
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


def compute_dinapoli_macd_feature_series(
    arrays: BarArrays,
    *,
    display_shift: int = 0,
) -> list[IndicatorSample]:
    macd, sig, hist = compute_dinapoli_macd_arrays(arrays.close)
    n = len(arrays.close)
    valid_flags = [
        _dinapoli_macd_valid(i, macd=macd, signal_line=sig, gap_flags=arrays.gap_flags) for i in range(n)
    ]
    samples: list[IndicatorSample] = []
    warmup = 1
    for i in range(n):
        calc_at = arrays.close_time[i]
        disp = displayed_at_for(arrays.close_time, arrays.open_time, i, display_shift)
        if not valid_flags[i]:
            reason = "warmup" if i < warmup else "insufficient_contiguous_history"
            samples.append(
                IndicatorSample(
                    calc_at,
                    calc_at,
                    disp,
                    {"macd": None, "signal": None, "histogram": None},
                    valid=False,
                    invalid_reason=reason,
                )
            )
            continue
        prim = _macd_feats_at(i, macd, sig, hist, display_shift=display_shift, valid_flags=valid_flags)
        samples.append(
            IndicatorSample(
                calc_at,
                calc_at,
                disp,
                {"macd": float(macd[i]), "signal": float(sig[i]), "histogram": float(hist[i])},
                prim,
                True,
            )
        )
    return samples
