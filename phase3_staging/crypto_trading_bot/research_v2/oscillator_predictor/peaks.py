"""Causal peak/trough confirmation for oscillator extrema."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.segments import same_segment

PREDICTOR_EXTREMA_CROSS_GAP = "NO"


@dataclass(frozen=True)
class ConfirmedExtremum:
    index: int
    value: float
    kind: str  # "PEAK" | "TROUGH"
    available_at_index: int


def _is_peak(dno: np.ndarray, i: int, k: int) -> bool:
    v = dno[i]
    if np.isnan(v) or v <= 0:
        return False
    for j in range(1, k + 1):
        if np.isnan(dno[i - j]) or np.isnan(dno[i + j]):
            return False
        if dno[i - j] >= v or dno[i + j] >= v:
            return False
    return True


def _is_trough(dno: np.ndarray, i: int, k: int) -> bool:
    v = dno[i]
    if np.isnan(v) or v >= 0:
        return False
    for j in range(1, k + 1):
        if np.isnan(dno[i - j]) or np.isnan(dno[i + j]):
            return False
        if dno[i - j] <= v or dno[i + j] <= v:
            return False
    return True


def confirmed_extrema_at(
    dno: np.ndarray,
    gap_flags: np.ndarray,
    decision_index: int,
    *,
    peak_strength: int,
    lookback: int,
) -> tuple[list[ConfirmedExtremum], list[ConfirmedExtremum]]:
    """
    Return causally confirmed peaks/troughs visible at decision_index.

    Extremum at i is available only when decision_index >= i + peak_strength.
    """
    peaks: list[ConfirmedExtremum] = []
    troughs: list[ConfirmedExtremum] = []
    start = max(peak_strength, decision_index - lookback + 1)
    for i in range(start, decision_index - peak_strength + 1):
        if not same_segment(gap_flags, i - peak_strength, i + peak_strength):
            continue
        avail = i + peak_strength
        if avail > decision_index:
            continue
        if _is_peak(dno, i, peak_strength):
            peaks.append(ConfirmedExtremum(i, float(dno[i]), "PEAK", avail))
        if _is_trough(dno, i, peak_strength):
            troughs.append(ConfirmedExtremum(i, float(dno[i]), "TROUGH", avail))
    return peaks, troughs
