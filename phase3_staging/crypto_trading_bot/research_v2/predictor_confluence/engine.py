"""Public confluence snapshot API."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from crypto_trading_bot.research_v2.indicator_engine.bars import parse_ts
from crypto_trading_bot.research_v2.inverse_predictors.version import PREDICTOR_ENGINE_VERSION
from crypto_trading_bot.research_v2.reversal_events.anti_leakage import filter_history_available_at

from .collect import (
    collect_predictor_results,
    family_normalize_nearest,
    to_trigger_points,
)
from .features import add_temporal_features, compute_static_features
from .registry import PARAMETER_REGISTRY
from .types import ConfluenceSnapshot, TriggerPoint
from .version import CONFLUENCE_ENGINE_VERSION


DEFAULT_TFS = ("5m", "15m", "1H", "4H")


def _prior_decision_time(bars: Sequence[dict[str, Any]], decision_time: Any) -> Any | None:
    hist = filter_history_available_at(bars, decision_time, require_closed=True)
    if len(hist) < 2:
        return None
    return hist[-2]["close_time"]


def _snapshot_one(
    bars: Sequence[dict[str, Any]],
    *,
    timeframe: str,
    decision_time: Any,
    parameter_set_id: str,
    view: str,
    include_temporal: bool = True,
) -> ConfluenceSnapshot:
    params = PARAMETER_REGISTRY[parameter_set_id]
    thr_pct = float(params["threshold_pct"])
    thr_atr = float(params["threshold_atr"])

    results, counts, price, atr = collect_predictor_results(bars, timeframe=timeframe, decision_time=decision_time)
    triggers = to_trigger_points(results, current_price=price, atr=atr)
    if view == "FAMILY_NORMALIZED":
        triggers = family_normalize_nearest(triggers)

    feats = compute_static_features(
        triggers,
        current_price=price,
        atr=atr,
        threshold_pct=thr_pct,
        threshold_atr=thr_atr,
        status_counts=counts,
    )

    prior_feats = prior_triggers = None
    if include_temporal:
        pdt = _prior_decision_time(bars, decision_time)
        if pdt is not None:
            pr, pc, pp, pa = collect_predictor_results(bars, timeframe=timeframe, decision_time=pdt)
            pt = to_trigger_points(pr, current_price=pp, atr=pa)
            if view == "FAMILY_NORMALIZED":
                pt = family_normalize_nearest(pt)
            prior_feats = compute_static_features(
                pt, current_price=pp, atr=pa, threshold_pct=thr_pct, threshold_atr=thr_atr, status_counts=pc
            )
            prior_triggers = pt
    feats = add_temporal_features(
        feats, triggers, prior_feats=prior_feats, prior_triggers=prior_triggers, current_price=price
    )

    hist = filter_history_available_at(bars, decision_time, require_closed=True)
    calc_at = parse_ts(hist[-1]["close_time"]) if hist else parse_ts(decision_time)
    return ConfluenceSnapshot(
        confluence_engine_version=CONFLUENCE_ENGINE_VERSION,
        predictor_engine_version=PREDICTOR_ENGINE_VERSION,
        decision_time=parse_ts(decision_time),
        calculated_at=calc_at,
        available_at=calc_at,
        parameter_set_id=parameter_set_id,
        view=view,
        scope="WITHIN_TF",
        source_timeframe=timeframe,
        timeframe_set=(timeframe,),
        current_price=price,
        atr=atr,
        features=feats,
        triggers=tuple(triggers),
    )


def _cross_tf_features(snaps: list[ConfluenceSnapshot], *, threshold_pct: float, threshold_atr: float) -> dict[str, Any]:
    all_triggers: list[TriggerPoint] = []
    for s in snaps:
        all_triggers.extend(s.triggers)
    price = snaps[0].current_price if snaps else float("nan")
    atr = next((s.atr for s in snaps if s.atr), None)
    from .cluster import cluster_triggers, nearest_cluster

    clusters = cluster_triggers(
        all_triggers, threshold_pct=threshold_pct, threshold_atr=threshold_atr, atr=atr, current_price=price
    )
    nc = nearest_cluster(clusters, price)
    return {
        "CROSS_TF_VALID_TRIGGER_COUNT": len(all_triggers),
        "CROSS_TF_DISTINCT_TF_COUNT": len({t.timeframe for t in all_triggers}),
        "CROSS_TF_NEAREST_CLUSTER_SIZE": nc.size if nc else 0,
        "CROSS_TF_NEAREST_CLUSTER_TF_DIVERSITY": len(nc.timeframes) if nc else 0,
        "CROSS_TF_NEAREST_CLUSTER_FAMILY_DIVERSITY": len(nc.families) if nc else 0,
        "CROSS_TF_CLUSTER_WIDTH_PCT": (nc.width_abs / price * 100.0) if nc and price else None,
        "CROSS_TF_CLUSTER_WIDTH_ATR": (nc.width_abs / atr) if nc and atr else None,
        "CROSS_TF_CLUSTER_COUNT": len(clusters),
    }


def compute_predictor_confluence(
    bars_by_tf: Mapping[str, Sequence[dict[str, Any]]],
    *,
    decision_time: Any,
    timeframes: Sequence[str] = DEFAULT_TFS,
    confluence_parameter_set: str = "CONF_PCT_025_ATR_050_V1",
    views: Sequence[str] = ("RAW", "FAMILY_NORMALIZED"),
    event_id: str | None = None,
) -> dict[str, Any]:
    """
    Causal confluence snapshot API for later REVERSAL-SIGNAL-EVENT-STUDY-1.

    Only closed bars <= decision_time are used (via inverse predictor causal path).
    """
    if confluence_parameter_set not in PARAMETER_REGISTRY:
        raise KeyError(confluence_parameter_set)
    params = PARAMETER_REGISTRY[confluence_parameter_set]
    out: dict[str, Any] = {
        "confluence_engine_version": CONFLUENCE_ENGINE_VERSION,
        "predictor_engine_version": PREDICTOR_ENGINE_VERSION,
        "event_id": event_id,
        "decision_time": str(decision_time),
        "parameter_set_id": confluence_parameter_set,
        "signed_distance_convention": "positive_means_trigger_above_market",
        "within_tf": {},
        "cross_tf": {},
    }
    for view in views:
        within = {}
        snaps: list[ConfluenceSnapshot] = []
        for tf in timeframes:
            bars = list(bars_by_tf.get(tf, []))
            if not bars:
                within[tf] = None
                continue
            # stamp timeframe on bars if missing for predictor source_timeframe consistency
            stamped = []
            for b in bars:
                bb = dict(b)
                bb.setdefault("timeframe", tf)
                stamped.append(bb)
            snap = _snapshot_one(
                stamped,
                timeframe=tf,
                decision_time=decision_time,
                parameter_set_id=confluence_parameter_set,
                view=view,
            )
            within[tf] = snap.to_dict()
            snaps.append(snap)
        out["within_tf"][view] = within
        if snaps:
            cross = _cross_tf_features(
                snaps, threshold_pct=float(params["threshold_pct"]), threshold_atr=float(params["threshold_atr"])
            )
            out["cross_tf"][view] = cross
        else:
            out["cross_tf"][view] = None
    return out
