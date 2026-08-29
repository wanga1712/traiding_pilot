"""Study constants — partition boundaries from REVERSAL_EVENT_DATASET_V1."""
from __future__ import annotations

from datetime import datetime, timezone

STUDY_VERSION = "REVERSAL_SIGNAL_EVENT_STUDY_V1"

DECISION_TFS = ("5m", "15m", "1H", "4H")
SOURCE_WAVE_TFS = ("5m", "15m", "30m", "1H", "2H", "4H", "6H", "8H", "12H", "1D")

# Chronological partitions from event_dataset_manifest_v1.json — OOS locked.
PARTITION_BOUNDS = {
    "DISCOVERY": (
        datetime(2019, 5, 12, tzinfo=timezone.utc),
        datetime(2022, 6, 10, 4, 36, tzinfo=timezone.utc),
    ),
    "VALIDATION": (
        datetime(2022, 6, 10, 4, 36, tzinfo=timezone.utc),
        datetime(2023, 6, 20, 6, 8, tzinfo=timezone.utc),
    ),
    # OOS intentionally listed but MUST NOT be used for selection in this WIP.
    "OOS": (
        datetime(2023, 6, 20, 6, 8, tzinfo=timezone.utc),
        datetime(2024, 6, 29, 7, 40, tzinfo=timezone.utc),
    ),
}

# Max post-C detection delay by decision TF (seconds). Signal must also be
# before next true pivot. Windows meaningful per TF — not raw-bar comparable.
MAX_DELAY_SECONDS = {
    "5m": 4 * 3600,  # 4h
    "15m": 8 * 3600,  # 8h
    "1H": 24 * 3600,  # 24h
    "4H": 48 * 3600,  # 48h
}

TF_BAR_SECONDS = {
    "5m": 300,
    "15m": 900,
    "1H": 3600,
    "4H": 14400,
}

TIMELINESS_BARS = (1, 2, 3, 6)
TIMELINESS_SECONDS = (
    15 * 60,
    30 * 60,
    3600,
    2 * 3600,
    4 * 3600,
    8 * 3600,
    24 * 3600,
)

EVENT_DIR = "/var/tmp/traiding_pilot_ui_workspace/reversal_event_dataset_v1"
WAVE_DIR = "/var/tmp/traiding_pilot_ui_workspace/wave_dataset_v1"
MARKET_CACHE = "/var/tmp/traiding_pilot_market_cache"
CANONICAL_1M = "/srv/traiding_pilot/market/binance/spot/ETHUSDT/1m"
SSH_HOST = "wanga@10.8.0.7"
SSH_KEY = "/home/sergey/.ssh/id_to_nyx"
