"""WAVE_ENGINE_V1 frozen configuration (immutable contract)."""
from __future__ import annotations

from typing import Any

WAVE_ENGINE_VERSION = "WAVE_ENGINE_V1"
WAVE_DATASET_VERSION = "WAVE_DATASET_V1"
SYMBOL = "ETHUSDT"
MARKET_SOURCE = "binance_spot_canonical_1m_resampled"
ALGORITHM_FAMILY = "classic_atr_zigzag"
NORMALIZATION_METHOD = "ATR_directional_change_grouped_by_TF"
DEPTH = 3
BACKSTEP = 0

# Frozen from accepted ZIGZAG-NORMALIZATION-AND-DINAPOLI-RETEST-1.
# Do NOT retune against indicators, PnL, volume, OI, or reversal accuracy.
CONFIG_BY_TF: dict[str, dict[str, Any]] = {
    "5m": {"atr_n": 10, "atr_k": 15.0, "depth": DEPTH, "backstep": BACKSTEP, "group": "5m-30m"},
    "15m": {"atr_n": 10, "atr_k": 15.0, "depth": DEPTH, "backstep": BACKSTEP, "group": "5m-30m"},
    "30m": {"atr_n": 10, "atr_k": 15.0, "depth": DEPTH, "backstep": BACKSTEP, "group": "5m-30m"},
    "1H": {"atr_n": 14, "atr_k": 2.5, "depth": DEPTH, "backstep": BACKSTEP, "group": "1H-4H"},
    "2H": {"atr_n": 14, "atr_k": 2.5, "depth": DEPTH, "backstep": BACKSTEP, "group": "1H-4H"},
    "4H": {"atr_n": 14, "atr_k": 2.5, "depth": DEPTH, "backstep": BACKSTEP, "group": "1H-4H"},
    "6H": {"atr_n": 14, "atr_k": 0.5, "depth": DEPTH, "backstep": BACKSTEP, "group": "6H-1D"},
    "8H": {"atr_n": 14, "atr_k": 0.5, "depth": DEPTH, "backstep": BACKSTEP, "group": "6H-1D"},
    "12H": {"atr_n": 14, "atr_k": 0.5, "depth": DEPTH, "backstep": BACKSTEP, "group": "6H-1D"},
    "1D": {"atr_n": 14, "atr_k": 0.5, "depth": DEPTH, "backstep": BACKSTEP, "group": "6H-1D"},
}

# Accepted diagnostics from Phase 0 (do not silently retune).
QUALITY_FLAG_BY_TF: dict[str, str] = {
    "5m": "OK",
    "15m": "OK",
    "30m": "OK",
    "1H": "MARGINAL_TOO_DENSE",
    "2H": "OK",
    "4H": "OK",
    "6H": "OK",
    "8H": "OK",
    "12H": "OK",
    "1D": "OK",
}

RESEARCH_DECISIONS = {
    "DINAPOLI_SPECIFIC_RATIOS_NOT_SUPPORTED": True,
    "WAVE_GEOMETRY_SUPPORTED": True,
    "LEG_PERSISTENCE_SUPPORTED": True,
    "R_IS_CONTINUOUS_TARGET": True,
    "LEGACY_FIB_FIELDS_STATUS": "LEGACY_DIAGNOSTIC_ONLY",
    "LEG_PERSISTENCE_BASELINE": "LEG_PERSISTENCE_BASELINE_V1",
    "R_BASELINE": 1.0,
    "EMPIRICAL_R_DISTRIBUTION": "EMPIRICAL_R_DISTRIBUTION_V1",
    "GEOMETRY_COMPARABLE_ACROSS_TF": False,
    "NOTE": (
        "Future research must primarily model continuous R / next_leg_magnitude. "
        "COP/OP/XOP may remain secondary descriptive thresholds only. "
        "Do not retune WAVE_ENGINE_V1 for PnL or indicator performance."
    ),
}

TIMEFRAMES = tuple(CONFIG_BY_TF.keys())
