"""Canonical display displacement semantics — availability never shifts."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

from crypto_trading_bot.research_v2.indicator_engine.types import IndicatorSample

DISPLACEMENT_SEMANTICS = (
    "For positive forward display shift d: value calculated at source index i "
    "is displayed at index i+d. At decision index t: "
    "DISPLAY_ALIGNED_VALUE(t, d) = SOURCE_VALUE(t - d) "
    "provided SOURCE_VALUE was already AVAILABLE_AT <= decision_time(T). "
    "DISPLAYED_AT may differ from AVAILABLE_AT; display shift NEVER changes availability."
)


def display_aligned_at_index(
    samples: Sequence[IndicatorSample],
    decision_index: int,
    display_shift: int,
    *,
    value_key: str,
) -> tuple[float | None, datetime | None, datetime | None]:
    """
    Return (display_aligned_value, source_available_at, displayed_at) at decision_index.
    Uses source index decision_index - display_shift.
    """
    if decision_index < 0 or decision_index >= len(samples):
        return None, None, None
    src_i = decision_index - display_shift
    if src_i < 0:
        return None, None, None
    src = samples[src_i]
    if not src.valid:
        return None, src.available_at, src.displayed_at
    val = src.values.get(value_key)
    return (float(val) if val is not None else None), src.available_at, samples[decision_index].displayed_at


def display_aligned_usable_at(
    samples: Sequence[IndicatorSample],
    decision_index: int,
    display_shift: int,
    decision_time: datetime,
    *,
    value_key: str,
) -> float | None:
    """Return display-aligned value only if source AVAILABLE_AT <= decision_time."""
    val, avail, _ = display_aligned_at_index(samples, decision_index, display_shift, value_key=value_key)
    if val is None or avail is None:
        return None
    if avail > decision_time:
        return None
    return val


def build_display_aligned_series(
    samples: Sequence[IndicatorSample],
    *,
    display_shift: int,
    value_key: str,
) -> list[dict[str, Any]]:
    """Per-bar display-aligned values with causal metadata."""
    out: list[dict[str, Any]] = []
    for t in range(len(samples)):
        dec = samples[t]
        val, src_avail, disp = display_aligned_at_index(samples, t, display_shift, value_key=value_key)
        out.append(
            {
                "decision_index": t,
                "source_time": dec.calculated_at.isoformat(),
                "calculated_at": dec.calculated_at.isoformat(),
                "available_at": dec.available_at.isoformat(),
                "displayed_at": disp.isoformat() if disp else None,
                "source_available_at": src_avail.isoformat() if src_avail else None,
                "display_aligned_value": val,
                "display_shift": display_shift,
            }
        )
    return out
