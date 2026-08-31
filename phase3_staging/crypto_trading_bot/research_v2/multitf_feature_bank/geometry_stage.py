"""Normalized geometry stage from direction-normalized R."""
from __future__ import annotations

from .geometry import COP_RATIO, OP_RATIO, XOP_RATIO


def stage_from_normalized_r(r: float | None) -> str:
    """R_CURRENT is (price - C) / AB — use positive thresholds for all AB signs."""
    if r is None or r != r:
        return "UNKNOWN"
    if r < COP_RATIO:
        return "PRE_COP"
    if r < OP_RATIO:
        return "COP_TO_OP"
    if r < XOP_RATIO:
        return "OP_TO_XOP"
    return "POST_XOP"
