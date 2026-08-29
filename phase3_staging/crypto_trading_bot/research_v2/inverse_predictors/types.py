from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class PredictorResult:
    predictor_engine_version: str
    predictor_id: str
    parameter_set_id: str
    source_timeframe: str
    decision_time: datetime
    calculated_at: datetime
    available_at: datetime
    predicted_trigger_price: float | None
    current_price: float
    distance_abs: float | None
    distance_pct: float | None
    distance_atr: float | None
    signed_trigger_distance: float | None
    direction_required: str  # UP | DOWN | EITHER | NONE
    trigger_definition: str
    solution_status: str
    hypothetical_input_type: str
    is_trigger_above_market: bool | None = None
    is_trigger_below_market: bool | None = None
    formula_note: str | None = None
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
