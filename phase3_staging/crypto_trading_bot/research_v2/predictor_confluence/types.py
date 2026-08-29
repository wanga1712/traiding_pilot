from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class TriggerPoint:
    predictor_id: str
    parameter_set_id: str
    family: str
    timeframe: str
    price: float
    signed_distance_abs: float
    signed_distance_pct: float
    signed_distance_atr: float | None
    direction_required: str
    solution_status: str


@dataclass
class ConfluenceSnapshot:
    confluence_engine_version: str
    predictor_engine_version: str
    decision_time: datetime
    calculated_at: datetime
    available_at: datetime
    parameter_set_id: str
    view: str  # RAW | FAMILY_NORMALIZED
    scope: str  # WITHIN_TF | CROSS_TF
    source_timeframe: str | None
    timeframe_set: tuple[str, ...]
    current_price: float
    atr: float | None
    features: dict[str, Any] = field(default_factory=dict)
    triggers: tuple[TriggerPoint, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["decision_time"] = self.decision_time.isoformat()
        d["calculated_at"] = self.calculated_at.isoformat()
        d["available_at"] = self.available_at.isoformat()
        d["timeframe_set"] = list(self.timeframe_set)
        return d
