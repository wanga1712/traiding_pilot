"""Explicit indicator + parameter registries for INDICATOR_ENGINE_V1."""
from __future__ import annotations

from typing import Any

INDICATOR_ENGINE_VERSION = "INDICATOR_ENGINE_V1"

MA_RESEARCH_PERIODS = [5, 8, 10, 13, 20, 21, 25, 34, 50, 100, 200]

# Baseline parameter sets — no massive search in this WIP.
PARAMETER_REGISTRY: dict[str, dict[str, Any]] = {
    # DMA (DiNapoli-style display displacement)
    "DMA_3X3_V1": {
        "indicator_id": "DMA",
        "period": 3,
        "display_shift": 3,
        "authority": "DINAPOLI_STYLE",
        "preset_class": "DINAPOLI_STYLE",
    },
    "DMA_7X5_V1": {
        "indicator_id": "DMA",
        "period": 7,
        "display_shift": 5,
        "authority": "DINAPOLI_STYLE",
        "preset_class": "DINAPOLI_STYLE",
    },
    "DMA_25X5_V1": {
        "indicator_id": "DMA",
        "period": 25,
        "display_shift": 5,
        "authority": "DINAPOLI_STYLE",
        "preset_class": "DINAPOLI_STYLE",
    },
    # Stochastic
    "STOCH_14_3_3_V1": {
        "indicator_id": "STOCHASTIC",
        "k_period": 14,
        "k_smooth": 3,
        "d_period": 3,
        "display_shift": 0,
        "overbought": 80.0,
        "oversold": 20.0,
        "preset_class": "STANDARD",
    },
    "DISPLACED_STOCH_14_3_3_SHIFT3_V1": {
        "indicator_id": "DISPLACED_STOCHASTIC",
        "k_period": 14,
        "k_smooth": 3,
        "d_period": 3,
        "display_shift": 3,
        "overbought": 80.0,
        "oversold": 20.0,
        "preset_class": "PROJECT_EXPERIMENTAL",
    },
    # MACD
    "MACD_12_26_9_V1": {
        "indicator_id": "MACD",
        "fast": 12,
        "slow": 26,
        "signal": 9,
        "display_shift": 0,
        "preset_class": "STANDARD",
    },
    "DISPLACED_MACD_12_26_9_SHIFT3_V1": {
        "indicator_id": "DISPLACED_MACD",
        "fast": 12,
        "slow": 26,
        "signal": 9,
        "display_shift": 3,
        "preset_class": "PROJECT_EXPERIMENTAL",
    },
    # RSI
    "RSI_7_V1": {"indicator_id": "RSI", "period": 7, "preset_class": "STANDARD"},
    "RSI_14_V1": {"indicator_id": "RSI", "period": 14, "preset_class": "STANDARD"},
    "RSI_21_V1": {"indicator_id": "RSI", "period": 21, "preset_class": "STANDARD"},
    # Momentum
    "ROC_12_V1": {"indicator_id": "ROC", "period": 12, "preset_class": "STANDARD"},
    "MOMENTUM_10_V1": {"indicator_id": "MOMENTUM", "period": 10, "preset_class": "STANDARD"},
    "CCI_20_V1": {"indicator_id": "CCI", "period": 20, "preset_class": "STANDARD"},
    "WILLIAMS_R_14_V1": {"indicator_id": "WILLIAMS_R", "period": 14, "preset_class": "STANDARD"},
    # Volatility
    "ATR_14_V1": {"indicator_id": "ATR", "period": 14, "preset_class": "STANDARD"},
    "BOLLINGER_20_2_V1": {"indicator_id": "BOLLINGER", "period": 20, "std_mult": 2.0, "preset_class": "STANDARD"},
    "REALIZED_VOL_20_V1": {"indicator_id": "REALIZED_VOLATILITY", "period": 20, "preset_class": "STANDARD"},
    # ADX
    "ADX_14_V1": {"indicator_id": "ADX_DMI", "period": 14, "preset_class": "STANDARD"},
    # Structure / volume
    "CANDLE_STRUCTURE_V1": {"indicator_id": "CANDLE_STRUCTURE", "preset_class": "STANDARD"},
    "VOLUME_BASIC_20_V1": {"indicator_id": "BASIC_VOLUME", "period": 20, "preset_class": "STANDARD"},
}

# Research MA baselines
for kind in ("SMA", "EMA", "WMA"):
    for p in MA_RESEARCH_PERIODS:
        PARAMETER_REGISTRY[f"{kind}_{p}_V1"] = {
            "indicator_id": kind,
            "period": p,
            "preset_class": "STANDARD",
        }

PARAMETER_REGISTRY["SMA_CROSS_10_50_V1"] = {
    "indicator_id": "MA_CROSS",
    "kind": "SMA",
    "fast": 10,
    "slow": 50,
    "preset_class": "STANDARD",
}

INDICATOR_REGISTRY: list[dict[str, Any]] = [
    {"indicator_id": "DMA", "family": "DINAPOLI_DMA", "description": "SMA with display-only displacement"},
    {"indicator_id": "STOCHASTIC", "family": "OSCILLATOR", "description": "Causal Stochastic %K/%D"},
    {
        "indicator_id": "DISPLACED_STOCHASTIC",
        "family": "OSCILLATOR",
        "description": "Stochastic with DISPLAY_SHIFT_BARS; PROJECT_EXPERIMENTAL",
    },
    {"indicator_id": "MACD", "family": "OSCILLATOR", "description": "Causal MACD 12/26/9 baseline"},
    {
        "indicator_id": "DISPLACED_MACD",
        "family": "OSCILLATOR",
        "description": "MACD with DISPLAY_SHIFT_BARS; PROJECT_EXPERIMENTAL",
    },
    {"indicator_id": "RSI", "family": "OSCILLATOR", "description": "Wilder RSI"},
    {"indicator_id": "ROC", "family": "MOMENTUM", "description": "Rate of change"},
    {"indicator_id": "MOMENTUM", "family": "MOMENTUM", "description": "Close - close[n]"},
    {"indicator_id": "CCI", "family": "MOMENTUM", "description": "Commodity Channel Index"},
    {"indicator_id": "WILLIAMS_R", "family": "MOMENTUM", "description": "Williams %R"},
    {"indicator_id": "SMA", "family": "TREND", "description": "Simple moving average"},
    {"indicator_id": "EMA", "family": "TREND", "description": "Exponential moving average"},
    {"indicator_id": "WMA", "family": "TREND", "description": "Weighted moving average"},
    {"indicator_id": "MA_CROSS", "family": "TREND", "description": "Dual MA distance/cross"},
    {"indicator_id": "ADX_DMI", "family": "TREND", "description": "ADX / +DI / -DI"},
    {"indicator_id": "ATR", "family": "VOLATILITY", "description": "Average True Range (+ normalized)"},
    {"indicator_id": "BOLLINGER", "family": "VOLATILITY", "description": "Bollinger mid/upper/lower/width/%B"},
    {"indicator_id": "REALIZED_VOLATILITY", "family": "VOLATILITY", "description": "Rolling log-return std + range stats"},
    {"indicator_id": "CANDLE_STRUCTURE", "family": "CANDLE", "description": "Numerical candle/structure features"},
    {"indicator_id": "BASIC_VOLUME", "family": "VOLUME", "description": "Basic volume transforms (infra only)"},
]

SCHEMA_COLUMNS = [
    ("indicator_engine_version", "IDENTITY", "Engine version tag"),
    ("indicator_id", "IDENTITY", "Indicator family id"),
    ("parameter_set_id", "IDENTITY", "Registry parameter set"),
    ("source_timeframe", "IDENTITY", "Bar timeframe"),
    ("calculated_at", "CAUSAL_TIME", "Formula evaluation bar close"),
    ("available_at", "CAUSAL_TIME", "Earliest causal use (== calculated_at for closed-candle)"),
    ("displayed_at", "DISPLAY_ONLY", "Optional chart shift; NEVER availability"),
    ("values.*", "CAUSAL_OUTPUT", "Numeric indicator outputs"),
    ("signal_primitives.*", "CAUSAL_OUTPUT", "Observable states; no BUY/SELL"),
    ("valid", "DIAGNOSTIC", "Warmup/gap validity"),
    ("invalid_reason", "DIAGNOSTIC", "warmup | insufficient_contiguous_history"),
]
