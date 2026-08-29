"""Causal MACD (+ optional DISPLAY displacement)."""
from __future__ import annotations

import numpy as np

from .bars import BarArrays, contiguous_ok, displayed_at_for
from .math_core import ema, slope_last
from .types import IndicatorSample


def compute_macd_series(
    arrays: BarArrays,
    *,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    display_shift: int = 0,
) -> list[IndicatorSample]:
    fast_e = ema(arrays.close, fast)
    slow_e = ema(arrays.close, slow)
    macd_line = fast_e - slow_e
    # Signal EMA of MACD; seed when both EMAs valid
    signal_line = np.full(len(arrays.close), np.nan, dtype=float)
    valid_idx = [i for i in range(len(macd_line)) if not np.isnan(macd_line[i])]
    if len(valid_idx) >= signal:
        first = valid_idx[0]
        # rebuild EMA on contiguous MACD values from first valid
        series = macd_line.copy()
        alpha = 2.0 / (signal + 1.0)
        # seed at first + signal - 1
        seed_i = first + signal - 1
        if seed_i < len(series) and not np.isnan(series[seed_i]):
            window = series[first : seed_i + 1]
            if not np.any(np.isnan(window)):
                signal_line[seed_i] = float(np.mean(window))
                for i in range(seed_i + 1, len(series)):
                    if np.isnan(series[i]) or np.isnan(signal_line[i - 1]):
                        continue
                    signal_line[i] = alpha * float(series[i]) + (1.0 - alpha) * signal_line[i - 1]

    hist = macd_line - signal_line
    warmup = slow + signal - 2
    samples: list[IndicatorSample] = []

    for i in range(len(arrays.close)):
        calc_at = arrays.close_time[i]
        disp = displayed_at_for(arrays.close_time, arrays.open_time, i, display_shift)
        if i < warmup or np.isnan(macd_line[i]) or np.isnan(signal_line[i]):
            samples.append(
                IndicatorSample(
                    calculated_at=calc_at,
                    available_at=calc_at,
                    displayed_at=disp,
                    values={"macd": None, "signal": None, "histogram": None},
                    valid=False,
                    invalid_reason="warmup",
                )
            )
            continue
        start = i - (slow + signal - 2)
        if start < 0 or not contiguous_ok(arrays.gap_flags, max(0, start), i):
            samples.append(
                IndicatorSample(
                    calculated_at=calc_at,
                    available_at=calc_at,
                    displayed_at=disp,
                    values={"macd": None, "signal": None, "histogram": None},
                    valid=False,
                    invalid_reason="insufficient_contiguous_history",
                )
            )
            continue

        m, s, h = float(macd_line[i]), float(signal_line[i]), float(hist[i])
        m_prev = float(macd_line[i - 1]) if i > 0 and not np.isnan(macd_line[i - 1]) else None
        s_prev = float(signal_line[i - 1]) if i > 0 and not np.isnan(signal_line[i - 1]) else None
        h_prev = float(hist[i - 1]) if i > 0 and not np.isnan(hist[i - 1]) else None

        prim = {
            "MACD_CROSS_UP_SIGNAL": False,
            "MACD_CROSS_DOWN_SIGNAL": False,
            "HISTOGRAM_CROSS_UP_ZERO": False,
            "HISTOGRAM_CROSS_DOWN_ZERO": False,
            "MACD_SLOPE": slope_last(macd_line, i),
            "HISTOGRAM_SLOPE": slope_last(hist, i),
        }
        if m_prev is not None and s_prev is not None:
            prim["MACD_CROSS_UP_SIGNAL"] = m_prev <= s_prev and m > s
            prim["MACD_CROSS_DOWN_SIGNAL"] = m_prev >= s_prev and m < s
        if h_prev is not None:
            prim["HISTOGRAM_CROSS_UP_ZERO"] = h_prev <= 0 and h > 0
            prim["HISTOGRAM_CROSS_DOWN_ZERO"] = h_prev >= 0 and h < 0

        samples.append(
            IndicatorSample(
                calculated_at=calc_at,
                available_at=calc_at,
                displayed_at=disp,
                values={"macd": m, "signal": s, "histogram": h},
                signal_primitives=prim,
                valid=True,
            )
        )
    return samples
