"""Oscillator predictor reference — DNO + project-style dynamic OB/OS bands."""
from __future__ import annotations

from .registry import (
    DNO_REFERENCE_VERSION,
    OSCILLATOR_PREDICTOR_REGISTRY,
    PROJECT_DINAPOLI_STYLE_PREDICTOR_VERSION,
    TARGET_AGGREGATION,
)
from .inverse import price_for_next_detrended_value
from .version import OSCILLATOR_PREDICTOR_VERSION

__all__ = [
    "OSCILLATOR_PREDICTOR_VERSION",
    "DNO_REFERENCE_VERSION",
    "PROJECT_DINAPOLI_STYLE_PREDICTOR_VERSION",
    "TARGET_AGGREGATION",
    "OSCILLATOR_PREDICTOR_REGISTRY",
    "price_for_next_detrended_value",
]
