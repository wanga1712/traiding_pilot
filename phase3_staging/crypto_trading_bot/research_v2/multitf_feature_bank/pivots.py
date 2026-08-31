"""Causal pivot records — retrospective fields must not affect features."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class PivotRecord:
    """Physical pivot with causal confirmation; retrospective labels isolated."""

    pivot_id: str
    pivot_price: float
    confirmation_time: datetime
    timeframe: str = "1H"
    # --- retrospective / label fields (NEVER read by feature bank) ---
    true_pivot_time: datetime | None = field(default=None, repr=False)
    true_pivot_price: float | None = field(default=None, repr=False)
    next_pivot_id: str | None = field(default=None, repr=False)
    future_d_price: float | None = field(default=None, repr=False)
    outcome_label: str | None = field(default=None, repr=False)

    def retrospective_mutated_copy(self, **kwargs: Any) -> "PivotRecord":
        """Return copy with changed retrospective fields only."""
        p = PivotRecord(
            pivot_id=self.pivot_id,
            pivot_price=self.pivot_price,
            confirmation_time=self.confirmation_time,
            timeframe=self.timeframe,
            true_pivot_time=self.true_pivot_time,
            true_pivot_price=self.true_pivot_price,
            next_pivot_id=self.next_pivot_id,
            future_d_price=self.future_d_price,
            outcome_label=self.outcome_label,
        )
        for k, v in kwargs.items():
            setattr(p, k, v)
        return p


def confirmed_pivots_at(pivots: list[PivotRecord], decision_time: datetime) -> list[PivotRecord]:
    return sorted(
        [p for p in pivots if p.confirmation_time <= decision_time],
        key=lambda p: p.confirmation_time,
    )
