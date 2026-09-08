"""Bounded-memory composite compose runner (execution repair)."""
from __future__ import annotations

import gc
import hashlib
import json
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import pandas as pd

from crypto_trading_bot.research_v2.indicator_parameter_search.signals_bank import (
    generate_frozen_price_baselines,
)
from crypto_trading_bot.research_v2.market_data.research_access import run_data_location_preflight
from crypto_trading_bot.research_v2.reversal_signal_study.bar_io import load_continuous_bars, make_bar_service

from . import MODE, WIP_ID
from .classify import (
    classify_composite,
    classification_payload,
    count_positive_precision_delta_folds,
    count_usable_folds,
)
from .compose import compose_signals_from_compact, iter_all_template_definitions
from .config import (
    ARTIFACT_ROOT,
    COMPOSITE_FDR_STATUS,
    DEVELOPMENT_END,
    DEVELOPMENT_FOLDS,
    DEVELOPMENT_START,
    EVENT_DIR,
    OOS_OPENED,
    SEARCH_TFS,
    TF_BAR_SECONDS,
    load_atomic_bank,
    load_templates,
)
from .context_state import (
    build_compact_state_arrays,
    detect_gap_reset_times,
    pair_configs_by_stream,
    pair_key_from_config,
)
from .evaluate_window import evaluate_signals_window
from .memory_guard import (
    COMPOSITE_CHECKPOINT,
    COMPOSITE_CHECKPOINT_EVERY,
    COMPOSITE_FOLD_PARTIAL,
    COMPOSITE_RESULT_BATCH_SIZE,
    COMPOSITE_RESULT_PARTIAL,
    MemoryGuardStop,
    default_memory_guard,
    read_rss_bytes,
    read_vms_bytes,
    save_json,
)
from .oos_guard import assert_events_exclude_oos, assert_oos_locked, guard_partition_iterable
from .stream_store import AtomicStreamStore, materialize_shards_from_pickle


def _load_events() -> pd.DataFrame:
    guard_partition_iterable(("DISCOVERY", "VALIDATION"), context="load_events")
    ev = pd.read_parquet(EVENT_DIR / "reversal_events_v1.parquet")
    out = ev[(ev["partition"].isin(["DISCOVERY", "VALIDATION"])) & (ev["partition_usable"] == True)].reset_index(  # noqa: E712
        drop=True
    )
    assert_events_exclude_oos(out, context="filtered_events")
    return out


def _load_bars(service: Any, tf: str, start: Any, end: Any, *, warmup_bars: int = 500) -> list:
    loaded = load_continuous_bars(service, tf, start, end, warmup_bars=warmup_bars)
    if isinstance(loaded, tuple):
        return loaded[0]
    return loaded


def _delta(a: Any, b: Any) -> float | None:
    if a is None or b is None:
        return None
    try:
        return float(a) - float(b)
    except (TypeError, ValueError):
        return None


def _safe_div(a: Any, b: Any) -> float | None:
    try:
        bb = float(b)
        if bb == 0:
            return None
        return float(a) / bb
    except (TypeError, ValueError):
        return None


def _evaluate_bundle(signals, events, **kwargs):
    return evaluate_signals_window(signals, events, **kwargs)


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _gap_resets_for_tf(bars: list, tf: str) -> np.ndarray:
    closes = [b["close_time"] for b in bars]
    resets = detect_gap_reset_times(closes, expected_bar_seconds=float(TF_BAR_SECONDS.get(tf, 3600)))
    if not resets:
        return np.zeros(0, dtype=np.int64)
    return np.fromiter(
        (int(r.timestamp() * 1_000_000_000) for r in resets),
        dtype=np.int64,
        count=len(resets),
    )


class LazyBars:
    """Load at most a few TF bar sets; FULL_BARS_ALL_TFS_RESIDENT_DURING_COMPOSE=NO."""

    def __init__(self, *, max_cached: int = 2) -> None:
        self._service = None
        self._cache: OrderedDict[str, list] = OrderedDict()
        self._max = max_cached
        self._gap_ns: dict[str, np.ndarray] = {}
        self._baselines: dict[str, list] = {}

    def _svc(self):
        if self._service is None:
            self._service = make_bar_service()
        return self._service

    def get(self, tf: str) -> list:
        if tf in self._cache:
            self._cache.move_to_end(tf)
            return self._cache[tf]
        bars = _load_bars(self._svc(), tf, DEVELOPMENT_START, DEVELOPMENT_END, warmup_bars=500)
        self._cache[tf] = bars
        self._cache.move_to_end(tf)
        while len(self._cache) > self._max:
            self._cache.popitem(last=False)
        return bars

    def gap_ns(self, tf: str) -> np.ndarray:
        if tf not in self._gap_ns:
            self._gap_ns[tf] = _gap_resets_for_tf(self.get(tf), tf)
        return self._gap_ns[tf]

    def baselines(self, tf: str) -> list:
        if tf not in self._baselines:
            self._baselines[tf] = generate_frozen_price_baselines(
                self.get(tf),
                decision_tf=tf,
                scan_start_iso=DEVELOPMENT_START.isoformat(),
                scan_end_iso=DEVELOPMENT_END.isoformat(),
            )
        return self._baselines[tf]


def _append_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    df = pd.DataFrame(rows)
    if path.exists():
        prev = pd.read_parquet(path)
        df = pd.concat([prev, df], ignore_index=True)
    df.to_parquet(path, index=False)


def run_bounded_compose(
    *,
    artifact_root: Path | None = None,
    max_candidates: int | None = None,
    smoke_rss_csv: Path | None = None,
    template_filter: set[str] | None = None,
    resume: bool = True,
) -> dict[str, Any]:
    """
    Streaming compose with disk-backed streams, incremental flush, memory guard.

    Does not change frozen methodology — only execution memory profile.
    """
    root = artifact_root or ARTIFACT_ROOT
    root.mkdir(parents=True, exist_ok=True)
    guard = default_memory_guard()
    # OOS remains locked; refuse via event/partition guards below (never call assert_oos_locked preemptively).
    assert OOS_OPENED == "NO"

    # Authorities (frozen artifacts — read-only integrity)
    spec_path = root / "composite_search_spec_v1.json"
    tmpl_path = root / "composite_templates_v1.json"
    bank_path = root / "composite_atomic_bank_v1.json"
    corpus_path = root / "development_corpus_manifest_v1.json"
    authorities = {
        "COMPOSITE_SEARCH_SPEC_SHA": _file_sha256(spec_path) if spec_path.exists() else None,
        "COMPOSITE_TEMPLATES_SHA": _file_sha256(tmpl_path) if tmpl_path.exists() else None,
        "COMPOSITE_ATOMIC_BANK_SHA": _file_sha256(bank_path) if bank_path.exists() else None,
        "DEVELOPMENT_CORPUS_SHA": _file_sha256(corpus_path) if corpus_path.exists() else None,
        "SPEC_FREEZE_COMMIT": "476927817e21ef6869261a0114b27864fdf2d789",
    }

    materialize_shards_from_pickle(artifact_root=root)
    store = AtomicStreamStore(root, max_active=5)
    assert len(store) == 582, f"expected 582 shards, got {len(store)}"

    events = _load_events()
    # Prefilter events once — avoid events.copy() storm in evaluate hot path.
    events_dev = events.copy()
    reps_bank = json.loads((root / "atomic_representative_bank_v1.json").read_text(encoding="utf-8"))
    reps = list(reps_bank["configs"])
    all_configs = list(load_atomic_bank(root=root)["configs"])
    config_by_id = {c["candidate_id"]: c for c in all_configs}
    pair_mates = pair_configs_by_stream(all_configs)

    preflight = run_data_location_preflight(
        required_start=DEVELOPMENT_START,
        required_end=DEVELOPMENT_END,
        artifact_root=root,
    )
    _ = preflight
    bars = LazyBars(max_cached=2)

    ckpt_path = root / COMPOSITE_CHECKPOINT
    completed: set[str] = set()
    next_index = 0
    if resume and ckpt_path.exists():
        ckpt = json.loads(ckpt_path.read_text(encoding="utf-8"))
        if ckpt.get("authorities") == authorities:
            completed = set(ckpt.get("completed_composite_ids") or [])
            next_index = int(ckpt.get("next_candidate_index") or 0)
            print(f"[bounded-compose] resume completed={len(completed)} next_index={next_index}", flush=True)
        else:
            print("[bounded-compose] checkpoint authority mismatch — starting fresh compose results", flush=True)
            completed = set()
            next_index = 0

    result_batch: list[dict[str, Any]] = []
    fold_batch: list[dict[str, Any]] = []
    trigger_cache: dict[str, dict[str, Any]] = {}
    price_cache: dict[tuple[str, str], dict[str, Any]] = {}
    timeline_cache: OrderedDict[str, tuple[np.ndarray, np.ndarray]] = OrderedDict()
    TIMELINE_CACHE_MAX = 32

    smoke_rows: list[dict[str, Any]] = []
    last_rss_poll = 0.0
    oos_access_count = 0
    evaluated = 0
    skipped = 0
    memory_guard_stop = False
    stop_reason = ""

    templates_doc = load_templates(root=root)
    if template_filter:
        templates_doc = {
            **templates_doc,
            "templates": [t for t in templates_doc["templates"] if t["template_id"] in template_filter],
        }

    def _get_timeline(ctx_cfg: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
        key = ctx_cfg["candidate_id"]
        if key in timeline_cache:
            timeline_cache.move_to_end(key)
            return timeline_cache[key]
        mates = pair_mates.get(pair_key_from_config(ctx_cfg), {})
        up_row = mates.get("UP")
        down_row = mates.get("DOWN")
        up_ns = store.get(up_row["candidate_id"]).available_at_ns if up_row else np.zeros(0, dtype=np.int64)
        down_ns = store.get(down_row["candidate_id"]).available_at_ns if down_row else np.zeros(0, dtype=np.int64)
        gap = bars.gap_ns(ctx_cfg["decision_tf"])
        times, codes = build_compact_state_arrays(up_ns, down_ns, gap_reset_ns=gap)
        timeline_cache[key] = (times, codes)
        timeline_cache.move_to_end(key)
        while len(timeline_cache) > TIMELINE_CACHE_MAX:
            timeline_cache.popitem(last=False)
        return times, codes

    def _flush() -> None:
        nonlocal result_batch, fold_batch
        _append_parquet(root / COMPOSITE_RESULT_PARTIAL, result_batch)
        _append_parquet(root / COMPOSITE_FOLD_PARTIAL, fold_batch)
        result_batch = []
        fold_batch = []
        gc.collect()

    def _write_ckpt(idx: int) -> None:
        save_json(
            ckpt_path,
            {
                "artifact": "composite_execution_checkpoint_v1",
                "WIP": WIP_ID,
                "MODE": "COMPOSITE-BOUNDED-MEMORY-EXECUTION-REPAIR-1",
                "authorities": authorities,
                "next_candidate_index": idx,
                "completed_composite_ids": sorted(completed),
                "n_completed": len(completed),
                "OOS_OPENED": OOS_OPENED,
                "OOS_ACCESS_COUNT": oos_access_count,
                "COMPOSITE_FDR_STATUS": COMPOSITE_FDR_STATUS,
                "ATOMIC_STREAM_LAZY_LOAD": "YES",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    definitions = iter_all_template_definitions(
        representatives=reps,
        all_configs_for_pairs=all_configs,
        templates_doc=templates_doc,
    )

    idx = max(next_index - 1, -1)
    for idx, comp in enumerate(definitions):
        if idx < next_index:
            skipped += 1
            continue
        cid = comp["composite_id"]
        if cid in completed:
            skipped += 1
            continue
        if max_candidates is not None and evaluated >= max_candidates:
            break

        try:
            guard.check(context=f"before {cid}")
        except MemoryGuardStop as exc:
            _flush()
            _write_ckpt(idx)
            memory_guard_stop = True
            stop_reason = str(exc)
            break

        tf = comp["decision_tf"]
        direction = comp["direction"]
        trig_id = comp["trigger_candidate_id"]
        ctx_ids = list(comp["context_candidate_ids"])

        # Build compact context timelines (max 2) + trigger stream.
        ctx_tls = []
        for ctx_id in ctx_ids:
            ctx_cfg = config_by_id[ctx_id]
            ctx_tls.append(_get_timeline(ctx_cfg))
        trig = store.get(trig_id)
        sigs = compose_signals_from_compact(
            composite_id=cid,
            trigger_ns=trig.available_at_ns,
            trigger_prices=trig.signal_price,
            trigger_direction=direction,
            decision_tf=tf,
            context_timelines=ctx_tls,
        )

        tf_bars = bars.get(tf)
        agg = _evaluate_bundle(
            sigs,
            events_dev,
            candidate_id=cid,
            decision_tf=tf,
            direction=direction,
            family="COMPOSITE",
            start=DEVELOPMENT_START,
            end=DEVELOPMENT_END,
            bars=tf_bars,
        )

        if trig_id not in trigger_cache:
            trig_cfg = config_by_id[trig_id]
            trig_sigs = store.get(trig_id).to_signal_dicts(
                direction=direction, decision_tf=trig_cfg["decision_tf"]
            )
            trigger_cache[trig_id] = _evaluate_bundle(
                trig_sigs,
                events_dev,
                candidate_id=trig_id,
                decision_tf=trig_cfg["decision_tf"],
                direction=direction,
                family=trig_cfg["family"],
                start=DEVELOPMENT_START,
                end=DEVELOPMENT_END,
                bars=bars.get(trig_cfg["decision_tf"]),
            )
        trig_m = trigger_cache[trig_id]

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
                events_dev,
                candidate_id=price_cid,
                decision_tf=tf,
                direction=direction,
                family="PRICE_ONLY",
                start=DEVELOPMENT_START,
                end=DEVELOPMENT_END,
                bars=tf_bars,
            )
        price_m = price_cache[pk]

        precision_delta_trig = _delta(agg.get("PRECISION"), trig_m.get("PRECISION"))
        precision_delta_price = _delta(agg.get("PRECISION"), price_m.get("PRECISION"))
        recall_retention = _safe_div(agg.get("EVENT_RECALL"), trig_m.get("EVENT_RECALL"))
        fpr_delta_trig = _delta(agg.get("FALSE_POSITIVE_RATE"), trig_m.get("FALSE_POSITIVE_RATE"))
        delay_delta = _delta(agg.get("MEDIAN_DELAY_SECONDS"), trig_m.get("MEDIAN_DELAY_SECONDS"))
        prec_rate_delta = _delta(agg.get("PRE_C_SIGNAL_RATE"), trig_m.get("PRE_C_SIGNAL_RATE"))
        signal_retention = _safe_div(agg.get("TOTAL_SIGNALS"), trig_m.get("TOTAL_SIGNALS"))

        fold_prec_deltas: list[float | None] = []
        fold_counts: list[int] = []
        trig_cfg = config_by_id[trig_id]
        trig_sigs = store.get(trig_id).to_signal_dicts(
            direction=direction, decision_tf=trig_cfg["decision_tf"]
        )
        for fold_id, fs, fe in DEVELOPMENT_FOLDS:
            fm = _evaluate_bundle(
                sigs,
                events_dev,
                candidate_id=cid,
                decision_tf=tf,
                direction=direction,
                family="COMPOSITE",
                start=fs,
                end=fe,
                bars=tf_bars,
            )
            tm = _evaluate_bundle(
                trig_sigs,
                events_dev,
                candidate_id=trig_id,
                decision_tf=trig_cfg["decision_tf"],
                direction=direction,
                family=trig_cfg["family"],
                start=fs,
                end=fe,
                bars=bars.get(trig_cfg["decision_tf"]),
            )
            fpd = _delta(fm.get("PRECISION"), tm.get("PRECISION"))
            fold_prec_deltas.append(fpd)
            fold_counts.append(int(fm.get("TOTAL_SIGNALS") or 0))
            fold_batch.append(
                {
                    "composite_id": cid,
                    "fold_id": fold_id,
                    "TOTAL_SIGNALS": fm.get("TOTAL_SIGNALS"),
                    "PRECISION": fm.get("PRECISION"),
                    "PRECISION_DELTA_VS_TRIGGER": fpd,
                    "EVENT_RECALL": fm.get("EVENT_RECALL"),
                    "FALSE_POSITIVE_RATE": fm.get("FALSE_POSITIVE_RATE"),
                    "sample_flag": fm.get("sample_flag"),
                    "trigger_TOTAL_SIGNALS": tm.get("TOTAL_SIGNALS"),
                    "trigger_PRECISION": tm.get("PRECISION"),
                }
            )

        usable = count_usable_folds(fold_counts)
        pos_folds = count_positive_precision_delta_folds(fold_prec_deltas, fold_counts)
        cclass = classify_composite(
            aggregate_sample_flag=str(agg.get("sample_flag") or "INSUFFICIENT"),
            precision_delta_vs_trigger=precision_delta_trig,
            recall_retention_vs_trigger=recall_retention,
            fpr_delta_vs_trigger=fpr_delta_trig,
            fold_precision_deltas=fold_prec_deltas,
            fold_signal_counts=fold_counts,
        )
        payload = classification_payload(
            composite_class=cclass, usable_folds=usable, positive_delta_folds=pos_folds
        )

        result_batch.append(
            {
                "composite_id": cid,
                "template_id": comp["template_id"],
                "direction": direction,
                "decision_tf": tf,
                "diagnostic": comp.get("diagnostic", False),
                "trigger_candidate_id": trig_id,
                "context_candidate_ids": "|".join(ctx_ids),
                "TOTAL_SIGNALS": agg.get("TOTAL_SIGNALS"),
                "PRECISION": agg.get("PRECISION"),
                "EVENT_RECALL": agg.get("EVENT_RECALL"),
                "FALSE_POSITIVE_RATE": agg.get("FALSE_POSITIVE_RATE"),
                "MEDIAN_DELAY_SECONDS": agg.get("MEDIAN_DELAY_SECONDS"),
                "MEDIAN_MFE_AFTER_SIGNAL": agg.get("MEDIAN_MFE_AFTER_SIGNAL"),
                "MEDIAN_MAE_AFTER_SIGNAL": agg.get("MEDIAN_MAE_AFTER_SIGNAL"),
                "PRE_C_SIGNAL_RATE": agg.get("PRE_C_SIGNAL_RATE"),
                "sample_flag": agg.get("sample_flag"),
                "trigger_PRECISION": trig_m.get("PRECISION"),
                "trigger_EVENT_RECALL": trig_m.get("EVENT_RECALL"),
                "trigger_TOTAL_SIGNALS": trig_m.get("TOTAL_SIGNALS"),
                "trigger_FALSE_POSITIVE_RATE": trig_m.get("FALSE_POSITIVE_RATE"),
                "price_PRECISION": price_m.get("PRECISION"),
                "PRECISION_DELTA_VS_TRIGGER": precision_delta_trig,
                "PRECISION_DELTA_VS_PRICE_BASELINE": precision_delta_price,
                "RECALL_RETENTION_VS_TRIGGER": recall_retention,
                "FPR_DELTA_VS_TRIGGER": fpr_delta_trig,
                "MEDIAN_DELAY_DELTA_VS_TRIGGER": delay_delta,
                "PRE_C_SIGNAL_RATE_DELTA_VS_TRIGGER": prec_rate_delta,
                "SIGNAL_RETENTION": signal_retention,
                "usable_folds": usable,
                "positive_delta_folds": pos_folds,
                "composite_class": cclass,
                "is_survivor": payload["is_survivor"],
            }
        )

        # Discard composite stream immediately (metrics already captured).
        del sigs
        completed.add(cid)
        evaluated += 1

        now = time.time()
        if smoke_rss_csv is not None and (now - last_rss_poll) >= 5.0:
            last_rss_poll = now
            smoke_rows.append(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "candidate_index": idx,
                    "template": comp["template_id"],
                    "rss_mb": read_rss_bytes() / (1024 * 1024),
                    "vms_mb": read_vms_bytes() / (1024 * 1024),
                    "active_stream_count": store.active_count,
                    "result_batch_rows": len(result_batch),
                }
            )

        if len(result_batch) >= COMPOSITE_RESULT_BATCH_SIZE:
            _flush()
        if evaluated % COMPOSITE_CHECKPOINT_EVERY == 0:
            _flush()
            _write_ckpt(idx + 1)
            print(
                f"[bounded-compose] evaluated={evaluated} completed={len(completed)} "
                f"rss_gb={guard.rss_gb():.2f} active_streams={store.active_count}",
                flush=True,
            )
            store.release()
            gc.collect()

        try:
            guard.check(context=f"after {cid}")
        except MemoryGuardStop as exc:
            _flush()
            _write_ckpt(idx + 1)
            memory_guard_stop = True
            stop_reason = str(exc)
            break

    _flush()
    final_idx = idx + 1 if evaluated or skipped or memory_guard_stop else next_index
    _write_ckpt(final_idx)

    if smoke_rss_csv is not None:
        pd.DataFrame(smoke_rows).to_csv(smoke_rss_csv, index=False)

    out = {
        "WIP": WIP_ID,
        "MODE": "COMPOSITE-BOUNDED-MEMORY-EXECUTION-REPAIR-1",
        "n_evaluated": evaluated,
        "n_skipped": skipped,
        "n_completed_total": len(completed),
        "memory_guard_stop": memory_guard_stop,
        "stop_reason": stop_reason,
        "rss_gb": guard.rss_gb(),
        "active_stream_count": store.active_count,
        "OOS_OPENED": OOS_OPENED,
        "OOS_ACCESS_COUNT": oos_access_count,
        "COMPOSITE_FDR_STATUS": COMPOSITE_FDR_STATUS,
        "authorities": authorities,
        "ATOMIC_STREAM_LAZY_LOAD": "YES",
        "ALL_582_STREAMS_RESIDENT_SIMULTANEOUSLY": "NO",
        "COMPOSITE_DEFINITION_GENERATOR": "YES",
        "RESULT_INCREMENTAL_FLUSH": "YES",
        "APPLICATION_MEMORY_GUARD": "YES",
        "MEMORY_GUARD_THRESHOLD_GB": guard.threshold_gb,
    }
    save_json(root / "bounded_compose_run_status_v1.json", out)
    return out
