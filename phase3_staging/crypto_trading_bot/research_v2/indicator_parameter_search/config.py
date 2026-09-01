"""Frozen search configuration — splits, folds, authorities."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from crypto_trading_bot.research_v2.oscillator_predictor.config import PredictorConfig
from crypto_trading_bot.research_v2.reversal_signal_study.config import PARTITION_BOUNDS

SEARCH_TFS = ("5m", "15m", "30m", "1H", "2H", "4H", "6H", "8H", "12H", "1D")
ACTIVE_SPLITS = ("DISCOVERY", "VALIDATION")

FROZEN_PREDICTOR_REFERENCE = PredictorConfig(
    period=7,
    peak_strength=2,
    lookback=100,
    samples=5,
    ob_os_level_percent=0.80,
)

DNO_ONE_FACTOR_AXES = {
    "period": [5, 7, 10, 14],
    "peak_strength": [1, 2, 3],
    "lookback": [50, 100, 200],
    "samples": [3, 5, 8],
    "ob_os_level_percent": [0.70, 0.80, 0.90],
}

MAX_COMBINED_PREDICTOR_CONFIGS_PER_TF_DIR = 4
DISCOVERY_SHORTLIST_CAP_PER_FAMILY = 2
REDUNDANCY_JACCARD = 0.90
REDUNDANCY_CORR = 0.95
FDR_ALPHA = 0.10
BOOTSTRAP_SEED = 42
BOOTSTRAP_BLOCKS = 200

TF_BAR_SECONDS = {
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1H": 3600,
    "2H": 7200,
    "4H": 14400,
    "6H": 21600,
    "8H": 28800,
    "12H": 43200,
    "1D": 86400,
}

MAX_DELAY_SECONDS = {
    "5m": 4 * 3600,
    "15m": 8 * 3600,
    "30m": 12 * 3600,
    "1H": 24 * 3600,
    "2H": 36 * 3600,
    "4H": 48 * 3600,
    "6H": 72 * 3600,
    "8H": 96 * 3600,
    "12H": 144 * 3600,
    "1D": 168 * 3600,
}

EVENT_PRIMITIVES = {
    "DMA": [
        ("PRICE_CROSS_UP_MA", "PRICE_CROSS_DOWN_MA"),
        ("MA_SLOPE_TURN_UP", "MA_SLOPE_TURN_DOWN"),
    ],
    "STOCHASTIC": [
        ("K_CROSS_UP_D", "K_CROSS_DOWN_D"),
    ],
    "MACD": [
        ("MACD_CROSS_UP_SIGNAL", "MACD_CROSS_DOWN_SIGNAL"),
        ("HIST_CROSS_UP_ZERO", "HIST_CROSS_DOWN_ZERO"),
    ],
    "DNO": [
        ("DNO_ZERO_CROSS_UP", "DNO_ZERO_CROSS_DOWN"),
    ],
    "OSC_PREDICTOR": [
        ("CROSSED_OB_BAND_UP", "CROSSED_OS_BAND_DOWN"),
        ("FORECAST_OB_CROSS", "FORECAST_OS_CROSS"),
    ],
}

_pkg_root = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(os.environ.get("TRAIDING_PILOT_REPO_ROOT", str(_pkg_root.parent)))
ARTIFACT_ROOT = Path(
    os.environ.get(
        "INDICATOR_PARAM_SEARCH_ARTIFACT_ROOT",
        str(REPO_ROOT / "artifacts" / "MULTITF-INDICATOR-PARAMETER-SEARCH-1"),
    )
)
EVENT_DIR = Path(os.environ.get("REVERSAL_EVENT_DATASET_DIR", "/var/tmp/traiding_pilot_ui_workspace/reversal_event_dataset_v1"))


def split_bounds(name: str) -> tuple[datetime, datetime]:
    return PARTITION_BOUNDS[name]


def discovery_fold_bounds() -> list[tuple[datetime, datetime]]:
    start, end = split_bounds("DISCOVERY")
    total = (end - start).total_seconds()
    third = total / 3.0
    folds = []
    for i in range(3):
        f0 = start if i == 0 else folds[-1][1]
        f1 = end if i == 2 else datetime.fromtimestamp(start.timestamp() + third * (i + 1), tz=timezone.utc)
        folds.append((f0, f1))
    return folds
