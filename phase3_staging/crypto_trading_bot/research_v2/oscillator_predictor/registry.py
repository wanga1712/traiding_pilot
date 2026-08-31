"""OSCILLATOR_PREDICTOR_REGISTRY_V1 and inverse predictor family audit."""
from __future__ import annotations

from typing import Any

from .dno import DNO_DEFAULT_PERIOD, DNO_REFERENCE_VERSION, REFERENCE_STATUS as DNO_REF_STATUS
from .dynamic_predictor import (
    DEFAULT_PREDICTOR_CONFIG,
    PROJECT_DINAPOLI_STYLE_PREDICTOR_VERSION,
    REFERENCE_STATUS as PRED_REF_STATUS,
    TARGET_AGGREGATION,
    PredictorConfig,
)

SUPPORTED_TIMEFRAMES = ("5m", "15m", "30m", "1H", "2H", "4H", "6H", "8H", "12H", "1D")

DEFAULT_PREDICTOR_CONFIG = PredictorConfig(
    period=DNO_DEFAULT_PERIOD,
    peak_strength=2,
    lookback=100,
    samples=5,
    ob_os_level_percent=0.80,
)

OSCILLATOR_PREDICTOR_REGISTRY: dict[str, dict[str, Any]] = {
    "DNO_REF_N7_V1": {
        "predictor_id": "DNO_REF_N7_V1",
        "timeframe": "ALL",
        "oscillator_period": DNO_DEFAULT_PERIOD,
        "peak_strength": None,
        "lookback": None,
        "samples": None,
        "ob_os_level_percent": None,
        "target_aggregation": None,
        "price_source": "CLOSE",
        "formula_version": DNO_REFERENCE_VERSION,
        "reference_status": DNO_REF_STATUS,
        "causal_semantics": "CONTIGUOUS_SEGMENT_SMA",
        "warmup": DNO_DEFAULT_PERIOD,
        "segment_policy": "PREDICTOR_EXTREMA_CROSS_GAP=NO",
    },
    "OSC_PRED_PROJECT_DINAPOLI_V1": {
        "predictor_id": "OSC_PRED_PROJECT_DINAPOLI_V1",
        "timeframe": "ALL",
        "oscillator_period": DEFAULT_PREDICTOR_CONFIG.period,
        "peak_strength": DEFAULT_PREDICTOR_CONFIG.peak_strength,
        "lookback": DEFAULT_PREDICTOR_CONFIG.lookback,
        "samples": DEFAULT_PREDICTOR_CONFIG.samples,
        "ob_os_level_percent": DEFAULT_PREDICTOR_CONFIG.ob_os_level_percent,
        "target_aggregation": TARGET_AGGREGATION,
        "price_source": "CLOSE",
        "formula_version": PROJECT_DINAPOLI_STYLE_PREDICTOR_VERSION,
        "reference_status": PRED_REF_STATUS,
        "causal_semantics": "PEAK_AVAILABLE_AT=i+K",
        "warmup": "period + peak_strength + samples extrema",
        "segment_policy": "PREDICTOR_EXTREMA_CROSS_GAP=NO",
    },
}

# Part 9 — inverse predictor engine family audit (reuse INVERSE_PREDICTOR_ENGINE_V1)
INVERSE_PREDICTOR_FAMILY_STATUS: dict[str, str] = {
    "DMA_PRICE_CROSS_PREDICTOR": "SUPPORTED_ANALYTICALLY",
    "STANDARD_STOCH_THRESHOLD_PREDICTOR": "SUPPORTED_ANALYTICALLY",
    "STANDARD_STOCH_KD_CROSS_PREDICTOR": "UNSUPPORTED",
    "DINAPOLI_PREFERRED_STOCH_THRESHOLD_PREDICTOR": "SUPPORTED_ANALYTICALLY",
    "DINAPOLI_PREFERRED_STOCH_KD_CROSS_PREDICTOR": "UNSUPPORTED",
    "STANDARD_MACD_CROSS_PREDICTOR": "SUPPORTED_ANALYTICALLY",
    "DINAPOLI_MACD_CROSS_PREDICTOR": "SUPPORTED_ANALYTICALLY",
    "DNO_OB_OS_PREDICTOR": "SUPPORTED_ANALYTICALLY",
}

INVERSE_PREDICTOR_ENGINE_REUSED = "YES"
