"""DiNapoli-style MACD reference — alpha-based recursive smoothing per contiguous segment."""
from __future__ import annotations

import numpy as np

from .bars import BarArrays, contiguous_ok, displayed_at_for
from .math_core import slope_last
from .segments import iter_segments, same_segment, segment_start_for
from .types import IndicatorSample

FAST_ALPHA = 0.213
SLOW_ALPHA = 0.108
SIGNAL_ALPHA = 0.199

FAST_PERIOD_EQUIV = 8.3896
SLOW_PERIOD_EQUIV = 17.5185
SIGNAL_PERIOD_EQUIV = 9.0503

INIT_CONVENTION = "alpha_ema_seed_close0_signal_seed_macd0"
POST_GAP_INIT_CONVENTION = "segment_restart_alpha_seed_close0_signal_seed_macd0"
STABILIZATION_POLICY = "restart_recursive_state_at_each_segment_start_no_vendor_exact_claim"


def compute_dinapoli_macd_arrays(
    close: np.ndarray,
    *,
    gap_flags: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = len(close)
    flags = gap_flags if gap_flags is not None else np.zeros(n, dtype=bool)
    fast = np.full(n, np.nan, dtype=float)
    slow = np.full(n, np.nan, dtype=float)
    signal = np.full(n, np.nan, dtype=float)

    for start, end in iter_segments(flags, n):
        fast[start] = float(close[start])
        slow[start] = float(close[start])
        for i in range(start + 1, end + 1):
            fast[i] = FAST_ALPHA * float(close[i]) + (1.0 - FAST_ALPHA) * fast[i - 1]
            slow[i] = SLOW_ALPHA * float(close[i]) + (1.0 - SLOW_ALPHA) * slow[i - 1]
        macd_start = fast[start] - slow[start]
        signal[start] = macd_start
        for i in range(start + 1, end + 1):
            m = fast[i] - slow[i]
            signal[i] = SIGNAL_ALPHA * m + (1.0 - SIGNAL_ALPHA) * signal[i - 1]

    macd = fast - slow
    hist = macd - signal
    return macd, signal, hist


def compute_dinapoli_macd_series(
    arrays: BarArrays,
    *,
    display_shift: int = 0,
) -> list[IndicatorSample]:
    macd_line, signal_line, hist = compute_dinapoli_macd_arrays(arrays.close, gap_flags=arrays.gap_flags)
    warmup = 1
    samples: list[IndicatorSample] = []

    for i in range(len(arrays.close)):
        calc_at = arrays.close_time[i]
        disp = displayed_at_for(arrays.close_time, arrays.open_time, i, display_shift)
        seg_start = segment_start_for(arrays.gap_flags, i)
        seg_age = i - seg_start
        if seg_age < warmup or np.isnan(macd_line[i]) or np.isnan(signal_line[i]):
            samples.append(
                IndicatorSample(
                    calc_at, calc_at, disp,
                    {"macd": None, "signal": None, "histogram": None},
                    valid=False, invalid_reason="warmup",
                )
            )
            continue
        if not same_segment(arrays.gap_flags, i - 1, i):
            samples.append(
                IndicatorSample(
                    calc_at, calc_at, disp,
                    {"macd": None, "signal": None, "histogram": None},
                    valid=False, invalid_reason="insufficient_contiguous_history",
                )
            )
            continue

        m, s, h = float(macd_line[i]), float(signal_line[i]), float(hist[i])
        m_prev, s_prev, h_prev = float(macd_line[i - 1]), float(signal_line[i - 1]), float(hist[i - 1])
        prim = {
            "MACD_CROSS_UP_SIGNAL": m_prev <= s_prev and m > s,
            "MACD_CROSS_DOWN_SIGNAL": m_prev >= s_prev and m < s,
            "HISTOGRAM_CROSS_UP_ZERO": h_prev <= 0 and h > 0,
            "HISTOGRAM_CROSS_DOWN_ZERO": h_prev >= 0 and h < 0,
            "MACD_SLOPE": slope_last(macd_line, i),
            "HISTOGRAM_SLOPE": slope_last(hist, i),
        }
        samples.append(
            IndicatorSample(
                calc_at, calc_at, disp,
                {"macd": m, "signal": s, "histogram": h},
                prim, True,
            )
        )
    return samples
