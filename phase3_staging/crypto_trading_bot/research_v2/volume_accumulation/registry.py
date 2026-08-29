"""Feature + parameter registries for VOLUME_ACCUMULATION_ENGINE_V1."""
from __future__ import annotations

from typing import Any

VOL_WINDOWS = [5, 10, 20, 50, 100]
SHORT_MED_LONG = {"SHORT": 10, "MEDIUM": 20, "LONG": 100}

PARAMETER_REGISTRY: dict[str, dict[str, Any]] = {}
for w in VOL_WINDOWS:
    PARAMETER_REGISTRY[f"VOL_WINDOW_{w}_V1"] = {
        "family": "VOLUME_INTENSITY",
        "window": w,
        "preset_class": "STANDARD",
    }

PARAMETER_REGISTRY["EFFICIENCY_10_V1"] = {"family": "EFFICIENCY_CHOP", "window": 10, "preset_class": "STANDARD"}
PARAMETER_REGISTRY["EFFICIENCY_20_V1"] = {"family": "EFFICIENCY_CHOP", "window": 20, "preset_class": "STANDARD"}
PARAMETER_REGISTRY["RANGE_20_V1"] = {"family": "RANGE_BALANCE", "window": 20, "preset_class": "STANDARD"}
PARAMETER_REGISTRY["RANGE_50_V1"] = {"family": "RANGE_BALANCE", "window": 50, "preset_class": "STANDARD"}

for short, long in ((5, 20), (10, 50), (20, 100)):
    PARAMETER_REGISTRY[f"COMPRESSION_{short}_{long}_V1"] = {
        "family": "COMPRESSION",
        "short_window": short,
        "long_window": long,
        "threshold": 0.5,
        "preset_class": "STANDARD",
    }

PARAMETER_REGISTRY["PV_INTERACTION_20_V1"] = {
    "family": "PRICE_VOLUME_INTERACTION",
    "window": 20,
    "preset_class": "STANDARD",
}
PARAMETER_REGISTRY["CONCENTRATION_20_V1"] = {
    "family": "VOLUME_CONCENTRATION",
    "window": 20,
    "preset_class": "STANDARD",
}
PARAMETER_REGISTRY["EXHAUSTION_20_V1"] = {"family": "EXHAUSTION", "window": 20, "preset_class": "STANDARD"}
PARAMETER_REGISTRY["REJECTION_20_V1"] = {"family": "REJECTION", "window": 20, "confirm_bars": 1, "preset_class": "STANDARD"}
PARAMETER_REGISTRY["BREAKOUT_ATTEMPTS_20_V1"] = {
    "family": "BREAKOUT_ATTEMPTS",
    "window": 20,
    "confirm_bars": 1,
    "preset_class": "STANDARD",
}
PARAMETER_REGISTRY["COMPRESSION_EXPANSION_10_50_V1"] = {
    "family": "COMPRESSION_EXPANSION",
    "short_window": 10,
    "long_window": 50,
    "threshold": 0.5,
    "preset_class": "STANDARD",
}
PARAMETER_REGISTRY["DURATION_20_V1"] = {
    "family": "DURATION",
    "window": 20,
    "short_window": 10,
    "long_window": 50,
    "threshold": 0.5,
    "vol_spike_z": 2.0,
    "preset_class": "STANDARD",
}
PARAMETER_REGISTRY["CONTEXT_BUNDLE_V1"] = {
    "family": "CONTEXT_BUNDLE",
    "volume_window": 20,
    "efficiency_window": 10,
    "range_window": 20,
    "short_window": 10,
    "long_window": 50,
    "threshold": 0.5,
    "preset_class": "STANDARD",
}

FEATURE_REGISTRY: list[dict[str, Any]] = [
    # A
    {"feature_id": "VOLUME_RAW", "family": "VOLUME_INTENSITY", "description": "Bar volume", "unit": "volume", "causal": "YES", "warmup": "0"},
    {"feature_id": "VOLUME_ROLLING_MEAN", "family": "VOLUME_INTENSITY", "description": "Rolling mean volume", "unit": "volume", "causal": "YES", "warmup": "window"},
    {"feature_id": "VOLUME_ROLLING_MEDIAN", "family": "VOLUME_INTENSITY", "description": "Rolling median volume", "unit": "volume", "causal": "YES", "warmup": "window"},
    {"feature_id": "VOLUME_RELATIVE_TO_MEAN", "family": "VOLUME_INTENSITY", "description": "vol / mean", "unit": "ratio", "causal": "YES", "warmup": "window"},
    {"feature_id": "VOLUME_RELATIVE_TO_MEDIAN", "family": "VOLUME_INTENSITY", "description": "vol / median", "unit": "ratio", "causal": "YES", "warmup": "window"},
    {"feature_id": "VOLUME_ZSCORE", "family": "VOLUME_INTENSITY", "description": "z-score vs rolling mean/std", "unit": "z", "causal": "YES", "warmup": "window"},
    {"feature_id": "VOLUME_CHANGE_1", "family": "VOLUME_INTENSITY", "description": "1-bar volume change pct", "unit": "pct", "causal": "YES", "warmup": "1"},
    {"feature_id": "VOLUME_CHANGE_N", "family": "VOLUME_INTENSITY", "description": "N-bar volume change pct", "unit": "pct", "causal": "YES", "warmup": "window"},
    {"feature_id": "VOLUME_SLOPE", "family": "VOLUME_INTENSITY", "description": "1-bar volume delta", "unit": "volume", "causal": "YES", "warmup": "1"},
    {"feature_id": "VOLUME_PERCENTILE", "family": "VOLUME_INTENSITY", "description": "percentile rank in window", "unit": "pctile", "causal": "YES", "warmup": "window"},
    {"feature_id": "VOLUME_CV", "family": "VOLUME_INTENSITY", "description": "std/mean volume", "unit": "ratio", "causal": "YES", "warmup": "window"},
    # B
    {"feature_id": "OBV", "family": "PRICE_VOLUME_INTERACTION", "description": "On-balance volume (close-direction proxy)", "unit": "volume", "causal": "YES", "warmup": "1"},
    {"feature_id": "OBV_SLOPE", "family": "PRICE_VOLUME_INTERACTION", "description": "OBV 1-bar delta", "unit": "volume", "causal": "YES", "warmup": "2"},
    {"feature_id": "VWAP_ROLLING", "family": "PRICE_VOLUME_INTERACTION", "description": "Rolling VWAP of typical price", "unit": "price", "causal": "YES", "warmup": "window"},
    {"feature_id": "DISTANCE_TO_VWAP_PCT", "family": "PRICE_VOLUME_INTERACTION", "description": "(close-vwap)/vwap", "unit": "pct", "causal": "YES", "warmup": "window"},
    {"feature_id": "DISTANCE_TO_VWAP_ATR", "family": "PRICE_VOLUME_INTERACTION", "description": "(close-vwap)/ATR", "unit": "atr", "causal": "YES", "warmup": "window"},
    {"feature_id": "CMF", "family": "PRICE_VOLUME_INTERACTION", "description": "Chaikin Money Flow", "unit": "ratio", "causal": "YES", "warmup": "window"},
    {"feature_id": "MFI", "family": "PRICE_VOLUME_INTERACTION", "description": "Money Flow Index", "unit": "index", "causal": "YES", "warmup": "window+1"},
    {"feature_id": "CLOSE_LOCATION_VALUE", "family": "PRICE_VOLUME_INTERACTION", "description": "CLV = ((c-l)-(h-c))/(h-l)", "unit": "ratio", "causal": "YES", "warmup": "0"},
    {"feature_id": "VOLUME_WEIGHTED_CLOSE_LOCATION", "family": "PRICE_VOLUME_INTERACTION", "description": "CLV * volume", "unit": "volume", "causal": "YES", "warmup": "0"},
    {"feature_id": "UP_BAR_VOLUME", "family": "PRICE_VOLUME_INTERACTION", "description": "Volume on up-close bars (proxy, not taker buy)", "unit": "volume", "causal": "YES", "warmup": "1"},
    {"feature_id": "DOWN_BAR_VOLUME", "family": "PRICE_VOLUME_INTERACTION", "description": "Volume on down-close bars (proxy)", "unit": "volume", "causal": "YES", "warmup": "1"},
    {"feature_id": "UP_DOWN_VOLUME_RATIO", "family": "PRICE_VOLUME_INTERACTION", "description": "Rolling up/down volume proxy ratio", "unit": "ratio", "causal": "YES", "warmup": "window"},
    # C
    {"feature_id": "ROLLING_HIGH", "family": "COMPRESSION", "description": "Rolling high", "unit": "price", "causal": "YES", "warmup": "window"},
    {"feature_id": "ROLLING_LOW", "family": "COMPRESSION", "description": "Rolling low", "unit": "price", "causal": "YES", "warmup": "window"},
    {"feature_id": "RANGE_WIDTH_ABS", "family": "COMPRESSION", "description": "high-low of window", "unit": "price", "causal": "YES", "warmup": "window"},
    {"feature_id": "RANGE_WIDTH_PCT", "family": "COMPRESSION", "description": "range/mid", "unit": "pct", "causal": "YES", "warmup": "window"},
    {"feature_id": "RANGE_WIDTH_ATR", "family": "COMPRESSION", "description": "range/ATR", "unit": "atr", "causal": "YES", "warmup": "window"},
    {"feature_id": "ROLLING_STD", "family": "COMPRESSION", "description": "close std", "unit": "price", "causal": "YES", "warmup": "window"},
    {"feature_id": "REALIZED_VOLATILITY", "family": "COMPRESSION", "description": "log-return std", "unit": "vol", "causal": "YES", "warmup": "window"},
    {"feature_id": "ATR_RELATIVE", "family": "COMPRESSION", "description": "ATR/price", "unit": "ratio", "causal": "YES", "warmup": "14"},
    {"feature_id": "ATR_PERCENTILE", "family": "COMPRESSION", "description": "ATR percentile in long window", "unit": "pctile", "causal": "YES", "warmup": "long"},
    {"feature_id": "BOLLINGER_WIDTH", "family": "COMPRESSION", "description": "(upper-lower)/mid", "unit": "ratio", "causal": "YES", "warmup": "20"},
    {"feature_id": "BOLLINGER_WIDTH_PERCENTILE", "family": "COMPRESSION", "description": "BB width percentile", "unit": "pctile", "causal": "YES", "warmup": "long"},
    {"feature_id": "COMPRESSION_RATIO", "family": "COMPRESSION", "description": "short_range / long_range", "unit": "ratio", "causal": "YES", "warmup": "long"},
    # D
    {"feature_id": "NET_MOVE", "family": "EFFICIENCY_CHOP", "description": "close_t - close_t-N", "unit": "price", "causal": "YES", "warmup": "window"},
    {"feature_id": "PATH_LENGTH", "family": "EFFICIENCY_CHOP", "description": "sum abs close deltas", "unit": "price", "causal": "YES", "warmup": "window"},
    {"feature_id": "EFFICIENCY_RATIO", "family": "EFFICIENCY_CHOP", "description": "abs(net)/path", "unit": "ratio", "causal": "YES", "warmup": "window"},
    {"feature_id": "DIRECTIONAL_EFFICIENCY", "family": "EFFICIENCY_CHOP", "description": "signed net/path", "unit": "ratio", "causal": "YES", "warmup": "window"},
    {"feature_id": "BAR_OVERLAP_RATIO", "family": "EFFICIENCY_CHOP", "description": "overlap with prior bar / ranges", "unit": "ratio", "causal": "YES", "warmup": "1"},
    {"feature_id": "AVERAGE_BAR_OVERLAP", "family": "EFFICIENCY_CHOP", "description": "mean overlap in window", "unit": "ratio", "causal": "YES", "warmup": "window"},
    {"feature_id": "CLOSE_DISPERSION", "family": "EFFICIENCY_CHOP", "description": "std of closes", "unit": "price", "causal": "YES", "warmup": "window"},
    {"feature_id": "HIGH_LOW_DISPERSION", "family": "EFFICIENCY_CHOP", "description": "mean bar range", "unit": "price", "causal": "YES", "warmup": "window"},
    # E
    {"feature_id": "BARS_IN_RANGE", "family": "RANGE_BALANCE", "description": "bars with close inside rolling range core", "unit": "count", "causal": "YES", "warmup": "window"},
    {"feature_id": "RANGE_OCCUPANCY", "family": "RANGE_BALANCE", "description": "fraction of closes in range", "unit": "ratio", "causal": "YES", "warmup": "window"},
    {"feature_id": "TIME_NEAR_RANGE_MID", "family": "RANGE_BALANCE", "description": "fraction near mid", "unit": "ratio", "causal": "YES", "warmup": "window"},
    {"feature_id": "TIME_NEAR_RANGE_HIGH", "family": "RANGE_BALANCE", "description": "fraction near high", "unit": "ratio", "causal": "YES", "warmup": "window"},
    {"feature_id": "TIME_NEAR_RANGE_LOW", "family": "RANGE_BALANCE", "description": "fraction near low", "unit": "ratio", "causal": "YES", "warmup": "window"},
    {"feature_id": "CLOSES_INSIDE_CORE_RANGE", "family": "RANGE_BALANCE", "description": "count in central 50% of range", "unit": "count", "causal": "YES", "warmup": "window"},
    {"feature_id": "CORE_RANGE_WIDTH", "family": "RANGE_BALANCE", "description": "central 50% width", "unit": "price", "causal": "YES", "warmup": "window"},
    {"feature_id": "PRICE_DENSITY", "family": "RANGE_BALANCE", "description": "bars / range_width", "unit": "density", "causal": "YES", "warmup": "window"},
    # F–K families summarized as composite feature_ids used in compute
    {"feature_id": "VOLUME_PER_PRICE_RANGE", "family": "VOLUME_CONCENTRATION", "description": "cum vol / range", "unit": "vol/price", "causal": "YES", "warmup": "window"},
    {"feature_id": "HIGH_VOLUME_LOW_PROGRESS_SCORE", "family": "VOLUME_CONCENTRATION", "description": "cum_vol / (1+abs(net))", "unit": "score", "causal": "YES", "warmup": "window"},
    {"feature_id": "LOW_VOLUME_HIGH_PROGRESS_SCORE", "family": "VOLUME_CONCENTRATION", "description": "abs(net) / (1+cum_vol)", "unit": "score", "causal": "YES", "warmup": "window"},
    {"feature_id": "PRICE_SLOPE", "family": "EXHAUSTION", "description": "close slope", "unit": "price", "causal": "YES", "warmup": "1"},
    {"feature_id": "PRICE_PROGRESS_PER_VOLUME", "family": "EXHAUSTION", "description": "net/cum_vol", "unit": "price/vol", "causal": "YES", "warmup": "window"},
    {"feature_id": "UPPER_REJECTION_STRENGTH", "family": "REJECTION", "description": "upper wick ratio after high attempt", "unit": "ratio", "causal": "YES", "warmup": "window"},
    {"feature_id": "LOWER_REJECTION_STRENGTH", "family": "REJECTION", "description": "lower wick ratio after low attempt", "unit": "ratio", "causal": "YES", "warmup": "window"},
    {"feature_id": "COUNT_UPSIDE_BREAKOUT_ATTEMPTS", "family": "BREAKOUT_ATTEMPTS", "description": "causal upside break attempts", "unit": "count", "causal": "YES", "warmup": "window"},
    {"feature_id": "COUNT_FAILED_UPSIDE_BREAKOUTS", "family": "BREAKOUT_ATTEMPTS", "description": "exceed high then close back (confirm=1)", "unit": "count", "causal": "YES", "warmup": "window"},
    {"feature_id": "COMPRESSION_STATE", "family": "COMPRESSION_EXPANSION", "description": "short/long range below threshold", "unit": "bool", "causal": "YES", "warmup": "long"},
    {"feature_id": "COMPRESSION_DURATION", "family": "DURATION", "description": "bars in compression state", "unit": "bars", "causal": "YES", "warmup": "long"},
    {"feature_id": "EXPANSION_AFTER_COMPRESSION", "family": "COMPRESSION_EXPANSION", "description": "left compression this bar", "unit": "bool", "causal": "YES", "warmup": "long"},
]

SCHEMA_COLUMNS = [
    ("feature_engine_version", "IDENTITY", "Engine version"),
    ("feature_family", "IDENTITY", "Family id"),
    ("parameter_set_id", "IDENTITY", "Parameter registry key"),
    ("source_timeframe", "IDENTITY", "Bar TF"),
    ("calculated_at", "CAUSAL_TIME", "Bar close used"),
    ("available_at", "CAUSAL_TIME", "Earliest causal use"),
    ("values.*", "CAUSAL_OUTPUT", "Feature values"),
    ("valid", "DIAGNOSTIC", "Warmup/gap validity"),
    ("invalid_reason", "DIAGNOSTIC", "INVALID_WARMUP | insufficient_contiguous_history"),
]
