"""Normalized indicator result model and time semantics."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class IndicatorSample:
    """One bar-aligned indicator observation."""

    calculated_at: datetime
    available_at: datetime
    displayed_at: datetime | None
    values: dict[str, float | None]
    signal_primitives: dict[str, Any] = field(default_factory=dict)
    valid: bool = True
    invalid_reason: str | None = None


@dataclass(frozen=True)
class IndicatorResult:
    indicator_engine_version: str
    indicator_id: str
    parameter_set_id: str
    source_timeframe: str
    samples: tuple[IndicatorSample, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "indicator_engine_version": self.indicator_engine_version,
            "indicator_id": self.indicator_id,
            "parameter_set_id": self.parameter_set_id,
            "source_timeframe": self.source_timeframe,
            "samples": [asdict(s) for s in self.samples],
        }

    def last_valid(self) -> IndicatorSample | None:
        for s in reversed(self.samples):
            if s.valid:
                return s
        return None


# Time semantics (authoritative):
# CALCULATED_AT  — close_time of the last source bar used in the formula
# AVAILABLE_AT   — earliest causal use time (== CALCULATED_AT for closed-candle indicators)
# DISPLAYED_AT   — optional chart display coordinate (may be shifted forward);
#                  NEVER information availability. DISPLAYED_AT != AVAILABLE_AT when displaced.
