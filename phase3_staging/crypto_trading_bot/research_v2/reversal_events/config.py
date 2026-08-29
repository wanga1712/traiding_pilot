"""REVERSAL_EVENT_DATASET_V1 constants and window specs."""
from __future__ import annotations

from datetime import timedelta

EVENT_DATASET_VERSION = "REVERSAL_EVENT_DATASET_V1"
WAVE_ENGINE_VERSION = "WAVE_ENGINE_V1"
WAVE_DATASET_VERSION = "WAVE_DATASET_V1"
SYMBOL = "ETHUSDT"

# Context TFs for WHEN research windows (geometry source TFs may be any WAVE_DATASET_V1 TF).
CONTEXT_TFS = ("5m", "15m", "1H", "4H")

# Configurable window half-widths around true pivot C (stored in manifest).
WINDOW_SPEC = {
    "5m": {"before": timedelta(hours=24), "after": timedelta(hours=24)},
    "15m": {"before": timedelta(hours=48), "after": timedelta(hours=48)},
    "1H": {"before": timedelta(days=7), "after": timedelta(days=7)},
    "4H": {"before": timedelta(days=30), "after": timedelta(days=30)},
}

# Chronological partitions by true_pivot_time span.
PARTITION_FRAC = {"DISCOVERY": 0.60, "VALIDATION": 0.20, "OOS": 0.20}
# Events whose outcome (next_pivot_time) crosses a partition boundary are purged from
# the crossed partitions' usable sets and labeled PARTITION_CROSS_PURGED.
