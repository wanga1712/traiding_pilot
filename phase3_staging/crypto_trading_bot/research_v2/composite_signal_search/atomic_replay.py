"""Atomic stream replay, validation parity, exact/near dedup representatives."""
from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import os
import pickle
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from crypto_trading_bot.research_v2.indicator_engine.bars import parse_ts
from crypto_trading_bot.research_v2.indicator_parameter_search.signals_bank import generate_signals_for_row
from crypto_trading_bot.research_v2.reversal_signal_study.bar_io import load_continuous_bars, make_bar_service

from .config import (
    ARTIFACT_ROOT,
    ATOMIC_INDICATOR_RECOMPUTE_PER_COMPOSITE,
    ATOMIC_REPRESENTATIVE_CAP,
    DEVELOPMENT_END,
    DEVELOPMENT_START,
    NEAR_REDUNDANCY_JACCARD,
    PARENT_ARTIFACT_ROOT,
    SEARCH_TFS,
    VALIDATION_PARITY_END,
    VALIDATION_PARITY_START,
    load_atomic_bank,
)
from .evaluate_window import evaluate_signals_window
from .oos_guard import assert_events_exclude_oos, guard_partition_iterable


def stream_hash(*, tf: str, direction: str, available_at_isos: list[str]) -> str:
    """Exact stream hash: sha256(tf + '\\0' + direction + '\\0' + '\\n'.join(ordered AVAILABLE_AT))."""
    payload = f"{tf}\0{direction}\0" + "\n".join(available_at_isos)
    return hashlib.sha256(payload.encode()).hexdigest()


def signals_to_stream_record(
    signals: list[dict[str, Any]],
    *,
    candidate_id: str,
    tf: str,
    direction: str,
) -> dict[str, Any]:
    # Preserve causal order as emitted (do not sort for hash).
    events = [
        {
            "available_at": str(s["available_at"]),
            "signal_time": str(s.get("signal_time", s["available_at"])),
            "signal_direction": s.get("signal_direction", direction),
            "signal_price": s.get("signal_price"),
            "calculated_at": s.get("calculated_at"),
        }
        for s in signals
    ]
    available_ats = [e["available_at"] for e in events]
    return {
        "candidate_id": candidate_id,
        "decision_tf": tf,
        "direction": direction,
        "n_signals": len(events),
        "available_at": available_ats,
        "events": events,
        "stream_hash": stream_hash(tf=tf, direction=direction, available_at_isos=available_ats),
        "ATOMIC_INDICATOR_RECOMPUTE_PER_COMPOSITE": ATOMIC_INDICATOR_RECOMPUTE_PER_COMPOSITE,
    }


def _load_bars(service: Any, tf: str, start: datetime, end: datetime, *, warmup_bars: int = 500) -> list:
    loaded = load_continuous_bars(service, tf, start, end, warmup_bars=warmup_bars)
    if isinstance(loaded, tuple):
        return loaded[0]
    return loaded


CHECKPOINT_PKL = "atomic_streams_checkpoint_v1.pkl"
CHECKPOINT_META = "atomic_replay_progress_v1.json"
FINAL_CACHE_PKL = "atomic_streams_cache_v1.pkl"
# Persist after every completed candidate so a kill/power-off can resume.
CHECKPOINT_EVERY = 1

# Inherited by forked workers (Linux). Avoids pickling multi-GB bar frames.
_WORKER_BARS_BY_TF: dict[str, list] | None = None
_WORKER_START_ISO: str = ""
_WORKER_END_ISO: str = ""


def atomic_replay_workers() -> int:
    """Parallel workers for remaining atomic candidates. Default 1 (sequential)."""
    raw = os.environ.get("ATOMIC_REPLAY_WORKERS", "1").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 1
    return max(1, n)


def _worker_replay_row(row: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Process entrypoint: replay one atomic config using inherited bars."""
    assert _WORKER_BARS_BY_TF is not None
    sample_cache: dict[tuple, Any] = {}
    inverse_threshold_cache: dict[tuple, Any] = {}
    tf = row["decision_tf"]
    sigs = generate_signals_for_row(
        _WORKER_BARS_BY_TF[tf],
        row,
        scan_start_iso=_WORKER_START_ISO,
        scan_end_iso=_WORKER_END_ISO,
        sample_cache=sample_cache,
        inverse_threshold_cache=inverse_threshold_cache,
    )
    rec = signals_to_stream_record(
        sigs,
        candidate_id=row["candidate_id"],
        tf=tf,
        direction=row["direction"],
    )
    return row["candidate_id"], rec, row


def _atomic_pickle_dump(path: Path, obj: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("wb") as fh:
        pickle.dump(obj, fh, protocol=pickle.HIGHEST_PROTOCOL)
        fh.flush()
        try:
            import os

            os.fsync(fh.fileno())
        except OSError:
            pass
    tmp.replace(path)


def _atomic_json_dump(path: Path, obj: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def load_atomic_checkpoint(*, artifact_root: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load incremental checkpoint if present; else empty."""
    root = artifact_root or ARTIFACT_ROOT
    path = root / CHECKPOINT_PKL
    if not path.exists():
        # Fall back to final cache if a previous full run finished.
        final = root / FINAL_CACHE_PKL
        if final.exists():
            with final.open("rb") as fh:
                return pickle.load(fh)
        return {}
    with path.open("rb") as fh:
        return pickle.load(fh)


def save_atomic_checkpoint(
    streams: dict[str, dict[str, Any]],
    *,
    artifact_root: Path | None = None,
    completed: int = 0,
    total: int = 0,
    last_candidate_id: str = "",
    start_iso: str = "",
    end_iso: str = "",
) -> None:
    root = artifact_root or ARTIFACT_ROOT
    root.mkdir(parents=True, exist_ok=True)
    _atomic_pickle_dump(root / CHECKPOINT_PKL, streams)
    _atomic_json_dump(
        root / CHECKPOINT_META,
        {
            "artifact": "atomic_replay_progress_v1",
            "completed": completed,
            "total": total,
            "n_streams_cached": len(streams),
            "last_candidate_id": last_candidate_id,
            "development_start": start_iso,
            "development_end": end_iso,
            "resumable": True,
        },
    )


def replay_atomic_bank(
    configs: list[dict[str, Any]] | None = None,
    *,
    events: pd.DataFrame | None = None,
    artifact_root: Path | None = None,
    bars_by_tf: dict[str, list] | None = None,
    scan_start: datetime | None = None,
    scan_end: datetime | None = None,
    resume: bool = True,
) -> dict[str, Any]:
    """
    Replay all atomic configs once over DEVELOPMENT.

    ATOMIC_INDICATOR_RECOMPUTE_PER_COMPOSITE=NO — streams are cached by candidate_id.
    Incremental checkpoint is written after every candidate (CHECKPOINT_EVERY=1)
    so a kill/power-off can resume without recomputing finished IDs.
    """
    root = artifact_root or ARTIFACT_ROOT
    root.mkdir(parents=True, exist_ok=True)
    bank = load_atomic_bank(root=root) if configs is None else {"configs": configs}
    rows = list(bank["configs"])
    if len(rows) != 582 and configs is None:
        # Frozen bank must be 582; allow injected subsets for tests.
        if Path(root / "composite_atomic_bank_v1.json").exists():
            raise RuntimeError(f"expected 582 atomic configs, got {len(rows)}")

    start = scan_start or DEVELOPMENT_START
    end = scan_end or DEVELOPMENT_END
    guard_partition_iterable(("DISCOVERY", "VALIDATION"), context="atomic_replay")

    if bars_by_tf is None:
        service = make_bar_service()
        bars_by_tf = {}
        for tf in SEARCH_TFS:
            bars_by_tf[tf] = _load_bars(service, tf, start, end, warmup_bars=500)

    start_iso = start.isoformat()
    end_iso = end.isoformat()
    sample_cache: dict[tuple, Any] = {}
    inverse_threshold_cache: dict[tuple, Any] = {}

    streams: dict[str, dict[str, Any]] = {}
    if resume:
        streams = load_atomic_checkpoint(artifact_root=root)
        if streams:
            print(
                f"[composite-atomic] resume: loaded {len(streams)}/{len(rows)} cached streams",
                flush=True,
            )

    index_by_id: dict[str, dict[str, Any]] = {}
    row_by_id = {r["candidate_id"]: r for r in rows}
    for cid, rec in streams.items():
        src = row_by_id.get(cid, {})
        index_by_id[cid] = {
            "candidate_id": cid,
            "decision_tf": rec.get("decision_tf"),
            "direction": rec.get("direction"),
            "family": src.get("family"),
            "n_signals": rec.get("n_signals"),
            "stream_hash": rec.get("stream_hash"),
            "is_reference": bool(src.get("is_reference", False)),
        }

    def _commit(cid: str, rec: dict[str, Any], row: dict[str, Any]) -> int:
        streams[cid] = rec
        index_by_id[cid] = {
            "candidate_id": cid,
            "decision_tf": row["decision_tf"],
            "direction": row["direction"],
            "family": row["family"],
            "n_signals": rec["n_signals"],
            "stream_hash": rec["stream_hash"],
            "is_reference": bool(row.get("is_reference", False)),
        }
        done_n = len(streams)
        if done_n % CHECKPOINT_EVERY == 0 or done_n == len(rows):
            save_atomic_checkpoint(
                streams,
                artifact_root=root,
                completed=done_n,
                total=len(rows),
                last_candidate_id=cid,
                start_iso=start_iso,
                end_iso=end_iso,
            )
        if done_n % 50 == 0 or done_n == len(rows):
            print(f"[composite-atomic] replayed {done_n}/{len(rows)}", flush=True)
        return done_n

    pending = [row for row in rows if row["candidate_id"] not in streams]
    workers = atomic_replay_workers()
    use_pool = workers > 1 and bool(pending) and sys.platform.startswith("linux")

    if use_pool:
        # Fork inherits bars_by_tf (CoW) — N cores without multi-GB pickle of bars.
        global _WORKER_BARS_BY_TF, _WORKER_START_ISO, _WORKER_END_ISO
        _WORKER_BARS_BY_TF = bars_by_tf
        _WORKER_START_ISO = start_iso
        _WORKER_END_ISO = end_iso
        print(
            f"[composite-atomic] parallel workers={workers} pending={len(pending)}/{len(rows)}",
            flush=True,
        )
        ctx = mp.get_context("fork")
        with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as pool:
            futures = [pool.submit(_worker_replay_row, row) for row in pending]
            for fut in as_completed(futures):
                cid, rec, row = fut.result()
                _commit(cid, rec, row)
        _WORKER_BARS_BY_TF = None
    else:
        if workers > 1 and not sys.platform.startswith("linux"):
            print(
                f"[composite-atomic] ATOMIC_REPLAY_WORKERS={workers} ignored "
                f"(fork parallelism is Linux-only); running sequential",
                flush=True,
            )
        for row in pending:
            cid = row["candidate_id"]
            tf = row["decision_tf"]
            sigs = generate_signals_for_row(
                bars_by_tf[tf],
                row,
                scan_start_iso=start_iso,
                scan_end_iso=end_iso,
                sample_cache=sample_cache,
                inverse_threshold_cache=inverse_threshold_cache,
            )
            rec = signals_to_stream_record(
                sigs,
                candidate_id=cid,
                tf=tf,
                direction=row["direction"],
            )
            _commit(cid, rec, row)

    # Preserve bank order in final index.
    index_rows = [index_by_id[r["candidate_id"]] for r in rows if r["candidate_id"] in index_by_id]

    cache_path = root / FINAL_CACHE_PKL
    _atomic_pickle_dump(cache_path, streams)
    index = {
        "artifact": "atomic_streams_index_v1",
        "n_streams": len(streams),
        "ATOMIC_INDICATOR_RECOMPUTE_PER_COMPOSITE": ATOMIC_INDICATOR_RECOMPUTE_PER_COMPOSITE,
        "development_start": start_iso,
        "development_end": end_iso,
        "streams": index_rows,
        "resumed_from_checkpoint": resume,
    }
    _atomic_json_dump(root / "atomic_streams_index_v1.json", index)
    save_atomic_checkpoint(
        streams,
        artifact_root=root,
        completed=len(rows),
        total=len(rows),
        last_candidate_id=rows[-1]["candidate_id"] if rows else "",
        start_iso=start_iso,
        end_iso=end_iso,
    )

    return {"streams": streams, "index": index, "bars_by_tf": bars_by_tf, "configs": rows}


def load_stream_cache(*, artifact_root: Path | None = None) -> dict[str, dict[str, Any]]:
    root = artifact_root or ARTIFACT_ROOT
    path = root / FINAL_CACHE_PKL
    if path.exists():
        with path.open("rb") as fh:
            return pickle.load(fh)
    # Resume mid-run cache if final not written yet.
    return load_atomic_checkpoint(artifact_root=root)


def run_validation_parity(
    streams: dict[str, dict[str, Any]],
    configs: list[dict[str, Any]],
    events: pd.DataFrame,
    *,
    bars_by_tf: dict[str, list] | None = None,
    artifact_root: Path | None = None,
    parent_root: Path | None = None,
    precision_tol: float = 1e-9,
) -> dict[str, Any]:
    """
    Recompute metrics on Validation window only; compare to parent validation_stability_v1.csv
    for the 582 atomic IDs. TOTAL_SIGNALS exact; PRECISION abs diff <= 1e-9 or both None.
    """
    root = artifact_root or ARTIFACT_ROOT
    parent = parent_root or PARENT_ARTIFACT_ROOT
    assert_events_exclude_oos(events, context="validation_parity")

    parent_csv = parent / "validation_stability_v1.csv"
    parent_df = pd.read_csv(parent_csv)
    parent_map = {str(r["candidate_id"]): r for _, r in parent_df.iterrows()}

    fs, fe = VALIDATION_PARITY_START, VALIDATION_PARITY_END
    comparisons: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for row in configs:
        cid = row["candidate_id"]
        stream = streams[cid]
        sigs = stream.get("events") or []
        # Restrict to validation window for parity evaluation.
        bounded = [
            s
            for s in sigs
            if fs <= parse_ts(s["available_at"]) < fe
        ]
        # Rebuild emit-compatible dicts.
        signal_dicts = [
            {
                "candidate_id": cid,
                "signal_id": f"{cid}|{s['available_at']}",
                "signal_time": s["signal_time"],
                "signal_price": s.get("signal_price") or 0.0,
                "signal_direction": s.get("signal_direction", row["direction"]),
                "decision_tf": row["decision_tf"],
                "calculated_at": s.get("calculated_at", s["available_at"]),
                "available_at": s["available_at"],
            }
            for s in bounded
        ]
        bars = None if bars_by_tf is None else bars_by_tf.get(row["decision_tf"])
        m = evaluate_signals_window(
            signal_dicts,
            events,
            candidate_id=cid,
            decision_tf=row["decision_tf"],
            direction=row["direction"],
            family=row["family"],
            start=fs,
            end=fe,
            bars=bars,
            parameter_set_id=row.get("parameter_set_id", ""),
            event_primitive=row.get("event_primitive", ""),
            is_reference=bool(row.get("is_reference", False)),
        )
        pref = parent_map.get(cid)
        if pref is None:
            failures.append({"candidate_id": cid, "reason": "missing_in_parent_validation_stability"})
            continue
        parent_n = int(pref["TOTAL_SIGNALS"]) if pd.notna(pref["TOTAL_SIGNALS"]) else 0
        replay_n = int(m.get("TOTAL_SIGNALS") or 0)
        parent_p = None if pd.isna(pref["PRECISION"]) else float(pref["PRECISION"])
        replay_p = m.get("PRECISION")
        signals_ok = parent_n == replay_n
        if parent_p is None and replay_p is None:
            precision_ok = True
            pdiff = None
        elif parent_p is None or replay_p is None:
            precision_ok = False
            pdiff = None
        else:
            pdiff = abs(float(replay_p) - float(parent_p))
            precision_ok = pdiff <= precision_tol
        row_cmp = {
            "candidate_id": cid,
            "parent_TOTAL_SIGNALS": parent_n,
            "replay_TOTAL_SIGNALS": replay_n,
            "parent_PRECISION": parent_p,
            "replay_PRECISION": replay_p,
            "precision_abs_diff": pdiff,
            "signals_match": signals_ok,
            "precision_match": precision_ok,
        }
        comparisons.append(row_cmp)
        if not (signals_ok and precision_ok):
            failures.append(row_cmp)

    status = "PASS" if not failures else "FAIL"
    report = {
        "artifact": "atomic_validation_parity_v1",
        "status": status,
        "n_compared": len(comparisons),
        "n_failures": len(failures),
        "precision_tol": precision_tol,
        "parity_window": [fs.isoformat(), fe.isoformat()],
        "failures": failures[:50],
        "comparisons_sample": comparisons[:5],
    }
    (root / "atomic_validation_parity_v1.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if status != "PASS":
        raise RuntimeError(
            f"ATOMIC_VALIDATION_REPLAY_PARITY_REQUIRED failed: {len(failures)} mismatches "
            f"(see atomic_validation_parity_v1.json)"
        )
    return report


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    u = a | b
    if not u:
        return 1.0
    return len(a & b) / len(u)


def exact_duplicate_clusters(
    configs: list[dict[str, Any]],
    streams: dict[str, dict[str, Any]],
) -> tuple[pd.DataFrame, dict[str, str]]:
    """
    Exact duplicate clusters by stream_hash.
    Retain reference if present else lexicographically smallest candidate_id.
    Returns (cluster_df, mapping discarded_id -> retained_id).
    """
    by_hash: dict[str, list[str]] = defaultdict(list)
    meta = {c["candidate_id"]: c for c in configs}
    for c in configs:
        cid = c["candidate_id"]
        by_hash[streams[cid]["stream_hash"]].append(cid)

    cluster_rows: list[dict[str, Any]] = []
    replace_map: dict[str, str] = {}
    cluster_id = 0
    for h, members in sorted(by_hash.items(), key=lambda kv: min(kv[1])):
        if len(members) < 2:
            continue
        refs = [m for m in members if meta[m].get("is_reference")]
        if refs:
            retained = sorted(refs)[0]
        else:
            retained = sorted(members)[0]
        for m in members:
            if m != retained:
                replace_map[m] = retained
        cluster_rows.append(
            {
                "cluster_id": cluster_id,
                "stream_hash": h,
                "size": len(members),
                "retained_candidate_id": retained,
                "members": "|".join(sorted(members)),
                "decision_tf": meta[retained]["decision_tf"],
                "direction": meta[retained]["direction"],
                "family": meta[retained]["family"],
            }
        )
        cluster_id += 1
    return pd.DataFrame(cluster_rows), replace_map


def _redundancy_score(row: dict[str, Any]) -> tuple:
    """
    Primary: min(discovery_precision_delta, validation_precision_delta) — higher better.
    Then higher min(disc,val) EVENT_RECALL if available else signals fields,
    lower max FPR if available, higher signal count, lex id.
    """
    dpd = row.get("discovery_precision_delta")
    vpd = row.get("validation_precision_delta")
    primary = None
    if dpd is not None and vpd is not None:
        primary = min(float(dpd), float(vpd))
    elif dpd is not None:
        primary = float(dpd)
    elif vpd is not None:
        primary = float(vpd)
    else:
        primary = float("-inf")

    disc_rec = row.get("discovery_event_recall")
    val_rec = row.get("validation_event_recall")
    if disc_rec is not None and val_rec is not None:
        recall_key = min(float(disc_rec), float(val_rec))
    else:
        ds = float(row.get("discovery_signals") or 0)
        vs = float(row.get("validation_signals") or 0)
        recall_key = min(ds, vs)

    disc_fpr = row.get("discovery_fpr")
    val_fpr = row.get("validation_fpr")
    if disc_fpr is not None and val_fpr is not None:
        fpr_key = -max(float(disc_fpr), float(val_fpr))  # lower max FPR → higher score
    else:
        fpr_key = 0.0

    sig_count = int(row.get("discovery_signals") or 0) + int(row.get("validation_signals") or 0)
    # Sort key for "better": higher primary, higher recall_key, higher fpr_key, higher sig_count, lower lex id
    return (primary, recall_key, fpr_key, sig_count, -1)  # -1 placeholder; id applied separately


def near_redundancy_representatives(
    configs: list[dict[str, Any]],
    streams: dict[str, dict[str, Any]],
    *,
    exact_replace: dict[str, str],
    jaccard: float = NEAR_REDUNDANCY_JACCARD,
    cap: int = ATOMIC_REPRESENTATIVE_CAP,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """
    Near redundancy Jaccard>=threshold within TF/direction/family on AVAILABLE_AT sets.
    Keep at most `cap` reps (prefer distinct ref + nonref).
    """
    active = [c for c in configs if c["candidate_id"] not in exact_replace]
    meta = {c["candidate_id"]: c for c in active}

    groups: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for c in active:
        groups[(c["decision_tf"], c["direction"], c["family"])].append(c["candidate_id"])

    retained_ids: set[str] = set()
    cluster_rows: list[dict[str, Any]] = []
    cluster_id = 0
    for (tf, direction, family), ids in sorted(groups.items()):
        # REDUNDANCY_BLOCKWISE=YES — only this TF/direction/family block's sets in RAM.
        avail_sets = {
            cid: set(streams[cid].get("available_at") or [])
            for cid in ids
            if cid in streams
        }
        used: set[str] = set()
        for cid in sorted(ids):
            if cid in used:
                continue
            members = [cid]
            used.add(cid)
            for other in sorted(ids):
                if other in used:
                    continue
                if _jaccard(avail_sets.get(cid, set()), avail_sets.get(other, set())) >= jaccard:
                    members.append(other)
                    used.add(other)

            member_rows = [meta[m] for m in members]
            chosen = _pick_representatives(member_rows, cap=cap)
            for r in chosen:
                retained_ids.add(r["candidate_id"])
            if len(members) > 1:
                cluster_rows.append(
                    {
                        "cluster_id": cluster_id,
                        "decision_tf": tf,
                        "direction": direction,
                        "family": family,
                        "size": len(members),
                        "jaccard_threshold": jaccard,
                        "retained_candidate_ids": "|".join(sorted(r["candidate_id"] for r in chosen)),
                        "members": "|".join(sorted(members)),
                    }
                )
                cluster_id += 1
        del avail_sets

    reps = [meta[cid] for cid in sorted(retained_ids)]
    return pd.DataFrame(cluster_rows), reps


def _pick_representatives(member_rows: list[dict[str, Any]], *, cap: int) -> list[dict[str, Any]]:
    refs = [r for r in member_rows if r.get("is_reference")]
    nonrefs = [r for r in member_rows if not r.get("is_reference")]
    chosen: list[dict[str, Any]] = []

    def best_of(rows: list[dict[str, Any]]) -> dict[str, Any]:
        by_score: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
        for r in rows:
            by_score[_redundancy_score(r)[:4]].append(r)
        top = max(by_score.keys())
        return sorted(by_score[top], key=lambda x: x["candidate_id"])[0]

    if refs:
        chosen.append(best_of(refs))
    if len(chosen) < cap and nonrefs:
        # Rank nonrefs by score then lex
        remaining = list(nonrefs)
        while len(chosen) < cap and remaining:
            pick = best_of(remaining)
            chosen.append(pick)
            remaining = [r for r in remaining if r["candidate_id"] != pick["candidate_id"]]
    if not chosen:
        chosen.append(sorted(member_rows, key=lambda r: r["candidate_id"])[0])
    return chosen[:cap]


def write_representative_artifacts(
    configs: list[dict[str, Any]],
    streams: dict[str, dict[str, Any]],
    *,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    root = artifact_root or ARTIFACT_ROOT
    exact_df, exact_replace = exact_duplicate_clusters(configs, streams)
    exact_df.to_csv(root / "atomic_exact_duplicate_clusters_v1.csv", index=False)

    near_df, reps = near_redundancy_representatives(
        configs, streams, exact_replace=exact_replace
    )
    near_df.to_csv(root / "atomic_redundancy_clusters_v1.csv", index=False)

    bank = {
        "artifact": "atomic_representative_bank_v1",
        "source_atomic_bank": "composite_atomic_bank_v1.json",
        "EXACT_DUPLICATE_STREAMS_DEDUPED": "YES",
        "NEAR_REDUNDANCY_JACCARD": NEAR_REDUNDANCY_JACCARD,
        "ATOMIC_REPRESENTATIVE_CAP_PER_TF_DIRECTION_FAMILY": ATOMIC_REPRESENTATIVE_CAP,
        "n_input": len(configs),
        "n_exact_duplicate_discarded": len(exact_replace),
        "n_representatives": len(reps),
        "exact_replace_map": exact_replace,
        "configs": reps,
    }
    (root / "atomic_representative_bank_v1.json").write_text(
        json.dumps(bank, indent=2), encoding="utf-8"
    )
    return bank
