"""Causal MACD (+ optional DISPLAY displacement) — segment-aware."""
from __future__ import annotations

import numpy as np

from .bars import BarArrays, contiguous_ok, displayed_at_for
from .math_core import ema, slope_last
from .segments import iter_segments, same_segment, segment_start_for
from .types import IndicatorSample


def _signal_ema_segmented(macd_line: np.ndarray, signal: int, gap_flags: np.ndarray) -> np.ndarray:
    signal_line = np.full(len(macd_line), np.nan, dtype=float)
    alpha = 2.0 / (signal + 1.0)
    for start, end in iter_segments(gap_flags, len(macd_line)):
        valid = [i for i in range(start, end + 1) if not np.isnan(macd_line[i])]
        if len(valid) < signal:
            continue
        first = valid[0]
        seed_i = first + signal - 1
        if seed_i > end:
            continue
        window = macd_line[first : seed_i + 1]
        if np.any(np.isnan(window)):
            continue
        signal_line[seed_i] = float(np.mean(window))
        for i in range(seed_i + 1, end + 1):
            if np.isnan(macd_line[i]) or np.isnan(signal_line[i - 1]):
                continue
            signal_line[i] = alpha * float(macd_line[i]) + (1.0 - alpha) * signal_line[i - 1]
    return signal_line


def compute_macd_series(
    arrays: BarArrays,
    *,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    display_shift: int = 0,
) -> list[IndicatorSample]:
    gf = arrays.gap_flags
    fast_e = ema(arrays.close, fast, gap_flags=gf)
    slow_e = ema(arrays.close, slow, gap_flags=gf)
    macd_line = fast_e - slow_e
    signal_line = _signal_ema_segmented(macd_line, signal, gf)
    hist = macd_line - signal_line
    samples: list[IndicatorSample] = []

    for i in range(len(arrays.close)):
        calc_at = arrays.close_time[i]
        disp = displayed_at_for(arrays.close_time, arrays.open_time, i, display_shift)
        seg_start = segment_start_for(gf, i)
        seg_len_needed = slow + signal - 1
        if i - seg_start + 1 < seg_len_needed or np.isnan(macd_line[i]) or np.isnan(signal_line[i]):
            samples.append(
                IndicatorSample(
                    calc_at, calc_at, disp,
                    {"macd": None, "signal": None, "histogram": None},
                    valid=False, invalid_reason="warmup",
                )
            )
            continue
        if not same_segment(gf, i - 1, i) or not contiguous_ok(gf, seg_start, i):
            samples.append(
                IndicatorSample(
                    calc_at, calc_at, disp,
                    {"macd": None, "signal": None, "histogram": None},
                    valid=False, invalid_reason="insufficient_contiguous_history",
                )
            )
            continue

        m, s, h = float(macd_line[i]), float(signal_line[i]), float(hist[i])
        m_prev = float(macd_line[i - 1]) if same_segment(gf, i - 1, i) else None
        s_prev = float(signal_line[i - 1]) if same_segment(gf, i - 1, i) else None
        h_prev = float(hist[i - 1]) if same_segment(gf, i - 1, i) else None

        prim = {
            "MACD_CROSS_UP_SIGNAL": False,
            "MACD_CROSS_DOWN_SIGNAL": False,
            "HISTOGRAM_CROSS_UP_ZERO": False,
            "HISTOGRAM_CROSS_DOWN_ZERO": False,
            "MACD_SLOPE": slope_last(macd_line, i) if m_prev is not None else None,
            "HISTOGRAM_SLOPE": slope_last(hist, i) if h_prev is not None else None,
        }
        if m_prev is not None and s_prev is not None:
            prim["MACD_CROSS_UP_SIGNAL"] = m_prev <= s_prev and m > s
            prim["MACD_CROSS_DOWN_SIGNAL"] = m_prev >= s_prev and m < s
        if h_prev is not None:
            prim["HISTOGRAM_CROSS_UP_ZERO"] = h_prev <= 0 and h > 0
            prim["HISTOGRAM_CROSS_DOWN_ZERO"] = h_prev >= 0 and h < 0

        samples.append(
            IndicatorSample(
                calc_at, calc_at, disp,
                {"macd": m, "signal": s, "histogram": h},
                prim, True,
            )
        )
    return samples
