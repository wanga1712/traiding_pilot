from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


DEV_START = datetime(2020, 1, 1, tzinfo=timezone.utc)
TRAIN_END = datetime(2020, 7, 1, tzinfo=timezone.utc)
SELECTION_END = datetime(2021, 1, 1, tzinfo=timezone.utc)
DEV_END = datetime(2022, 1, 1, tzinfo=timezone.utc)
OOS_LOCK_START = datetime(2022, 1, 1, tzinfo=timezone.utc)

RUN1_START = datetime(2020, 1, 1, tzinfo=timezone.utc)
RUN1_END = datetime(2021, 1, 1, tzinfo=timezone.utc)
RUN2_START = datetime(2021, 1, 1, tzinfo=timezone.utc)
RUN2_END = datetime(2022, 1, 1, tzinfo=timezone.utc)

DECISION_TF = "1H"
HORIZONS_HOURS = (24, 72, 168)
PURGE_HOURS = max(HORIZONS_HOURS)
EMBARGO_HOURS = 24

INITIAL_CAPITAL = 100.0
LEVERAGE = 10.0
TAKER_FEE_PER_SIDE = 0.0005
SLIPPAGE_PER_SIDE = 0.0002
LIQUIDATION_FEE_RATE = 0.0005
MAINTENANCE_MARGIN_RATE = 0.004
MAX_THESIS_LOSS_FRACTION = 0.05
ENTRY_RETURN_THRESHOLD = 0.005

SPOT_FRACTIONS = (0.60, 0.40)
SPOT_MODES = ("HOLD", "SWING")
AI_VARIANTS = ("AI_NO_HEDGE", "AI_HEDGE", "AI_HEDGE_AVG")

DEFAULT_S13_ROOT = Path("/var/tmp/traiding_pilot_ui_workspace")
DEFAULT_OUTPUT_ROOT = DEFAULT_S13_ROOT / "gpu_ai_trading_policy_v1"
DEFAULT_MARKET_CACHE = Path("/var/tmp/traiding_pilot_market_cache")
DEFAULT_BASE_DATASET = (
    DEFAULT_S13_ROOT
    / "artifacts"
    / "PROBABILITY-MODEL-TRAINING-DATASET-1"
    / "full_v2"
)
DEFAULT_FUTURES_DATASET = DEFAULT_S13_ROOT / "capital_growth_experiment_v1" / "data"


@dataclass(frozen=True)
class DatasetConfig:
    decision_tf: str = DECISION_TF
    start: datetime = DEV_START
    end: datetime = DEV_END
    horizons_hours: tuple[int, ...] = HORIZONS_HOURS
    purge_hours: int = PURGE_HOURS
    embargo_hours: int = EMBARGO_HOURS
    minimum_feature_coverage: float = 0.05
