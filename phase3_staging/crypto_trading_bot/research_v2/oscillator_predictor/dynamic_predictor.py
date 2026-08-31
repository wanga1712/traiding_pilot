"""Project DiNapoli-style dynamic OB/OS oscillator predictor (reconstruction)."""
from __future__ import annotations

from typing import Any

from crypto_trading_bot.research_v2.indicator_engine.bars import BarArrays

from .config import DEFAULT_PREDICTOR_CONFIG, PredictorConfig
from .dno import compute_masked_dno_series
from .series_engine import PredictorSeriesEngine

PROJECT_DINAPOLI_STYLE_PREDICTOR_VERSION = "PROJECT_DINAPOLI_STYLE_OSCILLATOR_PREDICTOR_V1"
REFERENCE_STATUS = "PROJECT_RECONSTRUCTION"
TARGET_AGGREGATION = "PROJECT_MEAN_CONFIRMED_EXTREMA_V1"

__all__ = [
    "PredictorConfig",
    "DEFAULT_PREDICTOR_CONFIG",
    "PROJECT_DINAPOLI_STYLE_PREDICTOR_VERSION",
    "REFERENCE_STATUS",
    "TARGET_AGGREGATION",
    "compute_predictor_at_index",
    "compute_predictor_feature_series",
]


def _run_engine_to_index(
    arrays: BarArrays,
    idx: int,
    *,
    config: PredictorConfig,
    atr: Any,
) -> dict[str, Any]:
    from crypto_trading_bot.research_v2.indicator_engine.segments import segment_starts_array

    engine = PredictorSeriesEngine(config)
    dno = compute_masked_dno_series(arrays, period=config.period)
    seg_arr = segment_starts_array(arrays.gap_flags)
    prev_seg = 0
    result: dict[str, Any] = {"predictor_state": "INSUFFICIENT_HISTORY", "valid": False}
    for i in range(idx + 1):
        seg = int(seg_arr[i])
        if seg != prev_seg:
            engine.reset_segment()
            prev_seg = seg
        result = engine.step(arrays, i, dno=dno, atr=atr)
    return result


def compute_predictor_at_index(
    arrays: BarArrays,
    idx: int,
    *,
    config: PredictorConfig,
    atr: Any = None,
) -> dict[str, Any]:
    return _run_engine_to_index(arrays, idx, config=config, atr=atr)


def compute_predictor_feature_series(
    arrays: BarArrays,
    *,
    config: PredictorConfig,
    atr: Any = None,
) -> list[dict[str, Any]]:
    return PredictorSeriesEngine(config).compute_series(arrays, atr=atr)
