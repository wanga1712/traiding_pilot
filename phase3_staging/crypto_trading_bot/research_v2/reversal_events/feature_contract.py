"""Feature computation contract (interfaces only — no indicators in this WIP)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class FeatureValue:
    value: Any
    calculated_at: datetime
    available_at: datetime
    displayed_at: datetime | None
    source_timeframe: str
    feature_version: str


class CausalFeatureFn(Protocol):
    """
    Every future feature function MUST accept only history available at T.

    It MUST NOT read the complete event window or any bar with
    close_time > decision_time (for closed-candle features).

    Displacement semantics:
      CALCULATED_AT  — wall/logical time when formula was evaluated
      AVAILABLE_AT   — earliest time the value may be used causally
      DISPLAYED_AT   — optional chart display time (may be shifted);
                       DISPLAYED_AT is NEVER information availability
    """

    def __call__(
        self,
        history_available_at_t: list[dict[str, Any]],
        *,
        decision_time: datetime,
        source_timeframe: str,
    ) -> FeatureValue: ...
