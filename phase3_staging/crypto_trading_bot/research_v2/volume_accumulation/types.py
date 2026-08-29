from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class FeatureSample:
    calculated_at: datetime
    available_at: datetime
    values: dict[str, float | int | bool | str | None]
    valid: bool = True
    invalid_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FeatureResult:
    feature_engine_version: str
    feature_family: str
    parameter_set_id: str
    source_timeframe: str
    samples: tuple[FeatureSample, ...]

    def last_valid(self) -> FeatureSample | None:
        for s in reversed(self.samples):
            if s.valid:
                return s
        return None
