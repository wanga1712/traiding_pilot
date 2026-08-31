"""Search-space metadata for NEXT WIP staged parameter search (no search performed here)."""
from __future__ import annotations

from typing import Any

SEARCH_SPACE_V1: dict[str, dict[str, Any]] = {
    "DMA": {
        "implementation": "INDICATOR_ENGINE_V1",
        "parameters": ["ma_type", "period", "display_shift"],
        "ma_type_values": ["SMA", "EMA", "WMA"],
        "period_values": [3, 5, 7, 10, 14, 20, 25],
        "display_shift_values": [0, 2, 3, 5, 8],
        "preset_classes": ["DINAPOLI_STYLE", "PROJECT_RESEARCH"],
    },
    "STANDARD_STOCHASTIC": {
        "implementation": "STOCH_CANONICAL_V1",
        "parameters": ["k_period", "k_smooth", "d_period", "display_shift"],
        "k_period_values": [5, 9, 14, 21],
        "k_smooth_values": [3, 5],
        "d_period_values": [3, 5],
        "display_shift_values": [0, 2, 3, 5],
        "preset_classes": ["STANDARD", "PROJECT_DISPLACED_STOCHASTIC"],
    },
    "DINAPOLI_MODIFIED_STOCH": {
        "implementation": "DINAPOLI_PREFERRED_STOCH_REFERENCE_V1",
        "parameters": ["k_period", "slowing", "d_period"],
        "reference_config": {"k_period": 8, "slowing": 3, "d_period": 3},
        "note": "Modified recursive smoothing — distinct from SMA-smoothed canonical Stochastic",
    },
    "STANDARD_MACD": {
        "implementation": "MACD_CANONICAL_V1",
        "parameters": ["fast", "slow", "signal", "display_shift"],
        "config_labels": ["5/13/4", "8/21/5", "12/26/9"],
        "display_shift_values": [0, 2, 3, 5],
        "preset_classes": ["STANDARD", "PROJECT_DISPLACED_MACD"],
    },
    "DINAPOLI_COEFFICIENT_MACD": {
        "implementation": "DINAPOLI_MACD_REFERENCE_V1",
        "parameters": ["fast_alpha", "slow_alpha", "signal_alpha"],
        "reference_config": {
            "fast_alpha": 0.213,
            "slow_alpha": 0.108,
            "signal_alpha": 0.199,
        },
        "note": "Alpha-based smoothing — distinct from integer-period MACD",
    },
    "INVERSE_PREDICTORS": {
        "implementation": "EXISTING_DETERMINISTIC_PRICE_AT_CROSS",
        "note": "Preserved for later composite search — not expanded in this WIP",
        "available_in_search": True,
    },
}
