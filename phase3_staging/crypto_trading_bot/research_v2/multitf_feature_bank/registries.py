"""Versioned parameter registries for MULTITF_INDICATOR_FEATURE_BANK_V1."""
from __future__ import annotations

from typing import Any

from crypto_trading_bot.research_v2.resampling import UI_TIMEFRAMES

from .warmup import registry_warmup_bars

MA_PERIODS = (3, 5, 7, 10, 14, 20, 25)
MA_SHIFTS = (0, 2, 3, 5, 8)
MA_TYPES = ("SMA", "EMA", "WMA")

STOCH_CONFIGS = (
    {"k_period": 5, "k_smooth": 3, "d_period": 3, "label": "5/3/3"},
    {"k_period": 9, "k_smooth": 3, "d_period": 3, "label": "9/3/3"},
    {"k_period": 14, "k_smooth": 3, "d_period": 3, "label": "14/3/3"},
    {"k_period": 21, "k_smooth": 5, "d_period": 5, "label": "21/5/5"},
)
STOCH_SHIFTS = (0, 2, 3, 5)

MACD_CONFIGS = (
    {"fast": 5, "slow": 13, "signal": 4, "label": "5/13/4"},
    {"fast": 8, "slow": 21, "signal": 5, "label": "8/21/5"},
    {"fast": 12, "slow": 26, "signal": 9, "label": "12/26/9"},
)
MACD_SHIFTS = (0, 2, 3, 5)

# Curated DMA pairs — includes mandatory 3x3, 7x5, 25x5 + neighbors
DMA_CURATED: list[tuple[int, int]] = [
    (3, 0),
    (3, 2),
    (3, 3),
    (3, 5),
    (5, 3),
    (5, 5),
    (7, 3),
    (7, 5),
    (10, 5),
    (14, 5),
    (14, 8),
    (20, 5),
    (25, 5),
    (25, 8),
]

HISTORICAL_SOURCES = {
    "dma_3x3": "phase3_staging/crypto_trading_bot/research_v2/indicator_engine/registry.py:DMA_3X3_V1",
    "dma_7x5": "phase3_staging/crypto_trading_bot/research_v2/indicator_engine/registry.py:DMA_7X5_V1",
    "dma_25x5": "phase3_staging/crypto_trading_bot/research_v2/indicator_engine/registry.py:DMA_25X5_V1",
    "stoch_14_3_3": "phase3_staging/crypto_trading_bot/research_v2/indicator_engine/registry.py:STOCH_14_3_3_V1",
    "displaced_stoch_shift3": "phase3_staging/crypto_trading_bot/research_v2/indicator_engine/registry.py:DISPLACED_STOCH_14_3_3_SHIFT3_V1",
    "macd_12_26_9": "phase3_staging/crypto_trading_bot/research_v2/indicator_engine/registry.py:MACD_12_26_9_V1",
    "displaced_macd_shift3": "phase3_staging/crypto_trading_bot/research_v2/indicator_engine/registry.py:DISPLACED_MACD_12_26_9_SHIFT3_V1",
    "reconstruction_freeze": "artifacts/ORIGINAL-DINAPOLI-STYLE-WHEN-RECONSTRUCTION-1/RETURN_SUMMARY_v1.json",
}


def _dma_id(ma_type: str, period: int, shift: int) -> str:
    return f"DMA_{ma_type}_P{period}_SHIFT{shift}_V1"


def _stoch_id(cfg: dict, shift: int) -> str:
    k, ks, d = cfg["k_period"], cfg["k_smooth"], cfg["d_period"]
    prefix = "STOCH" if shift == 0 else "DISPLACED_STOCH"
    return f"{prefix}_K{k}_KS{ks}_D{d}_SHIFT{shift}_V1"


def _macd_id(cfg: dict, shift: int) -> str:
    f, s, sig = cfg["fast"], cfg["slow"], cfg["signal"]
    prefix = "MACD" if shift == 0 else "DISPLACED_MACD"
    return f"{prefix}_{f}_{s}_{sig}_SHIFT{shift}_V1"


def build_dma_registry() -> dict[str, dict[str, Any]]:
    reg: dict[str, dict[str, Any]] = {}
    for ma_type in MA_TYPES:
        for period, shift in DMA_CURATED:
            fid = _dma_id(ma_type, period, shift)
            preset = "DINAPOLI_STYLE" if ma_type == "SMA" and (period, shift) in ((3, 3), (7, 5), (25, 5)) else "PROJECT_RESEARCH"
            row = {
                "feature_set_id": fid,
                "family": "DMA",
                "ma_type": ma_type,
                "period": period,
                "display_shift": shift,
                "formula_version": "MA_V1",
                "causal_semantics": "CLOSED_CANDLE",
                "source_engine": "INDICATOR_ENGINE_V1",
                "reference_status": "NUMERIC_REFERENCE_TESTED" if ma_type == "SMA" and shift in (0, 3) else "PROJECT_RESEARCH",
                "preset_class": preset,
                "implementation_name": "DINAPOLI_DMA" if preset == "DINAPOLI_STYLE" else "PROJECT_RESEARCH_DMA",
            }
            row["warmup_bars"] = registry_warmup_bars(row)
            reg[fid] = row
    return reg


def build_stochastic_registry() -> dict[str, dict[str, Any]]:
    reg: dict[str, dict[str, Any]] = {}
    for cfg in STOCH_CONFIGS:
        for shift in STOCH_SHIFTS:
            fid = _stoch_id(cfg, shift)
            row = {
                "feature_set_id": fid,
                "family": "STOCHASTIC",
                "k_period": cfg["k_period"],
                "k_smooth": cfg["k_smooth"],
                "d_period": cfg["d_period"],
                "display_shift": shift,
                "overbought": 80.0,
                "oversold": 20.0,
                "formula_version": "STOCH_CANONICAL_V1",
                "causal_semantics": "CLOSED_CANDLE",
                "source_engine": "INDICATOR_ENGINE_V1",
                "reference_status": "NUMERIC_REFERENCE_TESTED" if cfg["label"] == "14/3/3" and shift == 0 else "PROJECT_RESEARCH",
                "preset_class": "STANDARD" if shift == 0 else "PROJECT_DISPLACED_STOCHASTIC",
                "implementation_name": "STANDARD_STOCHASTIC" if shift == 0 else "PROJECT_DISPLACED_STOCHASTIC",
            }
            row["warmup_bars"] = registry_warmup_bars(row)
            reg[fid] = row
    # DiNapoli Preferred Stochastic reference — separate from canonical SMA-smoothed Stochastic
    din_row = {
        "feature_set_id": "DINAPOLI_PREFERRED_STOCHASTIC_REFERENCE_V1",
        "family": "STOCHASTIC",
        "k_period": 8,
        "slowing": 3,
        "d_period": 3,
        "display_shift": 0,
        "overbought": 80.0,
        "oversold": 20.0,
        "formula_version": "DINAPOLI_PREFERRED_STOCH_REFERENCE_V1",
        "causal_semantics": "CLOSED_CANDLE",
        "source_engine": "INDICATOR_ENGINE_V1",
        "reference_status": "DINAPOLI_REFERENCE_IMPLEMENTATION",
        "preset_class": "DINAPOLI_REFERENCE",
        "implementation_name": "DINAPOLI_PREFERRED_STOCHASTIC",
        "smoothing": "MODIFIED_RECURSIVE",
        "threshold_profile": "PROJECT_GENERIC_80_20",
    }
    din_row["warmup_bars"] = registry_warmup_bars(din_row)
    reg[din_row["feature_set_id"]] = din_row
    return reg


def build_macd_registry() -> dict[str, dict[str, Any]]:
    reg: dict[str, dict[str, Any]] = {}
    for cfg in MACD_CONFIGS:
        for shift in MACD_SHIFTS:
            fid = _macd_id(cfg, shift)
            row = {
                "feature_set_id": fid,
                "family": "MACD",
                "fast": cfg["fast"],
                "slow": cfg["slow"],
                "signal": cfg["signal"],
                "display_shift": shift,
                "formula_version": "MACD_CANONICAL_V1",
                "causal_semantics": "CLOSED_CANDLE",
                "source_engine": "INDICATOR_ENGINE_V1",
                "reference_status": "NUMERIC_REFERENCE_TESTED" if cfg["label"] == "12/26/9" and shift == 0 else "PROJECT_RESEARCH",
                "preset_class": "STANDARD" if shift == 0 else "PROJECT_DISPLACED_MACD",
                "implementation_name": "STANDARD_MACD" if shift == 0 else "PROJECT_DISPLACED_MACD",
            }
            row["warmup_bars"] = registry_warmup_bars(row)
            reg[fid] = row
    din_row = {
        "feature_set_id": "DINAPOLI_MACD_REFERENCE_V1",
        "family": "MACD",
        "fast_alpha": 0.213,
        "slow_alpha": 0.108,
        "signal_alpha": 0.199,
        "fast_period_equiv": 8.3896,
        "slow_period_equiv": 17.5185,
        "signal_period_equiv": 9.0503,
        "display_shift": 0,
        "formula_version": "DINAPOLI_MACD_REFERENCE_V1",
        "causal_semantics": "CLOSED_CANDLE",
        "source_engine": "INDICATOR_ENGINE_V1",
        "reference_status": "DINAPOLI_REFERENCE_IMPLEMENTATION",
        "preset_class": "DINAPOLI_REFERENCE",
        "implementation_name": "DINAPOLI_REFERENCE_MACD",
        "init_convention": "alpha_ema_seed_close0_signal_seed_macd0",
    }
    din_row["warmup_bars"] = registry_warmup_bars(din_row)
    reg[din_row["feature_set_id"]] = din_row
    return reg


DMA_REGISTRY = build_dma_registry()
STOCHASTIC_REGISTRY = build_stochastic_registry()
MACD_REGISTRY = build_macd_registry()

FEATURE_OUTPUTS = {
    "DMA": [
        "MA_VALUE",
        "PRICE_MINUS_MA",
        "PRICE_MINUS_MA_PCT",
        "PRICE_MINUS_MA_ATR",
        "MA_SLOPE_1",
        "MA_SLOPE_3",
        "PRICE_CROSS_UP_MA",
        "PRICE_CROSS_DOWN_MA",
        "MA_SLOPE_TURN_UP",
        "MA_SLOPE_TURN_DOWN",
        "DISPLAY_ALIGNED_MA_VALUE",
        "DISPLAY_ALIGNED_PRICE_MINUS_MA",
        "DISPLAY_ALIGNED_PRICE_MINUS_MA_PCT",
        "DISPLAY_ALIGNED_PRICE_MINUS_MA_ATR",
        "DISPLAY_ALIGNED_MA_SLOPE_1",
        "DISPLAY_ALIGNED_MA_SLOPE_3",
        "DISPLAY_ALIGNED_PRICE_CROSS_UP_MA",
        "DISPLAY_ALIGNED_PRICE_CROSS_DOWN_MA",
        "DISPLAY_ALIGNED_MA_SLOPE_TURN_UP",
        "DISPLAY_ALIGNED_MA_SLOPE_TURN_DOWN",
    ],
    "STOCHASTIC": [
        "RAW_K",
        "K",
        "D",
        "K_MINUS_D",
        "K_MINUS_D_SLOPE",
        "K_CROSS_UP_D",
        "K_CROSS_DOWN_D",
        "K_SLOPE",
        "D_SLOPE",
        "DIST_TO_OVERSOLD",
        "DIST_TO_OVERBOUGHT",
        "OVERBOUGHT_80",
        "OVERSOLD_20",
        "DISPLAY_ALIGNED_RAW_K",
        "DISPLAY_ALIGNED_K",
        "DISPLAY_ALIGNED_D",
        "DISPLAY_ALIGNED_K_MINUS_D",
        "DISPLAY_ALIGNED_K_MINUS_D_SLOPE",
        "DISPLAY_ALIGNED_K_SLOPE",
        "DISPLAY_ALIGNED_D_SLOPE",
        "DISPLAY_ALIGNED_K_CROSS_UP_D",
        "DISPLAY_ALIGNED_K_CROSS_DOWN_D",
        "DISPLAY_ALIGNED_DIST_TO_OVERSOLD",
        "DISPLAY_ALIGNED_DIST_TO_OVERBOUGHT",
        "DISPLAY_ALIGNED_OVERBOUGHT",
        "DISPLAY_ALIGNED_OVERSOLD",
    ],
    "MACD": [
        "MACD",
        "SIGNAL",
        "HIST",
        "MACD_MINUS_SIGNAL",
        "MACD_SLOPE",
        "SIGNAL_SLOPE",
        "HIST_SLOPE",
        "MACD_CROSS_UP_SIGNAL",
        "MACD_CROSS_DOWN_SIGNAL",
        "HIST_CROSS_UP_ZERO",
        "HIST_CROSS_DOWN_ZERO",
        "HIST_CONTRACTING_NEGATIVE",
        "HIST_CONTRACTING_POSITIVE",
        "DISPLAY_ALIGNED_MACD",
        "DISPLAY_ALIGNED_SIGNAL",
        "DISPLAY_ALIGNED_HIST",
        "DISPLAY_ALIGNED_MACD_MINUS_SIGNAL",
        "DISPLAY_ALIGNED_MACD_SLOPE",
        "DISPLAY_ALIGNED_SIGNAL_SLOPE",
        "DISPLAY_ALIGNED_HIST_SLOPE",
        "DISPLAY_ALIGNED_MACD_CROSS_UP_SIGNAL",
        "DISPLAY_ALIGNED_MACD_CROSS_DOWN_SIGNAL",
        "DISPLAY_ALIGNED_HIST_CROSS_UP_ZERO",
        "DISPLAY_ALIGNED_HIST_CROSS_DOWN_ZERO",
        "DISPLAY_ALIGNED_HIST_CONTRACTING_NEGATIVE",
        "DISPLAY_ALIGNED_HIST_CONTRACTING_POSITIVE",
    ],
    "GEOMETRY": [
        "AB_LENGTH",
        "AB_LENGTH_ATR",
        "REFERENCE_AB_LENGTH",
        "R_CURRENT",
        "R_MINUS_1",
        "DIST_TO_R1",
        "CURRENT_VS_REFERENCE_AB_RATIO",
        "PRIOR_SAME_DIRECTION_LEG_LENGTH",
        "DIST_TO_COP",
        "DIST_TO_OP",
        "DIST_TO_XOP",
        "DIST_TO_COP_ATR",
        "DIST_TO_OP_ATR",
        "DIST_TO_XOP_ATR",
        "GEOMETRY_STAGE",
        "COP_REACHED",
        "OP_REACHED",
        "XOP_REACHED",
    ],
    "DNO": [
        "DNO_VALUE",
        "DNO_SLOPE_1",
        "DNO_SLOPE_3",
        "DNO_ZERO_CROSS_UP",
        "DNO_ZERO_CROSS_DOWN",
        "DNO_DISTANCE_FROM_ZERO",
        "DNO_ABS",
        "DNO_ATR_NORMALIZED",
    ],
    "OSC_PREDICTOR": [
        "DYNAMIC_OB_OSC_TARGET",
        "DYNAMIC_OS_OSC_TARGET",
        "PREDICTOR_OB_PRICE_NEXT_BAR",
        "PREDICTOR_OS_PRICE_NEXT_BAR",
        "PRICE_DISTANCE_TO_OB",
        "PRICE_DISTANCE_TO_OS",
        "PRICE_DISTANCE_TO_OB_PCT",
        "PRICE_DISTANCE_TO_OS_PCT",
        "PRICE_DISTANCE_TO_OB_ATR",
        "PRICE_DISTANCE_TO_OS_ATR",
        "BAND_WIDTH",
        "BAND_WIDTH_PCT",
        "BAND_WIDTH_ATR",
        "CURRENT_PRICE_POSITION_IN_BAND",
        "ABOVE_PREDICTOR_OB",
        "BELOW_PREDICTOR_OS",
        "INSIDE_PREDICTOR_BAND",
        "CROSSED_OB_BAND_UP",
        "CROSSED_OB_BAND_DOWN",
        "CROSSED_OS_BAND_UP",
        "CROSSED_OS_BAND_DOWN",
        "OB_BAND_SLOPE_1",
        "OS_BAND_SLOPE_1",
        "OB_BAND_SLOPE_3",
        "OS_BAND_SLOPE_3",
        "OB_BAND_CONVERGING_TO_PRICE",
        "OS_BAND_CONVERGING_TO_PRICE",
        "BAND_COMPRESSION",
        "BAND_EXPANSION",
        "DNO_CUSTOM_OB_TARGET",
        "DNO_CUSTOM_OS_TARGET",
        "PRICE_TO_CUSTOM_OB",
        "PRICE_TO_CUSTOM_OS",
        "DIST_TO_CUSTOM_OB_PRICE",
        "DIST_TO_CUSTOM_OS_PRICE",
        "DIST_TO_CUSTOM_OB_PCT",
        "DIST_TO_CUSTOM_OS_PCT",
        "DIST_TO_CUSTOM_OB_ATR",
        "DIST_TO_CUSTOM_OS_ATR",
    ],
}


def declared_outputs(family: str) -> list[str]:
    return list(FEATURE_OUTPUTS[family])


def build_feature_registry_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for tf in UI_TIMEFRAMES:
        for reg, family in (
            (DMA_REGISTRY, "DMA"),
            (STOCHASTIC_REGISTRY, "STOCHASTIC"),
            (MACD_REGISTRY, "MACD"),
        ):
            for ps_id, meta in reg.items():
                for feat in FEATURE_OUTPUTS[family]:
                    rows.append(
                        {
                            "feature_id": f"{tf}.{ps_id}.{feat}",
                            "family": family,
                            "timeframe": tf,
                            "parameter_set": ps_id,
                            "formula_version": meta["formula_version"],
                            "causal_semantics": meta["causal_semantics"],
                            "units": "price" if "MA" in feat or "DIST" in feat else "ratio_or_flag",
                            "warmup_bars": meta["warmup_bars"],
                            "source_engine": meta["source_engine"],
                            "reference_status": meta["reference_status"],
                        }
                    )
        for feat in FEATURE_OUTPUTS["GEOMETRY"]:
            rows.append(
                {
                    "feature_id": f"{tf}.GEOMETRY_ABC.{feat}",
                    "family": "GEOMETRY",
                    "timeframe": tf,
                    "parameter_set": "GEOMETRY_ABC_V1",
                    "formula_version": "ABC_COP_OP_XOP_V1",
                    "causal_semantics": "CONFIRMED_PIVOTS_ONLY",
                    "units": "price_or_ratio",
                    "warmup_bars": 3,
                    "source_engine": "MULTITF_FEATURE_BANK_V1",
                    "reference_status": "NUMERIC_REFERENCE_TESTED",
                }
            )
        for feat in FEATURE_OUTPUTS["DNO"]:
            rows.append(
                {
                    "feature_id": f"{tf}.DNO.{feat}",
                    "family": "DNO",
                    "timeframe": tf,
                    "parameter_set": "DNO_REF_N7_V1",
                    "formula_version": "DINAPOLI_DETRENDED_OSCILLATOR_REFERENCE_V1",
                    "causal_semantics": "CONTIGUOUS_SEGMENT_SMA",
                    "units": "price_or_ratio",
                    "warmup_bars": 7,
                    "source_engine": "OSCILLATOR_PREDICTOR_REFERENCE_V1",
                    "reference_status": "DINAPOLI_NONPROPRIETARY_REFERENCE",
                }
            )
        for feat in FEATURE_OUTPUTS["OSC_PREDICTOR"]:
            rows.append(
                {
                    "feature_id": f"{tf}.OSC_PREDICTOR.{feat}",
                    "family": "OSC_PREDICTOR",
                    "timeframe": tf,
                    "parameter_set": "OSC_PRED_PROJECT_DINAPOLI_V1",
                    "formula_version": "PROJECT_DINAPOLI_STYLE_OSCILLATOR_PREDICTOR_V1",
                    "causal_semantics": "PEAK_AVAILABLE_AT=i+K",
                    "units": "price_or_ratio_or_flag",
                    "warmup_bars": "period+peak_strength+samples",
                    "source_engine": "OSCILLATOR_PREDICTOR_REFERENCE_V1",
                    "reference_status": "PROJECT_RECONSTRUCTION",
                }
            )
    return rows
