"""Predictor configuration."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PredictorConfig:
    period: int = 7
    peak_strength: int = 2
    lookback: int = 100
    samples: int = 5
    ob_os_level_percent: float = 0.80
    custom_ob: float | None = None
    custom_os: float | None = None


DEFAULT_PREDICTOR_CONFIG = PredictorConfig()
