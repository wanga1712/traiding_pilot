"""Signal generation via feature bank + oscillator predictor."""
from __future__ import annotations

import json
from typing import Any

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.bars import bars_to_arrays, parse_ts
from crypto_trading_bot.research_v2.indicator_engine.volatility import compute_atr_series
from crypto_trading_bot.research_v2.multitf_feature_bank.macd_features import compute_macd_feature_series
from crypto_trading_bot.research_v2.multitf_feature_bank.ma_features import compute_dma_feature_series
from crypto_trading_bot.research_v2.multitf_feature_bank.registries import (
    DMA_REGISTRY,
    MACD_REGISTRY,
    STOCHASTIC_REGISTRY,
)
from crypto_trading_bot.research_v2.multitf_feature_bank.stoch_features import compute_stoch_feature_series
from crypto_trading_bot.research_v2.oscillator_predictor.config import PredictorConfig
from crypto_trading_bot.research_v2.oscillator_predictor.dynamic_predictor import compute_predictor_feature_series
from crypto_trading_bot.research_v2.reversal_signal_study.signals import (
    _emit,
    generate_price_baseline_signals,
)

from .candidate_registry import parse_registry_parameters
from .config import FROZEN_PREDICTOR_REFERENCE
from .data_isolation import in_scan_window


def row_parameters(row: dict[str, Any]) -> dict[str, Any]:
    return parse_registry_parameters(row.get("parameters"))


def is_quantile_control_row(row: dict[str, Any]) -> bool:
    return row_parameters(row).get("control") == "quantile_80_20"


def resolve_candidate_route(row: dict[str, Any]) -> str:
    family = row["family"]
    ps_id = row["parameter_set_id"]
    params = row_parameters(row)
    if family == "DMA":
        return "DMA" if ps_id in DMA_REGISTRY else "UNRESOLVED"
    if family == "STOCHASTIC":
        return "STOCHASTIC" if ps_id in STOCHASTIC_REGISTRY or ps_id == "DINAPOLI_PREFERRED_STOCHASTIC_REFERENCE_V1" else "UNRESOLVED"
    if family == "MACD":
        return "MACD" if ps_id in MACD_REGISTRY or ps_id == "DINAPOLI_MACD_REFERENCE_V1" else "UNRESOLVED"
    if family in ("OSC_PREDICTOR", "DNO_PREDICTOR"):
        if is_quantile_control_row(row):
            return "DNO_QUANTILE_CONTROL"
        if _predictor_config_from_row(row) is not None:
            return "PREDICTOR"
        return "UNRESOLVED"
    if family == "INVERSE_PREDICTOR":
        return "INVERSE" if params.get("inverse_route") else "UNRESOLVED"
    return "UNRESOLVED"


def _scan_primitive_series(
    bars: list[dict[str, Any]],
    samples: list[Any],
    *,
    candidate_id: str,
    primitive: str,
    direction: str,
    decision_tf: str,
    scan_start_iso: str | None,
    scan_end_iso: str | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    scan_start = parse_ts(scan_start_iso) if scan_start_iso else None
    scan_end = parse_ts(scan_end_iso) if scan_end_iso else None
    for i, sample in enumerate(samples):
        if not sample.valid:
            continue
        ct = parse_ts(bars[i]["close_time"])
        if not in_scan_window(ct, scan_start=scan_start, scan_end=scan_end):
            continue
        prim = sample.signal_primitives
        if not prim.get(primitive):
            continue
        _emit(
            rows,
            candidate_id=candidate_id,
            signal_time=bars[i]["close_time"],
            signal_price=float(bars[i]["close"]),
            direction=direction,
            decision_tf=decision_tf,
            calculated_at=bars[i]["close_time"],
            available_at=bars[i]["close_time"],
        )
    return rows


def _feature_cache_key(row: dict[str, Any]) -> tuple:
    params = row_parameters(row)
    return (row["decision_tf"], row["family"], row["parameter_set_id"], json.dumps(params, sort_keys=True, default=str))


def _load_feature_samples(
    bars: list[dict[str, Any]],
    row: dict[str, Any],
    *,
    sample_cache: dict[tuple, Any] | None,
) -> Any:
    key = _feature_cache_key(row)
    if sample_cache is not None and key in sample_cache:
        return sample_cache[key]

    family = row["family"]
    ps_id = row["parameter_set_id"]
    tf = row["decision_tf"]
    payload: Any = None

    if family == "DMA" and ps_id in DMA_REGISTRY:
        meta = DMA_REGISTRY[ps_id]
        arrays = bars_to_arrays(bars, timeframe=tf)
        atr = np.array(
            [float(s.values["atr"]) if s.valid and s.values.get("atr") is not None else np.nan for s in compute_atr_series(arrays, period=14)],
            dtype=float,
        )
        payload = ("dma", compute_dma_feature_series(
            arrays, ma_type=meta["ma_type"], period=meta["period"], display_shift=meta["display_shift"], atr=atr
        ))
    elif family == "STOCHASTIC" and ps_id in STOCHASTIC_REGISTRY:
        meta = STOCHASTIC_REGISTRY[ps_id]
        arrays = bars_to_arrays(bars, timeframe=tf)
        payload = ("stoch", compute_stoch_feature_series(
            arrays,
            k_period=meta["k_period"],
            k_smooth=meta.get("k_smooth", meta.get("slowing", 3)),
            d_period=meta["d_period"],
            display_shift=meta.get("display_shift", 0),
            formula_version=meta.get("formula_version", "STOCH_CANONICAL_V1"),
            overbought=meta.get("overbought", 80.0),
            oversold=meta.get("oversold", 20.0),
        ))
    elif family == "MACD" and ps_id in MACD_REGISTRY:
        meta = MACD_REGISTRY[ps_id]
        arrays = bars_to_arrays(bars, timeframe=tf)
        if meta.get("formula_version") == "DINAPOLI_MACD_REFERENCE_V1":
            payload = (
                "macd",
                compute_macd_feature_series(
                    arrays,
                    display_shift=meta.get("display_shift", 0),
                    formula_version="DINAPOLI_MACD_REFERENCE_V1",
                ),
            )
        else:
            payload = ("macd", compute_macd_feature_series(
                arrays,
                fast=meta["fast"],
                slow=meta["slow"],
                signal=meta["signal"],
                display_shift=meta.get("display_shift", 0),
                formula_version=meta.get("formula_version", "MACD_CANONICAL_V1"),
            ))
    elif family in ("OSC_PREDICTOR", "DNO_PREDICTOR"):
        if is_quantile_control_row(row):
            arrays = bars_to_arrays(bars, timeframe=tf)
            payload = ("quantile_control", arrays)
        else:
            arrays = bars_to_arrays(bars, timeframe=tf)
            atr = np.array(
                [float(s.values["atr"]) if s.valid and s.values.get("atr") is not None else np.nan for s in compute_atr_series(arrays, period=14)],
                dtype=float,
            )
            cfg = _predictor_config_from_row(row)
            payload = ("predictor", compute_predictor_feature_series(arrays, config=cfg, atr=atr) if cfg else None)

    if sample_cache is not None and payload is not None:
        sample_cache[key] = payload
    return payload


def generate_bank_family_signals(
    bars: list[dict[str, Any]],
    row: dict[str, Any],
    *,
    scan_start_iso: str | None = None,
    scan_end_iso: str | None = None,
    sample_cache: dict[tuple, Any] | None = None,
) -> list[dict[str, Any]]:
    family = row["family"]
    ps_id = row["parameter_set_id"]
    tf = row["decision_tf"]
    prim = row["event_primitive"]
    direction = row["direction"]
    cid = row["candidate_id"]

    payload = _load_feature_samples(bars, row, sample_cache=sample_cache)
    if payload is None:
        return []

    kind = payload[0]
    if kind == "engine":
        return _scan_from_indicator_samples(payload[1], bars, row, scan_start_iso, scan_end_iso)
    if kind == "predictor":
        preds = payload[1]
        if preds is None:
            return []
        arrays = bars_to_arrays(bars, timeframe=row["decision_tf"])
        return _scan_predictor_payload(bars, row, arrays, preds, scan_start_iso=scan_start_iso, scan_end_iso=scan_end_iso)
    if kind == "quantile_control":
        return _generate_quantile_control_signals(
            bars,
            row,
            arrays=payload[1],
            scan_start_iso=scan_start_iso,
            scan_end_iso=scan_end_iso,
        )
    samples = payload[1]
    return _scan_primitive_series(
        bars,
        samples,
        candidate_id=cid,
        primitive=prim,
        direction=direction,
        decision_tf=tf,
        scan_start_iso=scan_start_iso,
        scan_end_iso=scan_end_iso,
    )


def _scan_from_indicator_samples(samples, bars, row, scan_start_iso, scan_end_iso=None):
    """Fallback for DiNapoli reference engine routes."""
    rows = []
    scan_start = parse_ts(scan_start_iso) if scan_start_iso else None
    scan_end = parse_ts(scan_end_iso) if scan_end_iso else None
    up, down = row["up_primitive"], row["down_primitive"]
    prim = row["event_primitive"]
    for i, sample in enumerate(samples):
        if not sample.valid:
            continue
        ct = parse_ts(bars[i]["close_time"])
        if not in_scan_window(ct, scan_start=scan_start, scan_end=scan_end):
            continue
        flag = None
        if prim == up and sample.signal_primitives.get(up):
            flag = row["direction"]
        elif prim == down and sample.signal_primitives.get(down):
            flag = row["direction"]
        if flag:
            _emit(
                rows,
                candidate_id=row["candidate_id"],
                signal_time=bars[i]["close_time"],
                signal_price=float(bars[i]["close"]),
                direction=flag,
                decision_tf=row["decision_tf"],
                calculated_at=bars[i]["close_time"],
                available_at=bars[i]["close_time"],
            )
    return rows


def _predictor_config_from_row(row: dict[str, Any]) -> PredictorConfig | None:
    p = row_parameters(row)
    if p.get("control") == "quantile_80_20":
        return None
    ref = FROZEN_PREDICTOR_REFERENCE
    if "period" in p or p.get("family") == "DNO_ONLY":
        return PredictorConfig(
            period=int(p.get("period", ref.period)),
            peak_strength=int(p.get("peak_strength", ref.peak_strength)),
            lookback=int(p.get("lookback", ref.lookback)),
            samples=int(p.get("samples", ref.samples)),
            ob_os_level_percent=float(p.get("ob_os_level_percent", ref.ob_os_level_percent)),
        )
    if "sweep_axis" in p:
        return PredictorConfig(
            period=int(p.get("period", ref.period)),
            peak_strength=int(p.get("peak_strength", ref.peak_strength)),
            lookback=int(p.get("lookback", ref.lookback)),
            samples=int(p.get("samples", ref.samples)),
            ob_os_level_percent=float(p.get("ob_os_level_percent", ref.ob_os_level_percent)),
        )
    return ref


def _generate_quantile_control_signals(
    bars: list[dict[str, Any]],
    row: dict[str, Any],
    *,
    arrays,
    scan_start_iso: str | None,
    scan_end_iso: str | None = None,
) -> list[dict[str, Any]]:
    """Causal DNO 80/20 quantile control — authority from OSCILLATOR-PREDICTOR-HISTORICAL-EVENT-STUDY-1."""
    from crypto_trading_bot.research_v2.oscillator_predictor_event_study.methodology_v2 import (
        precompute_control_forecast_bands,
    )
    from crypto_trading_bot.research_v2.oscillator_predictor_event_study.study_engine import (
        ScanContext,
        precompute_tf_series,
    )

    tf = row["decision_tf"]
    cfg = FROZEN_PREDICTOR_REFERENCE
    _, atr, dno, preds, seg_starts = precompute_tf_series(bars, timeframe=tf, config=cfg)
    n = len(bars)
    scan_indices = list(range(n))
    ctx = ScanContext(
        timeframe=tf,
        split="DISCOVERY",
        bars=bars,
        scan_indices=scan_indices,
        arrays=arrays,
        atr=atr,
        dno=dno,
        preds=preds,
        effective_first=parse_ts(bars[0]["close_time"]),
        effective_last=parse_ts(bars[-1]["close_time"]),
        seg_starts=seg_starts,
    )
    q_ob, q_os, _, _ = precompute_control_forecast_bands(ctx, decision_indices=scan_indices)
    scan_start = parse_ts(scan_start_iso) if scan_start_iso else None
    scan_end = parse_ts(scan_end_iso) if scan_end_iso else None
    prim = row["event_primitive"]
    rows: list[dict[str, Any]] = []
    for e in range(1, n):
        ct = parse_ts(bars[e]["close_time"])
        if not in_scan_window(ct, scan_start=scan_start, scan_end=scan_end):
            continue
        pp = float(arrays.close[e - 1])
        cp = float(arrays.close[e])
        fire = False
        if prim == "FORECAST_OB_CROSS" and row["direction"] == "UP":
            band = q_ob[e - 1]
            fire = np.isfinite(band) and pp <= float(band) and cp > float(band)
        elif prim == "FORECAST_OS_CROSS" and row["direction"] == "DOWN":
            band = q_os[e - 1]
            fire = np.isfinite(band) and pp >= float(band) and cp < float(band)
        elif prim == "CROSSED_OB_BAND_UP" and row["direction"] == "UP":
            fire = (
                np.isfinite(q_ob[e - 1])
                and np.isfinite(q_ob[e])
                and pp <= float(q_ob[e - 1])
                and cp > float(q_ob[e])
            )
        elif prim == "CROSSED_OS_BAND_DOWN" and row["direction"] == "DOWN":
            fire = (
                np.isfinite(q_os[e - 1])
                and np.isfinite(q_os[e])
                and pp >= float(q_os[e - 1])
                and cp < float(q_os[e])
            )
        if fire:
            _emit(
                rows,
                candidate_id=row["candidate_id"],
                signal_time=bars[e]["close_time"],
                signal_price=cp,
                direction=row["direction"],
                decision_tf=tf,
                calculated_at=bars[e]["close_time"],
                available_at=bars[e]["close_time"],
            )
    return rows


def _scan_predictor_payload(
    bars: list[dict[str, Any]],
    row: dict[str, Any],
    arrays,
    preds: list[dict[str, Any]],
    *,
    scan_start_iso: str | None,
    scan_end_iso: str | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    scan_start = parse_ts(scan_start_iso) if scan_start_iso else None
    scan_end = parse_ts(scan_end_iso) if scan_end_iso else None
    prim = row["event_primitive"]
    tf = row["decision_tf"]
    for i, pred in enumerate(preds):
        if not pred.get("valid"):
            continue
        ct = parse_ts(bars[i]["close_time"])
        if not in_scan_window(ct, scan_start=scan_start, scan_end=scan_end):
            continue
        fire = False
        if prim == "CROSSED_OB_BAND_UP" and row["direction"] == "UP":
            fire = bool(pred.get("CROSSED_OB_BAND_UP"))
        elif prim == "CROSSED_OS_BAND_DOWN" and row["direction"] == "DOWN":
            fire = bool(pred.get("CROSSED_OS_BAND_DOWN"))
        elif prim == "FORECAST_OB_CROSS" and row["direction"] == "UP" and i >= 1:
            f_ob = preds[i - 1].get("PREDICTOR_OB_PRICE_NEXT_BAR")
            if f_ob is not None:
                pp = float(arrays.close[i - 1])
                cp = float(arrays.close[i])
                fire = pp <= float(f_ob) and cp > float(f_ob)
        elif prim == "FORECAST_OS_CROSS" and row["direction"] == "DOWN" and i >= 1:
            f_os = preds[i - 1].get("PREDICTOR_OS_PRICE_NEXT_BAR")
            if f_os is not None:
                pp = float(arrays.close[i - 1])
                cp = float(arrays.close[i])
                fire = pp >= float(f_os) and cp < float(f_os)
        if fire:
            _emit(
                rows,
                candidate_id=row["candidate_id"],
                signal_time=bars[i]["close_time"],
                signal_price=float(bars[i]["close"]),
                direction=row["direction"],
                decision_tf=tf,
                calculated_at=bars[i]["close_time"],
                available_at=bars[i]["close_time"],
            )
    return rows


def _generate_predictor_signals(
    bars: list[dict[str, Any]],
    row: dict[str, Any],
    *,
    scan_start_iso: str | None,
) -> list[dict[str, Any]]:
    tf = row["decision_tf"]
    arrays = bars_to_arrays(bars, timeframe=tf)
    atr = np.array(
        [float(s.values["atr"]) if s.valid and s.values.get("atr") is not None else np.nan for s in compute_atr_series(arrays, period=14)],
        dtype=float,
    )
    cfg = _predictor_config_from_row(row)
    if cfg is None:
        return []  # quantile control handled separately if needed
    preds = compute_predictor_feature_series(arrays, config=cfg, atr=atr)
    rows: list[dict[str, Any]] = []
    scan_start = parse_ts(scan_start_iso) if scan_start_iso else None
    prim = row["event_primitive"]
    for i, pred in enumerate(preds):
        if not pred.get("valid"):
            continue
        ct = parse_ts(bars[i]["close_time"])
        if scan_start and ct < scan_start:
            continue
        fire = False
        if prim == "CROSSED_OB_BAND_UP" and row["direction"] == "UP":
            fire = bool(pred.get("CROSSED_OB_BAND_UP"))
        elif prim == "CROSSED_OS_BAND_DOWN" and row["direction"] == "DOWN":
            fire = bool(pred.get("CROSSED_OS_BAND_DOWN"))
        elif prim == "FORECAST_OB_CROSS" and row["direction"] == "UP" and i >= 1:
            f_ob = preds[i - 1].get("PREDICTOR_OB_PRICE_NEXT_BAR")
            if f_ob is not None:
                pp = float(arrays.close[i - 1])
                cp = float(arrays.close[i])
                fire = pp <= float(f_ob) and cp > float(f_ob)
        elif prim == "FORECAST_OS_CROSS" and row["direction"] == "DOWN" and i >= 1:
            f_os = preds[i - 1].get("PREDICTOR_OS_PRICE_NEXT_BAR")
            if f_os is not None:
                pp = float(arrays.close[i - 1])
                cp = float(arrays.close[i])
                fire = pp >= float(f_os) and cp < float(f_os)
        if fire:
            _emit(
                rows,
                candidate_id=row["candidate_id"],
                signal_time=bars[i]["close_time"],
                signal_price=float(bars[i]["close"]),
                direction=row["direction"],
                decision_tf=tf,
                calculated_at=bars[i]["close_time"],
                available_at=bars[i]["close_time"],
            )
    return rows


def generate_signals_for_row(
    bars: list[dict[str, Any]],
    row: dict[str, Any],
    *,
    scan_start_iso: str | None = None,
    scan_end_iso: str | None = None,
    sample_cache: dict[tuple, Any] | None = None,
) -> list[dict[str, Any]]:
    if row["family"] == "INVERSE_PREDICTOR":
        from crypto_trading_bot.research_v2.reversal_signal_study.signals import generate_predictor_trigger_signals

        up_id = row_parameters(row).get("inverse_route", "INVERSE_UP")
        return generate_predictor_trigger_signals(
            bars,
            candidate_id=row["candidate_id"],
            up_param=up_id,
            down_param=up_id,
            decision_tf=row["decision_tf"],
            scan_start_iso=scan_start_iso,
            scan_end_iso=scan_end_iso,
        )
    return generate_bank_family_signals(
        bars,
        row,
        scan_start_iso=scan_start_iso,
        scan_end_iso=scan_end_iso,
        sample_cache=sample_cache,
    )


def generate_frozen_price_baselines(
    bars: list[dict[str, Any]],
    *,
    decision_tf: str,
    scan_start_iso: str | None,
    scan_end_iso: str | None = None,
) -> list[dict[str, Any]]:
    kinds = [
        "ONE_BAR_DIRECTION_CHANGE",
        "CLOSE_ABOVE_PREVIOUS_HIGH",
        "N3_BAR_EXTREME_BREAK",
        "N5_BAR_EXTREME_BREAK",
        "SHORT_TERM_SLOPE_SIGN_CHANGE",
    ]
    out: list[dict[str, Any]] = []
    for kind in kinds:
        cid = f"PRICE_{kind}_{decision_tf}"
        out.extend(
            generate_price_baseline_signals(
                bars,
                candidate_id=cid,
                kind=kind,
                decision_tf=decision_tf,
                scan_start_iso=scan_start_iso,
                scan_end_iso=scan_end_iso,
            )
        )
    return out
