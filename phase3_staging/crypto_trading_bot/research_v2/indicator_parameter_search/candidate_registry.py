"""Candidate registry — bank IDs + references + controlled DNO sweeps."""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Any

import pandas as pd

from crypto_trading_bot.research_v2.multitf_feature_bank.registries import (
    DMA_REGISTRY,
    MACD_REGISTRY,
    STOCHASTIC_REGISTRY,
)
from crypto_trading_bot.research_v2.oscillator_predictor.config import PredictorConfig

from .config import DNO_ONE_FACTOR_AXES, EVENT_PRIMITIVES, FROZEN_PREDICTOR_REFERENCE, SEARCH_TFS
from .version import STUDY_VERSION

MANDATORY_DMA_IDS = {
    "DMA_SMA_P3_SHIFT3_V1",
    "DMA_SMA_P7_SHIFT5_V1",
    "DMA_SMA_P25_SHIFT5_V1",
}
MANDATORY_STOCH_IDS = {
    "STOCH_K14_KS3_D3_SHIFT0_V1",
    "DINAPOLI_PREFERRED_STOCHASTIC_REFERENCE_V1",
}
MANDATORY_MACD_IDS = {
    "MACD_12_26_9_SHIFT0_V1",
    "DINAPOLI_MACD_REFERENCE_V1",
}

REGISTRY_COMPARE_FIELDS = (
    "candidate_id",
    "family",
    "formula_variant",
    "parameter_set_id",
    "parameters",
    "decision_tf",
    "direction",
    "event_primitive",
    "up_primitive",
    "down_primitive",
    "reference_status",
    "is_reference",
    "execution_route",
    "version",
    "comparison_scope",
)


def parse_registry_parameters(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return {}
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        parsed = ast.literal_eval(text)
        if not isinstance(parsed, dict):
            raise ValueError(f"parameters must deserialize to dict, got {type(parsed).__name__}")
        return parsed
    raise ValueError(f"unsupported parameters value type: {type(raw).__name__}")


def normalize_registry_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["parameters"] = parse_registry_parameters(row.get("parameters"))
    ref = row.get("is_reference")
    if isinstance(ref, str):
        out["is_reference"] = ref.strip().lower() in {"true", "1", "yes"}
    else:
        out["is_reference"] = bool(ref)
    return out


def load_frozen_registry(path: Path | str) -> list[dict[str, Any]]:
    df = pd.read_csv(path)
    return [normalize_registry_row(row) for row in df.to_dict(orient="records")]


def registry_deserialization_stats(rows: list[dict[str, Any]]) -> dict[str, int]:
    params_dict = sum(1 for r in rows if isinstance(r.get("parameters"), dict))
    params_str = sum(1 for r in rows if isinstance(r.get("parameters"), str))
    return {
        "FROZEN_REGISTRY_ROW_COUNT": len(rows),
        "FROZEN_REGISTRY_PARAMETERS_DICT_COUNT": params_dict,
        "FROZEN_REGISTRY_PARAMETERS_STRING_COUNT": params_str,
    }


def compare_registry_semantics(built: list[dict[str, Any]], frozen: list[dict[str, Any]]) -> tuple[int, list[str]]:
    built_by_id = {r["candidate_id"]: r for r in built}
    frozen_by_id = {r["candidate_id"]: r for r in frozen}
    mismatches: list[str] = []
    for cid in sorted(built_by_id):
        if cid not in frozen_by_id:
            mismatches.append(f"missing_in_frozen:{cid}")
            continue
        b = built_by_id[cid]
        f = frozen_by_id[cid]
        for field in REGISTRY_COMPARE_FIELDS:
            if b.get(field) != f.get(field):
                mismatches.append(f"{cid}:{field}")
    for cid in sorted(frozen_by_id):
        if cid not in built_by_id:
            mismatches.append(f"missing_in_built:{cid}")
    return len(mismatches), mismatches


def _cid(*parts: str) -> str:
    raw = "|".join(parts)
    if len(raw) <= 120:
        return raw
    return f"{raw[:80]}_{hashlib.sha1(raw.encode()).hexdigest()[:12]}"


def _row(
    *,
    candidate_id: str,
    family: str,
    formula_variant: str,
    parameter_set_id: str,
    parameters: dict[str, Any],
    decision_tf: str,
    direction: str,
    event_primitive: str,
    up_primitive: str,
    down_primitive: str,
    reference_status: str,
    is_reference: bool,
    execution_route: str = "",
) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "family": family,
        "formula_variant": formula_variant,
        "parameter_set_id": parameter_set_id,
        "parameters": parameters,
        "decision_tf": decision_tf,
        "direction": direction,
        "event_primitive": event_primitive,
        "up_primitive": up_primitive,
        "down_primitive": down_primitive,
        "reference_status": reference_status,
        "is_reference": is_reference,
        "execution_route": execution_route or formula_variant,
        "version": STUDY_VERSION,
        "comparison_scope": "SINGLE_FAMILY_SINGLE_PRIMITIVE",
    }


def _dma_candidates() -> list[dict[str, Any]]:
    rows = []
    for ps_id, meta in DMA_REGISTRY.items():
        for tf in SEARCH_TFS:
            for up, down in EVENT_PRIMITIVES["DMA"]:
                for direction, prim in (("UP", up), ("DOWN", down)):
                    cid = _cid("DMA", ps_id, up, down, tf, direction)
                    rows.append(
                        _row(
                            candidate_id=cid,
                            family="DMA",
                            formula_variant=meta.get("implementation_name", "DMA"),
                            parameter_set_id=ps_id,
                            parameters={
                                "ma_type": meta["ma_type"],
                                "period": meta["period"],
                                "display_shift": meta["display_shift"],
                            },
                            decision_tf=tf,
                            direction=direction,
                            event_primitive=prim,
                            up_primitive=up,
                            down_primitive=down,
                            reference_status=meta.get("reference_status", "PROJECT_RESEARCH"),
                            is_reference=ps_id in MANDATORY_DMA_IDS,
                        )
                    )
    return rows


def _stoch_candidates() -> list[dict[str, Any]]:
    rows = []
    for ps_id, meta in STOCHASTIC_REGISTRY.items():
        for tf in SEARCH_TFS:
            for up, down in EVENT_PRIMITIVES["STOCHASTIC"]:
                for direction, prim in (("UP", up), ("DOWN", down)):
                    cid = _cid("STOCH", ps_id, up, down, tf, direction)
                    rows.append(
                        _row(
                            candidate_id=cid,
                            family="STOCHASTIC",
                            formula_variant=meta.get("implementation_name", "STOCHASTIC"),
                            parameter_set_id=ps_id,
                            parameters={k: meta[k] for k in meta if k not in ("feature_set_id", "family", "warmup_bars")},
                            decision_tf=tf,
                            direction=direction,
                            event_primitive=prim,
                            up_primitive=up,
                            down_primitive=down,
                            reference_status=meta.get("reference_status", "PROJECT_RESEARCH"),
                            is_reference=ps_id in MANDATORY_STOCH_IDS,
                        )
                    )
    return rows


def _macd_candidates() -> list[dict[str, Any]]:
    rows = []
    for ps_id, meta in MACD_REGISTRY.items():
        for tf in SEARCH_TFS:
            for up, down in EVENT_PRIMITIVES["MACD"]:
                for direction, prim in (("UP", up), ("DOWN", down)):
                    cid = _cid("MACD", ps_id, up, down, tf, direction)
                    rows.append(
                        _row(
                            candidate_id=cid,
                            family="MACD",
                            formula_variant=meta.get("implementation_name", "MACD"),
                            parameter_set_id=ps_id,
                            parameters={k: meta[k] for k in meta if k not in ("feature_set_id", "family", "warmup_bars")},
                            decision_tf=tf,
                            direction=direction,
                            event_primitive=prim,
                            up_primitive=up,
                            down_primitive=down,
                            reference_status=meta.get("reference_status", "PROJECT_RESEARCH"),
                            is_reference=ps_id in MANDATORY_MACD_IDS,
                        )
                    )
    return rows


def _predictor_config_dict(cfg) -> dict[str, Any]:
    return {
        "period": cfg.period,
        "peak_strength": cfg.peak_strength,
        "lookback": cfg.lookback,
        "samples": cfg.samples,
        "ob_os_level_percent": cfg.ob_os_level_percent,
    }


def _pure_dno_candidates() -> list[dict[str, Any]]:
    """Pure DNO reference — DNO[t]=Close-SMA7, zero-cross primitives only."""
    rows: list[dict[str, Any]] = []
    params = {"period": 7, "formula": "DNO_CLOSE_MINUS_SMA", "authority": "OSCILLATOR_PREDICTOR_REFERENCE_V1"}
    for tf in SEARCH_TFS:
        for up, down in EVENT_PRIMITIVES["DNO"]:
            for direction, prim in (("UP", up), ("DOWN", down)):
                cid = _cid("PURE_DNO", "DNO_PERIOD_7_REFERENCE", prim, tf, direction)
                rows.append(
                    _row(
                        candidate_id=cid,
                        family="PURE_DNO",
                        formula_variant="DNO_PERIOD_7_REFERENCE",
                        parameter_set_id="DNO_PERIOD_7_REFERENCE",
                        parameters=params,
                        decision_tf=tf,
                        direction=direction,
                        event_primitive=prim,
                        up_primitive=up,
                        down_primitive=down,
                        reference_status="DINAPOLI_NONPROPRIETARY_REFERENCE",
                        is_reference=True,
                        execution_route="compute_dno_feature_series",
                    )
                )
    return rows


def _dno_quantile_candidates() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    params = {"control": "quantile_80_20", "period": 7, "lookback": 100}
    label = "CAUSAL_DNO_QUANTILE_80_20_CONTROL_V1"
    for tf in SEARCH_TFS:
        for up, down in EVENT_PRIMITIVES["OSC_PREDICTOR"]:
            for direction, prim in (("UP", up), ("DOWN", down)):
                cid = _cid("DNO_QUANTILE", label, prim, tf, direction)
                rows.append(
                    _row(
                        candidate_id=cid,
                        family="DNO_QUANTILE",
                        formula_variant=label,
                        parameter_set_id=label,
                        parameters=params,
                        decision_tf=tf,
                        direction=direction,
                        event_primitive=prim,
                        up_primitive=up,
                        down_primitive=down,
                        reference_status="REFERENCE",
                        is_reference=True,
                        execution_route="precompute_control_forecast_bands",
                    )
                )
    return rows


def _osc_predictor_candidates() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    ref = FROZEN_PREDICTOR_REFERENCE
    configs: list[tuple[str, PredictorConfig, dict]] = [
        ("PROJECT_DINAPOLI_STYLE_OSCILLATOR_PREDICTOR_REFERENCE", ref, _predictor_config_dict(ref)),
    ]
    for axis, values in DNO_ONE_FACTOR_AXES.items():
        for v in values:
            if axis == "period" and v == ref.period:
                continue
            if axis == "peak_strength" and v == ref.peak_strength:
                continue
            if axis == "lookback" and v == ref.lookback:
                continue
            if axis == "samples" and v == ref.samples:
                continue
            if axis == "ob_os_level_percent" and v == ref.ob_os_level_percent:
                continue
            p = PredictorConfig(
                period=v if axis == "period" else ref.period,
                peak_strength=v if axis == "peak_strength" else ref.peak_strength,
                lookback=v if axis == "lookback" else ref.lookback,
                samples=v if axis == "samples" else ref.samples,
                ob_os_level_percent=v if axis == "ob_os_level_percent" else ref.ob_os_level_percent,
            )
            label = f"OSC_PRED_SWEEP_{axis.upper()}_{v}"
            configs.append((label, p, {"sweep_axis": axis, "sweep_value": v, **_predictor_config_dict(p)}))

    for label, _cfg, params in configs:
        for tf in SEARCH_TFS:
            for up, down in EVENT_PRIMITIVES["OSC_PREDICTOR"]:
                for direction, prim in (("UP", up), ("DOWN", down)):
                    cid = _cid("OSC_PREDICTOR", label, prim, tf, direction)
                    rows.append(
                        _row(
                            candidate_id=cid,
                            family="OSC_PREDICTOR",
                            formula_variant=label,
                            parameter_set_id=label,
                            parameters=params,
                            decision_tf=tf,
                            direction=direction,
                            event_primitive=prim,
                            up_primitive=up,
                            down_primitive=down,
                            reference_status="REFERENCE" if "REFERENCE" in label else "SWEEP",
                            is_reference=bool("REFERENCE" in label),
                            execution_route="compute_predictor_feature_series",
                        )
                    )
    return rows


INVERSE_EXECUTION_MAP: list[dict[str, str]] = [
    {
        "indicator_family": "DMA",
        "indicator_parameter_set_id": "DMA_SMA_P3_SHIFT3_V1",
        "up_parameter_set_id": "PRED_DMA_3X3_CROSS_UP_V1",
        "down_parameter_set_id": "PRED_DMA_3X3_CROSS_DOWN_V1",
        "formula_variant": "INVERSE_DMA_3X3",
    },
    {
        "indicator_family": "DMA",
        "indicator_parameter_set_id": "DMA_SMA_P7_SHIFT5_V1",
        "up_parameter_set_id": "PRED_DMA_7X5_CROSS_UP_V1",
        "down_parameter_set_id": "PRED_DMA_7X5_CROSS_DOWN_V1",
        "formula_variant": "INVERSE_DMA_7X5",
    },
    {
        "indicator_family": "DMA",
        "indicator_parameter_set_id": "DMA_SMA_P25_SHIFT5_V1",
        "up_parameter_set_id": "PRED_DMA_25X5_CROSS_UP_V1",
        "down_parameter_set_id": "PRED_DMA_25X5_CROSS_DOWN_V1",
        "formula_variant": "INVERSE_DMA_25X5",
    },
    {
        "indicator_family": "STOCHASTIC",
        "indicator_parameter_set_id": "STOCH_K14_KS3_D3_SHIFT0_V1",
        "up_parameter_set_id": "PRED_STOCH_14_K_20_POINT_V1",
        "down_parameter_set_id": "PRED_STOCH_14_K_80_POINT_V1",
        "formula_variant": "INVERSE_STOCH_14_3_3_POINT_BAR",
        "stoch_meaning": "UP uses OS-side K=20 point-bar threshold; DOWN uses OB-side K=80 point-bar threshold",
    },
    {
        "indicator_family": "MACD",
        "indicator_parameter_set_id": "MACD_12_26_9_SHIFT0_V1",
        "up_parameter_set_id": "PRED_MACD_12_26_9_SIGNAL_CROSS_UP_V1",
        "down_parameter_set_id": "PRED_MACD_12_26_9_SIGNAL_CROSS_DOWN_V1",
        "formula_variant": "INVERSE_MACD_12_26_9_SIGNAL_CROSS",
    },
    {
        "indicator_family": "PURE_DNO",
        "indicator_parameter_set_id": "DNO_PERIOD_7_REFERENCE",
        "up_parameter_set_id": "PRED_DNO_OS_V1",
        "down_parameter_set_id": "PRED_DNO_OB_V1",
        "formula_variant": "INVERSE_DNO_N7_OB_OS",
        "dno_meaning": "UP reversal uses OS-side DNO inverse (PRED_DNO_OS_V1); DOWN uses OB-side (PRED_DNO_OB_V1)",
    },
]


def _inverse_candidates() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in INVERSE_EXECUTION_MAP:
        for tf in SEARCH_TFS:
            for direction in ("UP", "DOWN"):
                pred_id = spec["up_parameter_set_id"] if direction == "UP" else spec["down_parameter_set_id"]
                cid = _cid("INVERSE", spec["formula_variant"], spec["indicator_parameter_set_id"], tf, direction)
                rows.append(
                    _row(
                        candidate_id=cid,
                        family="INVERSE_PREDICTOR",
                        formula_variant=spec["formula_variant"],
                        parameter_set_id=spec["indicator_parameter_set_id"],
                        parameters={
                            "inverse_parameter_set_id": pred_id,
                            "indicator_parameter_set_id": spec["indicator_parameter_set_id"],
                        },
                        decision_tf=tf,
                        direction=direction,
                        event_primitive="INVERSE_THRESHOLD_CROSS",
                        up_primitive="INVERSE_UP",
                        down_primitive="INVERSE_DOWN",
                        reference_status="SUPPORTED_ANALYTICALLY",
                        is_reference=True,
                        execution_route=pred_id,
                    )
                )
    return rows


def build_candidate_registry() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rows.extend(_dma_candidates())
    rows.extend(_stoch_candidates())
    rows.extend(_macd_candidates())
    rows.extend(_pure_dno_candidates())
    rows.extend(_dno_quantile_candidates())
    rows.extend(_osc_predictor_candidates())
    rows.extend(_inverse_candidates())
    return rows


def registry_family_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "DMA_CANDIDATES": sum(1 for r in rows if r["family"] == "DMA"),
        "STOCH_CANDIDATES": sum(1 for r in rows if r["family"] == "STOCHASTIC"),
        "MACD_CANDIDATES": sum(1 for r in rows if r["family"] == "MACD"),
        "PURE_DNO_CANDIDATES": sum(1 for r in rows if r["family"] == "PURE_DNO"),
        "DNO_QUANTILE_CANDIDATES": sum(1 for r in rows if r["family"] == "DNO_QUANTILE"),
        "OSC_PREDICTOR_CANDIDATES": sum(1 for r in rows if r["family"] == "OSC_PREDICTOR"),
        "INVERSE_PREDICTOR_CANDIDATES": sum(1 for r in rows if r["family"] == "INVERSE_PREDICTOR"),
    }


def audit_registry_semantic_consistency(rows: list[dict[str, Any]]) -> dict[str, Any]:
    dno_zero = [r for r in rows if r["event_primitive"] in ("DNO_ZERO_CROSS_UP", "DNO_ZERO_CROSS_DOWN")]
    bad_dno = [
        r
        for r in rows
        if r.get("parameters", {}).get("family") == "DNO_ONLY"
        and r["event_primitive"] in EVENT_PRIMITIVES["OSC_PREDICTOR"]
    ]
    bad_pure = [
        r
        for r in rows
        if r["family"] == "PURE_DNO"
        and r["event_primitive"] not in ("DNO_ZERO_CROSS_UP", "DNO_ZERO_CROSS_DOWN")
    ]
    return {
        "DNO_ZERO_CROSS_CANDIDATE_COUNT": len(dno_zero),
        "DNO_ONLY_OSC_PRIMITIVE_COUNT": len(bad_dno),
        "PURE_DNO_NON_ZERO_PRIMITIVE_COUNT": len(bad_pure),
        "SEARCH_SPEC_REGISTRY_SEMANTIC_CONSISTENCY": "PASS"
        if dno_zero and not bad_dno and not bad_pure
        else "FAIL",
    }


def registry_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    fams = {}
    for r in rows:
        fams[r["family"]] = fams.get(r["family"], 0) + 1
    return fams
