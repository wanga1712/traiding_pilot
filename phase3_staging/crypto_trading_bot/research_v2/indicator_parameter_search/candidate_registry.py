"""Candidate registry — bank IDs + references + controlled DNO sweeps."""
from __future__ import annotations

import hashlib
from typing import Any

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


def _dno_predictor_candidates() -> list[dict[str, Any]]:
    rows = []
    ref = FROZEN_PREDICTOR_REFERENCE
    configs: list[tuple[str, Any, dict]] = [
        ("PROJECT_DINAPOLI_STYLE_OSCILLATOR_PREDICTOR_REFERENCE", ref, _predictor_config_dict(ref)),
        ("CAUSAL_DNO_QUANTILE_80_20_CONTROL_V1", None, {"control": "quantile_80_20"}),
        ("DNO_PERIOD_7_REFERENCE", ref, {"period": 7, "family": "DNO_ONLY"}),
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

    for label, cfg, params in configs:
        family = "DNO_PREDICTOR" if "QUANTILE" not in label and "DNO_PERIOD" in label else (
            "DNO_PREDICTOR" if cfg is None else "OSC_PREDICTOR"
        )
        if "QUANTILE" in label:
            family = "DNO_PREDICTOR"
        for tf in SEARCH_TFS:
            for up, down in EVENT_PRIMITIVES["OSC_PREDICTOR"]:
                for direction, prim in (("UP", up), ("DOWN", down)):
                    cid = _cid(family, label, prim, tf, direction)
                    rows.append(
                        _row(
                            candidate_id=cid,
                            family=family,
                            formula_variant=label,
                            parameter_set_id=label,
                            parameters=params,
                            decision_tf=tf,
                            direction=direction,
                            event_primitive=prim,
                            up_primitive=up,
                            down_primitive=down,
                            reference_status="REFERENCE" if "REFERENCE" in label or "QUANTILE" in label else "SWEEP",
                            is_reference="REFERENCE" in label or "QUANTILE" in label or "DNO_PERIOD" in label,
                        )
                    )
    return rows


def _inverse_candidates() -> list[dict[str, Any]]:
    """Executable inverse routes only — from INVERSE_PREDICTOR_FAMILY_STATUS."""
    supported = [
        ("DMA", "DMA_SMA_P3_SHIFT3_V1", "DMA_PRICE_CROSS_PREDICTOR"),
        ("DMA", "DMA_SMA_P7_SHIFT5_V1", "DMA_PRICE_CROSS_PREDICTOR"),
        ("DMA", "DMA_SMA_P25_SHIFT5_V1", "DMA_PRICE_CROSS_PREDICTOR"),
        ("STOCHASTIC", "STOCH_K14_KS3_D3_SHIFT0_V1", "STANDARD_STOCH_THRESHOLD_PREDICTOR"),
        ("MACD", "MACD_12_26_9_SHIFT0_V1", "STANDARD_MACD_CROSS_PREDICTOR"),
        ("DNO_PREDICTOR", "DNO_REF_N7_V1", "DNO_OB_OS_PREDICTOR"),
    ]
    rows = []
    for tf in SEARCH_TFS:
        for family, ps_id, route in supported:
            for direction in ("UP", "DOWN"):
                cid = _cid("INVERSE", route, ps_id, tf, direction)
                rows.append(
                    _row(
                        candidate_id=cid,
                        family="INVERSE_PREDICTOR",
                        formula_variant=route,
                        parameter_set_id=ps_id,
                        parameters={"inverse_route": route},
                        decision_tf=tf,
                        direction=direction,
                        event_primitive="INVERSE_THRESHOLD_CROSS",
                        up_primitive="INVERSE_UP",
                        down_primitive="INVERSE_DOWN",
                        reference_status="SUPPORTED_ANALYTICALLY",
                        is_reference=True,
                    )
                )
    return rows


def build_candidate_registry() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rows.extend(_dma_candidates())
    rows.extend(_stoch_candidates())
    rows.extend(_macd_candidates())
    rows.extend(_dno_predictor_candidates())
    rows.extend(_inverse_candidates())
    return rows


def registry_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    fams = {}
    for r in rows:
        fams[r["family"]] = fams.get(r["family"], 0) + 1
    return fams
