"""Registered search space — freeze before VALIDATION; OOS locked."""
from __future__ import annotations

from crypto_trading_bot.research_v2.reversal_signal_study.config import (
    CANONICAL_1M,
    EVENT_DIR,
    MARKET_CACHE,
    MAX_DELAY_SECONDS,
    PARTITION_BOUNDS,
    SSH_HOST,
    SSH_KEY,
    TF_BAR_SECONDS,
    WAVE_DIR,
)

FIB_COP = 0.618
FIB_OP = 1.0
FIB_XOP = 1.618

# Primary pairs (geometry TF → confirmation TF)
MTF_PAIRS = (
    ("4H", "1H"),
    ("4H", "15m"),
    ("6H", "1H"),
    ("6H", "15m"),
    ("1D", "4H"),
    ("2H", "15m"),
)

# Selection pair for DISCOVERY freeze
SELECT_GEO_TF = "4H"
SELECT_DEC_TF = "1H"

# --- Staged grids (registered before VALIDATION) ---
DMA_COARSE = ((3, 3), (7, 5), (25, 5), (5, 3), (10, 5), (14, 5), (20, 5))
DMA_REFINE_SHIFTS = (2, 3, 5, 8)  # around winner period only

STOCH_COARSE = (
    # k, ks, d, shift, os, ob
    (14, 3, 3, 0, 20.0, 80.0),
    (14, 3, 3, 3, 20.0, 80.0),
    (14, 3, 3, 5, 20.0, 80.0),
    (10, 3, 3, 3, 20.0, 80.0),
    (21, 3, 3, 3, 20.0, 80.0),
)
STOCH_OBOS_LEVELS = ((20.0, 80.0), (15.0, 85.0), (25.0, 75.0))

MACD_COARSE = (
    # fast, slow, signal, shift — PROJECT_EXPERIMENTAL if not historical
    (12, 26, 9, 0),
    (12, 26, 9, 3),
    (12, 26, 9, 5),
    (8, 17, 9, 3),
    (12, 26, 5, 3),
)

CONFLUENCE_MODES = ("DMA_ONLY", "DMA_STOCH", "DMA_MACD", "STOCH_MACD", "DMA_STOCH_MACD", "2OF3")
CONFLUENCE_WINDOWS = (0, 2, 3, 5)
EXPIRATION_BARS = (1, 2, 3, 5, 8)

GEOMETRY_ARMS = (
    "NO_GEOMETRY_ARM",
    "R_GE_0618",
    "R_GE_1000",
    "R_GE_1618",
    "EMPIRICAL_R_PERCENTILE_ARM",
    "LEG_PERSISTENCE_R1_ZONE",
)

GEOMETRY_STAGES = ("PRE_COP", "COP_TO_OP", "OP_TO_XOP", "POST_XOP")

VOL_GATES = ("NO_VOL_GATE", "EXCLUDE_LOW_ACTIVITY", "REQUIRE_NORMAL_OR_HIGH", "REQUIRE_HIGH_ACTIVITY")

VOLUME_GATES = (
    "NO_VOLUME_GATE",
    "REL_VOLUME_P50",
    "VOLUME_ZSCORE_ABS_P50",
    "EFFICIENCY_P50",
    "NOT_COMPRESSED",
)

PRICE_BASELINES = (
    "ONE_BAR_DIRECTION_CHANGE",
    "CLOSE_ABOVE_PREVIOUS_HIGH",
    "N3_BAR_EXTREME_BREAK",
    "N5_BAR_EXTREME_BREAK",
    "SHORT_TERM_SLOPE_SIGN_CHANGE",
)

SYSTEM_VARIANTS = ("A_PRICE_ONLY", "B_CONFLUENCE", "C_GEO_CONF", "D_VOL_CONF", "E_GEO_VOL_CONF", "F_GEO_VOL_OBOS_CONF", "G_FULL")

ABLATION_REMOVE = ("geometry", "volatility", "obos", "dma", "stoch", "macd", "volume")
