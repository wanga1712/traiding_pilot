"""DiNapoli-style MACD reference — alpha-based recursive smoothing (not integer EMA periods).

Reference smoothing coefficients (public documented parameters):
  FAST_ALPHA   = 0.213
  SLOW_ALPHA   = 0.108
  SIGNAL_ALPHA = 0.199

Equivalent integer periods (metadata only, not used in calculation):
  FAST_PERIOD_EQUIV   ≈ 8.3896
  SLOW_PERIOD_EQUIV   ≈ 17.5185
  SIGNAL_PERIOD_EQUIV ≈ 9.0503

Initialization convention (documented, distinct from integer-period EMA seeding):
  - Fast and slow smoothers seed at bar 0: EMA[0] = close[0].
  - MACD[t] = fast[t] - slow[t] from bar 0 onward.
  - Signal seeds at bar 0: signal[0] = macd[0].
  - Signal recurses: signal[t] = SIGNAL_ALPHA * macd[t] + (1 - SIGNAL_ALPHA) * signal[t-1].

Reference status: DINAPOLI_REFERENCE_IMPLEMENTATION (reconstructed from public parameters).
"""
from __future__ import annotations

import numpy as np

from .bars import BarArrays, contiguous_ok, displayed_at_for
from .math_core import slope_last
from .types import IndicatorSample

FAST_ALPHA = 0.213
SLOW_ALPHA = 0.108
SIGNAL_ALPHA = 0.199

FAST_PERIOD_EQUIV = 8.3896
SLOW_PERIOD_EQUIV = 17.5185
SIGNAL_PERIOD_EQUIV = 9.0503

INIT_CONVENTION = "alpha_ema_seed_close0_signal_seed_macd0"


def alpha_recursive_ema(values: np.ndarray, alpha: float) -> np.ndarray:
    """Recursive EMA with EMA[0] = values[0]; no SMA warm-up period."""
    out = np.full(len(values), np.nan, dtype=float)
    if len(values) == 0:
        return out
    out[0] = float(values[0])
    for i in range(1, len(values)):
        if np.isnan(values[i]) or np.isnan(out[i - 1]):
            continue
        out[i] = alpha * float(values[i]) + (1.0 - alpha) * out[i - 1]
    return out


def compute_dinapoli_macd_arrays(close: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    fast = alpha_recursive_ema(close, FAST_ALPHA)
    slow = alpha_recursive_ema(close, SLOW_ALPHA)
    macd = fast - slow
    signal = alpha_recursive_ema(macd, SIGNAL_ALPHA)
    hist = macd - signal
    return macd, signal, hist


def compute_dinapoli_macd_series(
    arrays: BarArrays,
    *,
    display_shift: int = 0,
) -> list[IndicatorSample]:
    macd_line, signal_line, hist = compute_dinapoli_macd_arrays(arrays.close)
    # Slopes/crosses require prior bar → first fully featured index = 1
    warmup = 1
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
        if not contiguous_ok(arrays.gap_flags, 0, i):
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
        m_prev = float(macd_line[i - 1])
        s_prev = float(signal_line[i - 1])
        h_prev = float(hist[i - 1])

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
                calculated_at=calc_at,
                available_at=calc_at,
                displayed_at=disp,
                values={"macd": m, "signal": s, "histogram": h},
                signal_primitives=prim,
                valid=True,
            )
        )
    return samples
