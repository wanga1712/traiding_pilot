"""Streaming vs batch predictor consistency."""
from __future__ import annotations

from typing import Any

from .engine import predict
from .state import build_state


def predictor_from_prefix(
    bars: list[dict[str, Any]],
    *,
    end_index: int,
    parameter_set_id: str,
    source_timeframe: str,
):
    prefix = bars[: end_index + 1]
    decision = prefix[-1]["close_time"]
    return predict(prefix, parameter_set_id=parameter_set_id, source_timeframe=source_timeframe, decision_time=decision)


def batch_predictor_at(
    bars: list[dict[str, Any]],
    *,
    end_index: int,
    parameter_set_id: str,
    source_timeframe: str,
):
    """Batch path: filter by decision_time from full series (causal filter)."""
    decision = bars[end_index]["close_time"]
    return predict(bars, parameter_set_id=parameter_set_id, source_timeframe=source_timeframe, decision_time=decision)
