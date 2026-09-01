"""Signal generation via feature bank + oscillator predictor."""
from __future__ import annotations

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

from .config import FROZEN_PREDICTOR_REFERENCE


def _scan_primitive_series(
    bars: list[dict[str, Any]],
    samples: list[Any],
    *,
    candidate_id: str,
    primitive: str,
    direction: str,
    decision_tf: str,
    scan_start_iso: str | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    scan_start = parse_ts(scan_start_iso) if scan_start_iso else None
    for i, sample in enumerate(samples):
        if not sample.valid:
            continue
        ct = parse_ts(bars[i]["close_time"])
        if scan_start and ct < scan_start:
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


def generate_bank_family_signals(
    bars: list[dict[str, Any]],
    row: dict[str, Any],
    *,
    scan_start_iso: str | None = None,
) -> list[dict[str, Any]]:
    family = row["family"]
    ps_id = row["parameter_set_id"]
    tf = row["decision_tf"]
    prim = row["event_primitive"]
    direction = row["direction"]
    cid = row["candidate_id"]

    if family == "DMA" and ps_id in DMA_REGISTRY:
        meta = DMA_REGISTRY[ps_id]
        arrays = bars_to_arrays(bars, timeframe=tf)
        atr = np.array(
            [float(s.values["atr"]) if s.valid and s.values.get("atr") is not None else np.nan for s in compute_atr_series(arrays, 14)],
            dtype=float,
        )
        samples = compute_dma_feature_series(
            arrays, ma_type=meta["ma_type"], period=meta["period"], display_shift=meta["display_shift"], atr=atr
        )
        return _scan_primitive_series(bars, samples, candidate_id=cid, primitive=prim, direction=direction, decision_tf=tf, scan_start_iso=scan_start_iso)

    if family == "STOCHASTIC" and ps_id in STOCHASTIC_REGISTRY:
        meta = STOCHASTIC_REGISTRY[ps_id]
        arrays = bars_to_arrays(bars, timeframe=tf)
        if ps_id == "DINAPOLI_PREFERRED_STOCHASTIC_REFERENCE_V1":
            from crypto_trading_bot.research_v2.indicator_engine.engine import compute_series

            result = compute_series(bars, parameter_set_id="DINAPOLI_PREFERRED_STOCH_8_3_3_V1", source_timeframe=tf)
            return _scan_from_indicator_samples(result.samples, bars, row, scan_start_iso)
        samples = compute_stoch_feature_series(
            arrays,
            k_period=meta["k_period"],
            k_smooth=meta.get("k_smooth", meta.get("slowing", 3)),
            d_period=meta["d_period"],
            display_shift=meta.get("display_shift", 0),
        )
        return _scan_primitive_series(bars, samples, candidate_id=cid, primitive=prim, direction=direction, decision_tf=tf, scan_start_iso=scan_start_iso)

    if family == "MACD" and ps_id in MACD_REGISTRY:
        meta = MACD_REGISTRY[ps_id]
        arrays = bars_to_arrays(bars, timeframe=tf)
        if ps_id == "DINAPOLI_MACD_REFERENCE_V1":
            from crypto_trading_bot.research_v2.indicator_engine.engine import compute_series

            result = compute_series(bars, parameter_set_id="DINAPOLI_MACD_REFERENCE_V1", source_timeframe=tf)
            return _scan_from_indicator_samples(result.samples, bars, row, scan_start_iso)
        samples = compute_macd_feature_series(
            arrays,
            fast=meta["fast"],
            slow=meta["slow"],
            signal=meta["signal"],
            display_shift=meta.get("display_shift", 0),
        )
        return _scan_primitive_series(bars, samples, candidate_id=cid, primitive=prim, direction=direction, decision_tf=tf, scan_start_iso=scan_start_iso)

    if family in ("OSC_PREDICTOR", "DNO_PREDICTOR"):
        return _generate_predictor_signals(bars, row, scan_start_iso=scan_start_iso)

    return []


def _scan_from_indicator_samples(samples, bars, row, scan_start_iso):
    """Fallback for DiNapoli reference engine routes."""
    rows = []
    scan_start = parse_ts(scan_start_iso) if scan_start_iso else None
    up, down = row["up_primitive"], row["down_primitive"]
    prim = row["event_primitive"]
    for i, sample in enumerate(samples):
        if not sample.valid:
            continue
        ct = parse_ts(bars[i]["close_time"])
        if scan_start and ct < scan_start:
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
    p = row.get("parameters") or {}
    if p.get("control") == "quantile_80_20":
        return None
    if "period" in p and "lookback" in p:
        ref = FROZEN_PREDICTOR_REFERENCE
        return PredictorConfig(
            period=int(p.get("period", ref.period)),
            peak_strength=int(p.get("peak_strength", ref.peak_strength)),
            lookback=int(p.get("lookback", ref.lookback)),
            samples=int(p.get("samples", ref.samples)),
            ob_os_level_percent=float(p.get("ob_os_level_percent", ref.ob_os_level_percent)),
        )
    return FROZEN_PREDICTOR_REFERENCE


def _generate_predictor_signals(
    bars: list[dict[str, Any]],
    row: dict[str, Any],
    *,
    scan_start_iso: str | None,
) -> list[dict[str, Any]]:
    tf = row["decision_tf"]
    arrays = bars_to_arrays(bars, timeframe=tf)
    atr = np.array(
        [float(s.values["atr"]) if s.valid and s.values.get("atr") is not None else np.nan for s in compute_atr_series(arrays, 14)],
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
) -> list[dict[str, Any]]:
    if row["family"] == "INVERSE_PREDICTOR":
        from crypto_trading_bot.research_v2.reversal_signal_study.signals import generate_predictor_trigger_signals

        up_id = row["parameters"].get("inverse_route", "INVERSE_UP")
        return generate_predictor_trigger_signals(
            bars,
            candidate_id=row["candidate_id"],
            up_trigger_id=up_id,
            down_trigger_id=up_id,
            decision_tf=row["decision_tf"],
            scan_start_iso=scan_start_iso,
        )
    return generate_bank_family_signals(bars, row, scan_start_iso=scan_start_iso)


def generate_frozen_price_baselines(
    bars: list[dict[str, Any]],
    *,
    decision_tf: str,
    scan_start_iso: str | None,
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
                bars, candidate_id=cid, kind=kind, decision_tf=decision_tf, scan_start_iso=scan_start_iso
            )
        )
    return out
