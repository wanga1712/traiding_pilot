"""Analytic next-bar inverse for detrended oscillator."""
from __future__ import annotations

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.math_core import sma

FLOAT_TOL = 1e-9

DNO_INVERSE_FORMULA = "P = (N * D_TARGET + S) / (N - 1); S = sum(Close[t-N+2:t+1])"


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
