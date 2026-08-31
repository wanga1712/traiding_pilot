"""Analytic next-bar inverse for detrended oscillator."""
from __future__ import annotations

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.math_core import sma
from crypto_trading_bot.research_v2.indicator_engine.segments import segment_start_for, segment_starts_array

FLOAT_TOL = 1e-9

DNO_INVERSE_FORMULA = "P = (N * D_TARGET + S) / (N - 1); S = sum(Close[t-N+2:t+1])"
INSUFFICIENT_CONTIGUOUS_HISTORY = "INSUFFICIENT_CONTIGUOUS_HISTORY"


def price_for_next_detrended_value(
    closes: np.ndarray,
    *,
    period: int,
    target_oscillator_value: float,
) -> float | None:
    """
    Solve for Close[t+1]=P such that DNO[t+1] = target_oscillator_value.

    D[t+1] = P - (S + P) / N  where S = sum of last N-1 closes at t.
    """
    if len(closes) < period - 1 or period < 2:
        return None
    s = float(np.sum(closes[-(period - 1) :]))
    return (period * float(target_oscillator_value) + s) / (period - 1.0)


def price_for_next_detrended_value_segment_safe(
    closes: np.ndarray,
    gap_flags: np.ndarray,
    decision_index: int,
    *,
    period: int,
    target_oscillator_value: float,
    seg_starts: np.ndarray | None = None,
) -> tuple[float | None, str]:
    """
    Segment-safe adapter: uses only closes from current segment through decision_index.

    Does not modify frozen INVERSE_PREDICTOR_ENGINE_V1 core formula.
    """
    if decision_index < 0 or decision_index >= len(closes):
        return None, INSUFFICIENT_CONTIGUOUS_HISTORY
    if seg_starts is not None:
        seg_start = int(seg_starts[decision_index])
    else:
        seg_start = segment_start_for(gap_flags, decision_index)
    seg_closes = closes[seg_start : decision_index + 1]
    if len(seg_closes) < period - 1:
        return None, INSUFFICIENT_CONTIGUOUS_HISTORY
    price = price_for_next_detrended_value(
        seg_closes, period=period, target_oscillator_value=target_oscillator_value
    )
    return price, "OK"


def verify_inverse_roundtrip(
    closes: np.ndarray,
    *,
    period: int,
    target: float,
    tol: float = FLOAT_TOL,
) -> bool:
    p = price_for_next_detrended_value(closes, period=period, target_oscillator_value=target)
    if p is None:
        return False
    extended = np.append(closes, p)
    ma = sma(extended, period)
    d = float(extended[-1] - ma[-1])
    return abs(d - target) < tol
