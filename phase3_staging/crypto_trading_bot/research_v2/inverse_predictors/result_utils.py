"""Shared result construction + distance features."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .types import PredictorResult
from .version import HYPOTHETICAL_INPUT_TYPE, PREDICTOR_ENGINE_VERSION


def make_result(
    *,
    predictor_id: str,
    parameter_set_id: str,
    source_timeframe: str,
    decision_time: datetime,
    calculated_at: datetime,
    current_price: float,
    trigger_price: float | None,
    direction_required: str,
    trigger_definition: str,
    solution_status: str,
    atr: float | None = None,
    formula_note: str | None = None,
    details: dict[str, Any] | None = None,
) -> PredictorResult:
    dist_abs = dist_pct = dist_atr = signed = None
    above = below = None
    if trigger_price is not None:
        signed = trigger_price - current_price
        dist_abs = abs(signed)
        dist_pct = (signed / current_price * 100.0) if current_price else None
        dist_atr = (signed / atr) if atr else None
        above = trigger_price > current_price
        below = trigger_price < current_price
    return PredictorResult(
        predictor_engine_version=PREDICTOR_ENGINE_VERSION,
        predictor_id=predictor_id,
        parameter_set_id=parameter_set_id,
        source_timeframe=source_timeframe,
        decision_time=decision_time,
        calculated_at=calculated_at,
        available_at=calculated_at,
        predicted_trigger_price=trigger_price,
        current_price=current_price,
        distance_abs=dist_abs,
        distance_pct=dist_pct,
        distance_atr=dist_atr,
        signed_trigger_distance=signed,
        direction_required=direction_required,
        trigger_definition=trigger_definition,
        solution_status=solution_status,
        hypothetical_input_type=HYPOTHETICAL_INPUT_TYPE,
        is_trigger_above_market=above,
        is_trigger_below_market=below,
        formula_note=formula_note,
        details=details,
    )
