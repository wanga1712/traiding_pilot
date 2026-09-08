"""Real old-path vs bounded-path parity for selected composites."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .bounded_compose import LazyBars, _delta, _evaluate_bundle, _load_events, _safe_div
from .classify import (
    classify_composite,
    count_positive_precision_delta_folds,
    count_usable_folds,
)
from .compose import _stream_events, _timeline_for_config, compose_signals, compose_signals_from_compact
from .config import (
    ARTIFACT_ROOT,
    DEVELOPMENT_END,
    DEVELOPMENT_FOLDS,
    DEVELOPMENT_START,
    OOS_OPENED,
    load_atomic_bank,
)
from .context_state import build_compact_state_arrays, pair_configs_by_stream, pair_key_from_config
from .memory_guard import save_json
from .stream_store import AtomicStreamStore


METRIC_KEYS = (
    "PRECISION",
    "EVENT_RECALL",
    "FALSE_POSITIVE_RATE",
    "MEDIAN_DELAY_SECONDS",
    "PRE_C_SIGNAL_RATE",
    "MEDIAN_MAE_AFTER_SIGNAL",
    "MEDIAN_MFE_AFTER_SIGNAL",
)


def _legacy_stream(store: AtomicStreamStore, cid: str) -> dict[str, Any]:
    s = store.get(cid)
    events = s.to_signal_dicts()
    return {
        "candidate_id": cid,
        "decision_tf": s.decision_tf,
        "direction": s.direction,
        "events": events,
        "available_at": [e["available_at"] for e in events],
        "n_signals": s.n_signals,
        "stream_hash": s.stream_hash,
    }


def _compose_reference(
    comp: dict[str, Any],
    *,
    store: AtomicStreamStore,
    config_by_id: dict[str, Any],
    pair_mates: dict,
    bars: LazyBars,
) -> list[dict[str, Any]]:
    ctx_ids = list(comp["context_candidate_ids"])
    streams = {}
    for cid in [comp["trigger_candidate_id"], *ctx_ids]:
        streams[cid] = _legacy_stream(store, cid)
        # ensure pair mates present for timeline
        cfg = config_by_id[cid]
        mates = pair_mates.get(pair_key_from_config(cfg), {})
        for side in ("UP", "DOWN"):
            row = mates.get(side)
            if row and row["candidate_id"] not in streams:
                streams[row["candidate_id"]] = _legacy_stream(store, row["candidate_id"])
    tls = []
    bars_by_tf = {}
    for ctx_id in ctx_ids:
        cfg = config_by_id[ctx_id]
        tf = cfg["decision_tf"]
        if tf not in bars_by_tf:
            bars_by_tf[tf] = bars.get(tf)
        tls.append(_timeline_for_config(cfg, streams, pair_mates, bars_by_tf))
    trig = _stream_events(streams[comp["trigger_candidate_id"]])
    return compose_signals(
        composite_id=comp["composite_id"],
        trigger_signals=trig,
        trigger_direction=comp["direction"],
        decision_tf=comp["decision_tf"],
        context_timelines=tls,
    )


def _compose_new(
    comp: dict[str, Any],
    *,
    store: AtomicStreamStore,
    config_by_id: dict[str, Any],
    pair_mates: dict,
    bars: LazyBars,
) -> list[dict[str, Any]]:
    ctx_tls = []
    for ctx_id in comp["context_candidate_ids"]:
        cfg = config_by_id[ctx_id]
        mates = pair_mates.get(pair_key_from_config(cfg), {})
        up_row = mates.get("UP")
        down_row = mates.get("DOWN")
        up_ns = store.get(up_row["candidate_id"]).available_at_ns if up_row else np.zeros(0, dtype=np.int64)
        down_ns = store.get(down_row["candidate_id"]).available_at_ns if down_row else np.zeros(0, dtype=np.int64)
        gap = bars.gap_ns(cfg["decision_tf"])
        times, codes = build_compact_state_arrays(up_ns, down_ns, gap_reset_ns=gap)
        ctx_tls.append((times, codes))
    trig = store.get(comp["trigger_candidate_id"])
    return compose_signals_from_compact(
        composite_id=comp["composite_id"],
        trigger_ns=trig.available_at_ns,
        trigger_prices=trig.signal_price,
        trigger_direction=comp["direction"],
        decision_tf=comp["decision_tf"],
        context_timelines=ctx_tls,
    )


def _metric_bundle(sigs, events, bars, comp, config_by_id, store, price_cache: dict):
    tf = comp["decision_tf"]
    direction = comp["direction"]
    cid = comp["composite_id"]
    trig_id = comp["trigger_candidate_id"]
    agg = _evaluate_bundle(
        sigs,
        events,
        candidate_id=cid,
        decision_tf=tf,
        direction=direction,
        family="COMPOSITE",
        start=DEVELOPMENT_START,
        end=DEVELOPMENT_END,
        bars=bars.get(tf),
    )
    trig_cfg = config_by_id[trig_id]
    trig_sigs = store.get(trig_id).to_signal_dicts(direction=direction, decision_tf=trig_cfg["decision_tf"])
    trig_m = _evaluate_bundle(
        trig_sigs,
        events,
        candidate_id=trig_id,
        decision_tf=trig_cfg["decision_tf"],
        direction=direction,
        family=trig_cfg["family"],
        start=DEVELOPMENT_START,
        end=DEVELOPMENT_END,
        bars=bars.get(trig_cfg["decision_tf"]),
    )
    pk = (tf, direction)
    if pk not in price_cache:
        price_cid = f"PRICE_ONE_BAR_DIRECTION_CHANGE_{tf}"
        price_sigs = [
            s
            for s in bars.baselines(tf)
            if s["candidate_id"] == price_cid and s.get("signal_direction") == direction
        ]
        price_cache[pk] = _evaluate_bundle(
            price_sigs,
            events,
            candidate_id=price_cid,
            decision_tf=tf,
            direction=direction,
            family="PRICE_ONLY",
            start=DEVELOPMENT_START,
            end=DEVELOPMENT_END,
            bars=bars.get(tf),
        )
    price_m = price_cache[pk]
    fold_prec = []
    fold_counts = []
    for _fid, fs, fe in DEVELOPMENT_FOLDS:
        fm = _evaluate_bundle(
            sigs, events, candidate_id=cid, decision_tf=tf, direction=direction, family="COMPOSITE", start=fs, end=fe, bars=bars.get(tf)
        )
        tm = _evaluate_bundle(
            trig_sigs,
            events,
            candidate_id=trig_id,
            decision_tf=trig_cfg["decision_tf"],
            direction=direction,
            family=trig_cfg["family"],
            start=fs,
            end=fe,
            bars=bars.get(trig_cfg["decision_tf"]),
        )
        fold_prec.append(_delta(fm.get("PRECISION"), tm.get("PRECISION")))
        fold_counts.append(int(fm.get("TOTAL_SIGNALS") or 0))
    usable = count_usable_folds(fold_counts)
    pos = count_positive_precision_delta_folds(fold_prec, fold_counts)
    cclass = classify_composite(
        aggregate_sample_flag=str(agg.get("sample_flag") or "INSUFFICIENT"),
        precision_delta_vs_trigger=_delta(agg.get("PRECISION"), trig_m.get("PRECISION")),
        recall_retention_vs_trigger=_safe_div(agg.get("EVENT_RECALL"), trig_m.get("EVENT_RECALL")),
        fpr_delta_vs_trigger=_delta(agg.get("FALSE_POSITIVE_RATE"), trig_m.get("FALSE_POSITIVE_RATE")),
        fold_precision_deltas=fold_prec,
        fold_signal_counts=fold_counts,
    )
    return {
        "agg": agg,
        "trig": trig_m,
        "PRECISION_DELTA_VS_TRIGGER": _delta(agg.get("PRECISION"), trig_m.get("PRECISION")),
        "PRECISION_DELTA_VS_PRICE_BASELINE": _delta(agg.get("PRECISION"), price_m.get("PRECISION")),
        "RECALL_RETENTION_VS_TRIGGER": _safe_div(agg.get("EVENT_RECALL"), trig_m.get("EVENT_RECALL")),
        "FPR_DELTA_VS_TRIGGER": _delta(agg.get("FALSE_POSITIVE_RATE"), trig_m.get("FALSE_POSITIVE_RATE")),
        "usable_folds": usable,
        "positive_delta_folds": pos,
        "sample_flag": agg.get("sample_flag"),
        "composite_class": cclass,
    }


def _float_close(a, b, tol=1e-12) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= tol


def run_old_new_parity(
    definitions: list[dict[str, Any]],
    *,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    assert OOS_OPENED == "NO"
    root = artifact_root or ARTIFACT_ROOT
    store = AtomicStreamStore(root, max_active=5, require_shards=True)
    events = _load_events()
    all_configs = list(load_atomic_bank(root=root)["configs"])
    config_by_id = {c["candidate_id"]: c for c in all_configs}
    pair_mates = pair_configs_by_stream(all_configs)
    bars = LazyBars(max_cached=2)

    rows = []
    ts_fail = metric_fail = class_fail = 0
    price_cache: dict = {}
    for i, comp in enumerate(definitions):
        ref_sigs = _compose_reference(comp, store=store, config_by_id=config_by_id, pair_mates=pair_mates, bars=bars)
        new_sigs = _compose_new(comp, store=store, config_by_id=config_by_id, pair_mates=pair_mates, bars=bars)
        ref_ts = [str(s["available_at"]) for s in ref_sigs]
        new_ts = [str(s["available_at"]) for s in new_sigs]
        ts_ok = ref_ts == new_ts and len(ref_sigs) == len(new_sigs)
        if not ts_ok:
            ts_fail += 1

        ref_m = _metric_bundle(ref_sigs, events, bars, comp, config_by_id, store, price_cache)
        new_m = _metric_bundle(new_sigs, events, bars, comp, config_by_id, store, price_cache)
        metric_ok = all(_float_close(ref_m["agg"].get(k), new_m["agg"].get(k)) for k in METRIC_KEYS)
        if not metric_ok:
            metric_fail += 1
        class_ok = (
            _float_close(ref_m["PRECISION_DELTA_VS_TRIGGER"], new_m["PRECISION_DELTA_VS_TRIGGER"])
        ) and (
            _float_close(ref_m["PRECISION_DELTA_VS_PRICE_BASELINE"], new_m["PRECISION_DELTA_VS_PRICE_BASELINE"])
        ) and (
            _float_close(ref_m["RECALL_RETENTION_VS_TRIGGER"], new_m["RECALL_RETENTION_VS_TRIGGER"])
        ) and (
            _float_close(ref_m["FPR_DELTA_VS_TRIGGER"], new_m["FPR_DELTA_VS_TRIGGER"])
        ) and ref_m["usable_folds"] == new_m["usable_folds"] and ref_m["positive_delta_folds"] == new_m["positive_delta_folds"] and ref_m["sample_flag"] == new_m["sample_flag"] and ref_m["composite_class"] == new_m["composite_class"]
        if not class_ok:
            class_fail += 1

        rows.append(
            {
                "composite_id": comp["composite_id"],
                "template_id": comp["template_id"],
                "decision_tf": comp["decision_tf"],
                "direction": comp["direction"],
                "n_signals_ref": len(ref_sigs),
                "n_signals_new": len(new_sigs),
                "timestamp_parity": ts_ok,
                "metric_parity": metric_ok,
                "class_input_parity": class_ok,
            }
        )
        if (i + 1) % 10 == 0:
            print(f"[parity] {i + 1}/{len(definitions)} ts_fail={ts_fail} metric_fail={metric_fail} class_fail={class_fail}", flush=True)
        store.release()

    df = pd.DataFrame(rows)
    df.to_csv(root / "composite_old_new_parity_v1.csv", index=False)
    summary = {
        "artifact": "composite_old_new_parity_summary_v1",
        "REAL_PARITY_SAMPLE_COUNT": len(rows),
        "REAL_PARITY_ALL_TEMPLATES": "YES"
        if len({r["template_id"] for r in rows}) >= 6
        else "NO",
        "COMPOSITE_TIMESTAMP_PARITY": "PASS" if ts_fail == 0 else "FAIL",
        "COMPOSITE_METRIC_PARITY": "PASS" if metric_fail == 0 else "FAIL",
        "COMPOSITE_CLASS_INPUT_PARITY": "PASS" if class_fail == 0 else "FAIL",
        "timestamp_failures": ts_fail,
        "metric_failures": metric_fail,
        "class_failures": class_fail,
        "OOS_OPENED": OOS_OPENED,
        "OOS_ACCESS_COUNT": 0,
    }
    save_json(root / "composite_old_new_parity_summary_v1.json", summary)
    return summary
