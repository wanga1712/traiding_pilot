"""Feature + parameter registries for PREDICTOR_CONFLUENCE_ENGINE_V1."""
from __future__ import annotations

from typing import Any

PARAMETER_REGISTRY: dict[str, dict[str, Any]] = {
    "CONF_PCT_010_V1": {"threshold_pct": 0.10, "threshold_atr": 0.25, "preset_class": "STANDARD"},
    "CONF_PCT_025_V1": {"threshold_pct": 0.25, "threshold_atr": 0.25, "preset_class": "STANDARD"},
    "CONF_PCT_050_V1": {"threshold_pct": 0.50, "threshold_atr": 0.50, "preset_class": "STANDARD"},
    "CONF_ATR_025_V1": {"threshold_pct": 0.25, "threshold_atr": 0.25, "preset_class": "STANDARD"},
    "CONF_ATR_050_V1": {"threshold_pct": 0.50, "threshold_atr": 0.50, "preset_class": "STANDARD"},
    "CONF_ATR_100_V1": {"threshold_pct": 1.00, "threshold_atr": 1.00, "preset_class": "STANDARD"},
    "CONF_PCT_025_ATR_050_V1": {
        "threshold_pct": 0.25,
        "threshold_atr": 0.50,
        "preset_class": "STANDARD",
        "note": "default baseline: join if gap<=0.25% OR gap<=0.50 ATR",
    },
}

# Compact registry of baseline required outputs (+ major families).
_BASELINE_FEATURES = [
    ("VALID_TRIGGER_COUNT", "SNAPSHOT", "count of EXACT_ANALYTIC/NUMERIC_UNIQUE triggers"),
    ("COUNT_WITHIN_0_25_PCT", "PROXIMITY", "valid triggers within 0.25%"),
    ("COUNT_WITHIN_0_50_PCT", "PROXIMITY", "valid triggers within 0.50%"),
    ("COUNT_WITHIN_0_50_ATR", "PROXIMITY", "valid triggers within 0.50 ATR"),
    ("COUNT_WITHIN_1_00_ATR", "PROXIMITY", "valid triggers within 1.00 ATR"),
    ("DISTINCT_FAMILY_COUNT", "DIVERSITY", "unique indicator families among valid triggers"),
    ("NEAREST_TRIGGER_DISTANCE_PCT", "NEAREST", "signed % distance of nearest trigger"),
    ("NEAREST_TRIGGER_DISTANCE_ATR", "NEAREST", "signed ATR distance of nearest trigger"),
    ("NEAREST_CLUSTER_SIZE", "CLUSTER", "size of cluster nearest market"),
    ("NEAREST_CLUSTER_WIDTH_PCT", "CLUSTER", "width of nearest cluster in %"),
    ("NEAREST_CLUSTER_DISTANCE_PCT", "CLUSTER", "center distance of nearest cluster"),
    ("NEAREST_CLUSTER_DISTINCT_FAMILIES", "DIVERSITY", "families in nearest cluster"),
    ("TRIGGER_DISPERSION_PCT", "SPREAD", "std of signed % distances"),
    ("UP_REQUIRED_COUNT", "DIRECTION", "triggers requiring UP"),
    ("DOWN_REQUIRED_COUNT", "DIRECTION", "triggers requiring DOWN"),
    ("APPROACHING_TRIGGER_COUNT", "TEMPORAL", "triggers closer than prior bar"),
    ("TRIGGER_DISPERSION_DELTA", "TEMPORAL", "dispersion change vs prior bar"),
    ("CROSS_TF_NEAREST_CLUSTER_SIZE", "CROSS_TF", "nearest cluster size across TFs"),
    ("CROSS_TF_NEAREST_CLUSTER_TF_DIVERSITY", "CROSS_TF", "TF diversity of nearest cross-TF cluster"),
    ("CLUSTER_COUNT", "CLUSTER", "number of 1D adjacent-gap clusters"),
    ("FAMILY_DIVERSITY_RATIO", "DIVERSITY", "distinct families / valid triggers"),
    ("TRIGGERS_ABOVE_COUNT", "STRUCTURE", "triggers above market"),
    ("TRIGGERS_BELOW_COUNT", "STRUCTURE", "triggers below market"),
    ("CONVERGENCE_SCORE", "CONVERGENCE", "1/(1+dispersion_pct) deterministic"),
    ("MEAN_TRIGGER_APPROACH_SPEED", "TEMPORAL", "mean reduction in |distance_pct|"),
]

FEATURE_REGISTRY: list[dict[str, Any]] = [
    {
        "feature_id": fid,
        "family": fam,
        "description": desc,
        "raw_family_normalized": "BOTH",
        "within_cross_tf": "BOTH" if fid.startswith("CROSS_TF") else "WITHIN_TF",
        "unit": "varies",
        "causal": "YES",
        "engine_version": "PREDICTOR_CONFLUENCE_ENGINE_V1",
    }
    for fid, fam, desc in _BASELINE_FEATURES
]

SCHEMA_COLUMNS = [
    ("confluence_engine_version", "IDENTITY", "Engine version"),
    ("predictor_engine_version", "IDENTITY", "Frozen inverse engine"),
    ("decision_time", "CAUSAL_TIME", "Decision timestamp"),
    ("parameter_set_id", "IDENTITY", "Clustering thresholds"),
    ("view", "IDENTITY", "RAW | FAMILY_NORMALIZED"),
    ("scope", "IDENTITY", "WITHIN_TF | CROSS_TF"),
    ("features.*", "CAUSAL_OUTPUT", "Confluence features"),
]
