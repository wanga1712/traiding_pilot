"""Display-aligned feature helpers and provenance."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.types import IndicatorSample


def source_index(decision_index: int, display_shift: int) -> int | None:
    if display_shift <= 0:
        return decision_index
    src = decision_index - display_shift
    return src if src >= 0 else None


def provenance_at(
    samples: Sequence[IndicatorSample],
    decision_index: int,
    display_shift: int,
) -> dict[str, str | None]:
    """Source timestamps for display-aligned features at decision index t."""
    dec = samples[decision_index]
    src_i = source_index(decision_index, display_shift)
    if src_i is None:
        return {
            "DECISION_TIME": dec.available_at.isoformat(),
            "SOURCE_TIME": None,
            "CALCULATED_AT": None,
            "AVAILABLE_AT": None,
            "DISPLAYED_AT": None,
        }
    src = samples[src_i]
    return {
        "DECISION_TIME": dec.available_at.isoformat(),
        "SOURCE_TIME": src.calculated_at.isoformat(),
        "CALCULATED_AT": src.calculated_at.isoformat(),
        "AVAILABLE_AT": src.available_at.isoformat(),
        "DISPLAYED_AT": src.displayed_at.isoformat() if src.displayed_at else None,
    }


def _f(arr: np.ndarray, i: int) -> float | None:
    if i < 0 or i >= len(arr) or np.isnan(arr[i]):
        return None
    return float(arr[i])


def cross_up(prev_a: float | None, a: float | None, prev_b: float | None, b: float | None) -> bool:
    if None in (prev_a, a, prev_b, b):
        return False
    return prev_a <= prev_b and a > b


def cross_down(prev_a: float | None, a: float | None, prev_b: float | None, b: float | None) -> bool:
    if None in (prev_a, a, prev_b, b):
        return False
    return prev_a >= prev_b and a < b
