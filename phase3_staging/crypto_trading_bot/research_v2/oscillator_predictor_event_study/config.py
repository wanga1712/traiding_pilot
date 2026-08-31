"""Frozen study configuration — no parameter search."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from crypto_trading_bot.research_v2.oscillator_predictor.config import PredictorConfig
from crypto_trading_bot.research_v2.reversal_signal_study.config import PARTITION_BOUNDS

STUDY_TFS = ("5m", "15m", "30m", "1H", "2H", "4H", "6H", "8H", "12H", "1D")
ACTIVE_SPLITS = ("DISCOVERY", "VALIDATION")

FROZEN_PREDICTOR_CONFIG = PredictorConfig(
    period=7,
    peak_strength=2,
    lookback=100,
    samples=5,
    ob_os_level_percent=0.80,
)

TARGET_AGGREGATION = "PROJECT_MEAN_CONFIRMED_EXTREMA_V1"
DNO_PERIOD = 7
PEAK_STRENGTH = 2
LOOKBACK = 100
SAMPLES = 5
OB_OS_LEVEL_PERCENT = 0.80

ATR_DISTANCE_BINS = (
    (0.0, 0.25),
    (0.25, 0.50),
    (0.50, 0.75),
    (0.75, 1.00),
    (1.00, 1.50),
    (1.50, 2.00),
    (2.00, float("inf")),
)

FORWARD_HORIZONS = (1, 3, 5, 10)
BOOTSTRAP_SEED = 42
BOOTSTRAP_SAMPLES = 2000

CONTROL_DNO_QUANTILE = "CAUSAL_DNO_QUANTILE_80_20_CONTROL_V1"
CONTROL_ATR_BAND = "ATR_1X_PRICE_BAND_CONTROL_V1"
ATR_CONTROL_MULTIPLIER = 1.0

R_GEOMETRY_BINS = (
    (float("-inf"), 0.5),
    (0.5, 1.0),
    (1.0, 1.5),
    (1.5, float("inf")),
)

import os

WARMUP_BARS = 500

_pkg_root = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(os.environ.get("TRAIDING_PILOT_REPO_ROOT", str(_pkg_root.parent)))
ARTIFACT_ROOT = Path(
    os.environ.get(
        "OSCILLATOR_EVENT_STUDY_ARTIFACT_ROOT",
        str(REPO_ROOT / "artifacts" / "OSCILLATOR-PREDICTOR-HISTORICAL-EVENT-STUDY-1"),
    )
)


def split_bounds(name: str) -> tuple[datetime, datetime]:
    return PARTITION_BOUNDS[name]
