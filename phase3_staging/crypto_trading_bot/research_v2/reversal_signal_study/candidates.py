"""Candidate registry builders — immutable definitions for the study."""
from __future__ import annotations

from typing import Any

from .config import DECISION_TFS
from .version import STUDY_VERSION


def _row(
    *,
    candidate_id: str,
    family: str,
    role: str,
    source_engine: str,
    source_feature_or_signal: str,
    parameter_set_id: str,
    decision_tf: str,
    direction_semantics: str,
    threshold_method: str = "NONE",
    discovery_definition: str = "",
) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "family": family,
        "role": role,
        "source_engine": source_engine,
        "source_feature_or_signal": source_feature_or_signal,
        "parameter_set_id": parameter_set_id,
        "decision_tf": decision_tf,
        "direction_semantics": direction_semantics,
        "threshold_method": threshold_method,
        "discovery_definition": discovery_definition or candidate_id,
        "validation_frozen": "YES",
        "version": STUDY_VERSION,
    }


def build_candidate_registry() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    # --- Class 2: price-only baselines ---
    baselines = [
        ("ONE_BAR_DIRECTION_CHANGE", "close direction flip vs prior bar"),
        ("CLOSE_ABOVE_PREVIOUS_HIGH", "close > prior high → UP; close < prior low → DOWN twin"),
        ("N3_BAR_EXTREME_BREAK", "close breaks 3-bar high/low"),
        ("N5_BAR_EXTREME_BREAK", "close breaks 5-bar high/low"),
        ("SHORT_TERM_SLOPE_SIGN_CHANGE", "3-bar close slope sign change"),
    ]
    for tf in DECISION_TFS:
        for name, desc in baselines:
            rows.append(
                _row(
                    candidate_id=f"PRICE_{name}_{tf}",
                    family="PRICE_ONLY",
                    role="PRICE_BASELINE",
                    source_engine="PRICE_ACTION_V1",
                    source_feature_or_signal=name,
                    parameter_set_id=name,
                    decision_tf=tf,
                    direction_semantics="EXPLICIT_UP_DOWN",
                    discovery_definition=desc,
                )
            )

    # --- Class 1: directional indicator events ---
    indicator_specs = [
        ("DMA", "DMA_3X3_V1", "PRICE_CROSS_UP_DMA", "PRICE_CROSS_DOWN_DMA", "DMA"),
        ("DMA", "DMA_7X5_V1", "PRICE_CROSS_UP_DMA", "PRICE_CROSS_DOWN_DMA", "DMA"),
        ("DMA", "DMA_25X5_V1", "PRICE_CROSS_UP_DMA", "PRICE_CROSS_DOWN_DMA", "DMA"),
        ("STOCHASTIC", "STOCH_14_3_3_V1", "K_CROSS_UP_D", "K_CROSS_DOWN_D", "STOCHASTIC"),
        ("STOCHASTIC", "STOCH_14_3_3_V1", "K_CROSS_UP_LEVEL", "K_CROSS_DOWN_LEVEL", "STOCHASTIC"),
        ("MACD", "MACD_12_26_9_V1", "MACD_CROSS_UP_SIGNAL", "MACD_CROSS_DOWN_SIGNAL", "MACD"),
        ("MACD", "MACD_12_26_9_V1", "HISTOGRAM_CROSS_UP_ZERO", "HISTOGRAM_CROSS_DOWN_ZERO", "MACD"),
        ("RSI", "RSI_14_V1", "RSI_CROSS_UP_30", "RSI_CROSS_DOWN_70", "RSI"),
        ("RSI", "RSI_14_V1", "RSI_CROSS_UP_50", "RSI_CROSS_DOWN_50", "RSI"),
        ("MA_DMI", "SMA_CROSS_10_50_V1", "MA_CROSS_UP", "MA_CROSS_DOWN", "MA/DMI"),
        ("MA_DMI", "ADX_14_V1", "DI_CROSS_UP", "DI_CROSS_DOWN", "MA/DMI"),
    ]
    for tf in DECISION_TFS:
        for family, pset, up_prim, down_prim, board_family in indicator_specs:
            cid = f"IND_{pset}_{up_prim}_{tf}"
            rows.append(
                _row(
                    candidate_id=cid,
                    family=board_family,
                    role="DIRECTIONAL_TRIGGER",
                    source_engine="INDICATOR_ENGINE_V1",
                    source_feature_or_signal=f"{up_prim}|{down_prim}",
                    parameter_set_id=pset,
                    decision_tf=tf,
                    direction_semantics=f"UP={up_prim};DOWN={down_prim}",
                )
            )

    # --- Class 3: inverse predictor trigger events ---
    pred_specs = [
        ("PRED_DMA_3X3_CROSS_UP_V1", "PRED_DMA_3X3_CROSS_DOWN_V1"),
        ("PRED_DMA_7X5_CROSS_UP_V1", "PRED_DMA_7X5_CROSS_DOWN_V1"),
        ("PRED_DMA_25X5_CROSS_UP_V1", "PRED_DMA_25X5_CROSS_DOWN_V1"),
        ("PRED_RSI_14_CROSS_UP_30_V1", "PRED_RSI_14_CROSS_DOWN_70_V1"),
        ("PRED_RSI_14_50_V1", "PRED_RSI_14_50_V1"),
        ("PRED_MACD_12_26_9_SIGNAL_CROSS_UP_V1", "PRED_MACD_12_26_9_SIGNAL_CROSS_DOWN_V1"),
        ("PRED_MACD_12_26_9_HIST_ZERO_V1", "PRED_MACD_12_26_9_HIST_ZERO_V1"),
        ("PRED_STOCH_14_K_20_POINT_V1", "PRED_STOCH_14_K_80_POINT_V1"),
        ("PRED_PROJECT_OSC_20_50_2_V1", "PRED_PROJECT_OSC_20_50_2_V1"),
    ]
    for tf in DECISION_TFS:
        for up_id, down_id in pred_specs:
            rows.append(
                _row(
                    candidate_id=f"PREDTRIG_{up_id}__{down_id}__{tf}",
                    family="INVERSE_PREDICTOR",
                    role="PREDICTOR_THRESHOLD",
                    source_engine="INVERSE_PREDICTOR_ENGINE_V1",
                    source_feature_or_signal=f"{up_id}|{down_id}",
                    parameter_set_id=f"{up_id}|{down_id}",
                    decision_tf=tf,
                    direction_semantics="UP=close crosses prior UP/level trigger from below; DOWN=from above",
                )
            )

    # --- Class 4/5: non-directional context (enrichment only) ---
    context_specs = [
        ("VOLUME_CONTEXT", "VOLUME_ACCUMULATION_ENGINE_V1", "VOLUME_ZSCORE", "VOL_WINDOW_20_V1", "P90|P10"),
        ("VOLUME_CONTEXT", "VOLUME_ACCUMULATION_ENGINE_V1", "VOLUME_RELATIVE_TO_MEAN", "VOL_WINDOW_20_V1", "P90|P10"),
        ("COMPRESSION_CONTEXT", "VOLUME_ACCUMULATION_ENGINE_V1", "COMPRESSION_RATIO", "COMPRESSION_10_50_V1", "P10|P20"),
        ("COMPRESSION_CONTEXT", "VOLUME_ACCUMULATION_ENGINE_V1", "COMPRESSION_STATE", "COMPRESSION_10_50_V1", "NATURAL_TRUE"),
        ("COMPRESSION_CONTEXT", "VOLUME_ACCUMULATION_ENGINE_V1", "COMPRESSION_DURATION", "DURATION_20_V1", "P80|P90"),
        ("EXHAUSTION_CONTEXT", "VOLUME_ACCUMULATION_ENGINE_V1", "PRICE_PROGRESS_PER_VOLUME", "EXHAUSTION_20_V1", "P10|P90"),
        ("REJECTION_CONTEXT", "VOLUME_ACCUMULATION_ENGINE_V1", "UPPER_REJECTION_STRENGTH", "REJECTION_20_V1", "P90|P95"),
        ("REJECTION_CONTEXT", "VOLUME_ACCUMULATION_ENGINE_V1", "LOWER_REJECTION_STRENGTH", "REJECTION_20_V1", "P90|P95"),
        ("VOLUME_CONTEXT", "VOLUME_ACCUMULATION_ENGINE_V1", "EFFICIENCY_RATIO", "EFFICIENCY_20_V1", "P10|P90"),
        ("PREDICTOR_CONFLUENCE", "PREDICTOR_CONFLUENCE_ENGINE_V1", "VALID_TRIGGER_COUNT", "CONF_PCT_025_ATR_050_V1", "P80|P90"),
        ("PREDICTOR_CONFLUENCE", "PREDICTOR_CONFLUENCE_ENGINE_V1", "NEAREST_CLUSTER_SIZE", "CONF_PCT_025_ATR_050_V1", "P80|P90"),
        ("PREDICTOR_CONFLUENCE", "PREDICTOR_CONFLUENCE_ENGINE_V1", "DISTINCT_FAMILY_COUNT", "CONF_PCT_025_ATR_050_V1", "P80|P90"),
        ("PREDICTOR_CONFLUENCE", "PREDICTOR_CONFLUENCE_ENGINE_V1", "TRIGGER_DISPERSION_PCT", "CONF_PCT_025_ATR_050_V1", "P10|P20"),
        ("PREDICTOR_CONFLUENCE", "PREDICTOR_CONFLUENCE_ENGINE_V1", "APPROACHING_TRIGGER_COUNT", "CONF_PCT_025_ATR_050_V1", "P80|P90"),
        ("PREDICTOR_CONFLUENCE", "PREDICTOR_CONFLUENCE_ENGINE_V1", "CROSS_TF_NEAREST_CLUSTER_TF_DIVERSITY", "CONF_PCT_025_ATR_050_V1", "P80|P90"),
    ]
    for tf in DECISION_TFS:
        for family, eng, feat, pset, thr in context_specs:
            rows.append(
                _row(
                    candidate_id=f"CTX_{feat}_{pset}_{tf}",
                    family=family,
                    role="NON_DIRECTIONAL_CONTEXT",
                    source_engine=eng,
                    source_feature_or_signal=feat,
                    parameter_set_id=pset,
                    decision_tf=tf,
                    direction_semantics="NONE",
                    threshold_method=f"DISCOVERY_{thr}",
                    discovery_definition=f"tail thresholds {thr} frozen on DISCOVERY only",
                )
            )

    return rows


def classify_counts(registry: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "CANDIDATE_COUNT": len(registry),
        "DIRECTIONAL_CANDIDATE_COUNT": sum(
            1 for r in registry if r["role"] in ("DIRECTIONAL_TRIGGER", "PREDICTOR_THRESHOLD", "PRICE_BASELINE")
        ),
        "CONTEXT_CANDIDATE_COUNT": sum(1 for r in registry if r["role"] == "NON_DIRECTIONAL_CONTEXT"),
        "PREDICTOR_CANDIDATE_COUNT": sum(1 for r in registry if r["role"] == "PREDICTOR_THRESHOLD"),
        "PRICE_BASELINE_COUNT": sum(1 for r in registry if r["role"] == "PRICE_BASELINE"),
    }
