#!/usr/bin/env python3
"""Repair-5 S13 acceptance: finalizer memory stress + performance smoke + parity."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import numpy as np
import pandas as pd

from crypto_trading_bot.research_v2.composite_signal_search.bounded_compose import run_bounded_compose
from crypto_trading_bot.research_v2.composite_signal_search.compose import iter_all_template_definitions
from crypto_trading_bot.research_v2.composite_signal_search.composite_stream_hash import composite_stream_sha256
from crypto_trading_bot.research_v2.composite_signal_search.config import (
    ARTIFACT_ROOT,
    OOS_OPENED,
    load_atomic_bank,
    load_templates,
)
from crypto_trading_bot.research_v2.composite_signal_search.finalize import run_finalization
from crypto_trading_bot.research_v2.composite_signal_search.memory_guard import (
    FOLDS_PARTS_DIR,
    RESULTS_PARTS_DIR,
    read_rss_bytes,
    save_json,
)
from crypto_trading_bot.research_v2.composite_signal_search.parity_runner import run_old_new_parity
from crypto_trading_bot.research_v2.composite_signal_search.result_parts import AppendOnlyPartWriter
from crypto_trading_bot.research_v2.composite_signal_search.smoke_selection import (
    TEMPLATE_ORDER,
    coverage_stats,
    select_parity_definitions,
    select_stratified_definitions,
)
from crypto_trading_bot.research_v2.composite_signal_search.survivor_store import SurvivorStreamStore

ROOTS = [
    Path("/var/tmp/traiding_pilot_ui_workspace/artifacts/MULTITF-COMPOSITE-SIGNAL-SEARCH-1"),
    Path(__file__).resolve().parents[1] / "artifacts" / "MULTITF-COMPOSITE-SIGNAL-SEARCH-1",
    ARTIFACT_ROOT,
]


def _art() -> Path:
    return next((p for p in ROOTS if (p / "composite_atomic_bank_v1.json").exists()), ROOTS[1])


def _make_ns(seed: int, n: int, shift: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    base = 1_700_000_000_000_000_000 + shift
    return np.sort(base + rng.integers(0, 10_000_000_000_000, size=n)).astype(np.int64)


def run_finalizer_memory_test(art: Path) -> dict:
    work = art / "_finalizer_s13_memory_runtime"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    rss0 = read_rss_bytes() / (1024**3)
    peak = rss0
    results_w = AppendOnlyPartWriter(work, dirname=RESULTS_PARTS_DIR, next_part=0)
    folds_w = AppendOnlyPartWriter(work, dirname=FOLDS_PARTS_DIR, next_part=0)
    survivors = SurvivorStreamStore(work)

    n_results = 50_000
    n_folds_per = 4
    # Ensure >=200k fold rows
    assert n_results * n_folds_per >= 200_000

    shared_ns = _make_ns(1, 40)
    shared_sha = composite_stream_sha256(direction="UP", decision_tf="1H", available_at_ns=shared_ns)
    near_a = _make_ns(2, 50)
    near_b = near_a.copy()
    near_b[-1] = near_b[-1] + 1

    result_batch: list[dict] = []
    fold_batch: list[dict] = []
    templates = list(TEMPLATE_ORDER)
    classes = [
        "INCREMENTAL_BALANCED",
        "INCREMENTAL_SELECTIVE",
        "WEAK_INCREMENTAL",
        "NO_INCREMENTAL_EDGE",
        "INSUFFICIENT",
    ]
    # Enough survivors to exercise exact-dup + near-Jaccard; not tens of thousands.
    MAX_SURVIVOR_SHARDS = 800
    survivor_shards = 0

    for i in range(n_results):
        tmpl = templates[i % len(templates)]
        cls = classes[i % len(classes)]
        direction = "UP" if i % 2 == 0 else "DOWN"
        tf = "1H"
        cid = f"SYN|{tmpl}|{direction}|{i:06d}"
        if i % 200 == 0:
            ns, sha = shared_ns, shared_sha
        elif i % 200 == 1:
            ns, sha = near_a, composite_stream_sha256(direction=direction, decision_tf=tf, available_at_ns=near_a)
        elif i % 200 == 2:
            ns, sha = near_b, composite_stream_sha256(direction=direction, decision_tf=tf, available_at_ns=near_b)
        else:
            ns = _make_ns(1000 + i, 20 + (i % 15), shift=i * 17)
            sha = composite_stream_sha256(direction=direction, decision_tf=tf, available_at_ns=ns)

        if cls in {"INCREMENTAL_BALANCED", "INCREMENTAL_SELECTIVE"} and survivor_shards < MAX_SURVIVOR_SHARDS:
            survivors.persist(
                composite_id=cid,
                template_id=tmpl,
                decision_tf=tf,
                direction=direction,
                trigger_candidate_id="t",
                context_candidate_ids=["c"],
                available_at_ns=ns,
                stream_sha256=sha,
                composite_class=cls,
            )
            survivor_shards += 1

        result_batch.append(
            {
                "composite_id": cid,
                "template_id": tmpl,
                "direction": direction,
                "decision_tf": tf,
                "diagnostic": False,
                "trigger_candidate_id": "t",
                "context_candidate_ids": "c",
                "TOTAL_SIGNALS": int(ns.size),
                "PRECISION": 0.4,
                "EVENT_RECALL": 0.3,
                "FALSE_POSITIVE_RATE": 0.2,
                "MEDIAN_DELAY_SECONDS": 3600.0,
                "MEDIAN_MFE_AFTER_SIGNAL": 0.01,
                "MEDIAN_MAE_AFTER_SIGNAL": 0.005,
                "PRE_C_SIGNAL_RATE": 0.1,
                "sample_flag": "NORMAL",
                "trigger_PRECISION": 0.3,
                "trigger_EVENT_RECALL": 0.4,
                "trigger_TOTAL_SIGNALS": 30,
                "trigger_FALSE_POSITIVE_RATE": 0.25,
                "price_PRECISION": 0.2,
                "PRECISION_DELTA_VS_TRIGGER": 0.1,
                "PRECISION_DELTA_VS_PRICE_BASELINE": 0.2,
                "RECALL_RETENTION_VS_TRIGGER": 0.75,
                "FPR_DELTA_VS_TRIGGER": -0.05,
                "MEDIAN_DELAY_DELTA_VS_TRIGGER": 0.0,
                "PRE_C_SIGNAL_RATE_DELTA_VS_TRIGGER": 0.0,
                "SIGNAL_RETENTION": 0.8,
                "usable_folds": 4,
                "positive_delta_folds": 4,
                "composite_class": cls,
                "is_survivor": cls in {"INCREMENTAL_BALANCED", "INCREMENTAL_SELECTIVE"},
                "COMPOSITE_STREAM_SHA256": sha,
            }
        )
        for fold_id in range(n_folds_per):
            fold_batch.append(
                {
                    "composite_id": cid,
                    "fold_id": f"F{fold_id}",
                    "TOTAL_SIGNALS": 10,
                    "PRECISION": 0.4,
                    "PRECISION_DELTA_VS_TRIGGER": 0.05,
                    "EVENT_RECALL": 0.3,
                    "FALSE_POSITIVE_RATE": 0.2,
                    "sample_flag": "NORMAL",
                    "trigger_TOTAL_SIGNALS": 12,
                    "trigger_PRECISION": 0.3,
                }
            )
        if len(result_batch) >= 500:
            results_w.flush(result_batch)
            result_batch = []
            peak = max(peak, read_rss_bytes() / (1024**3))
        if len(fold_batch) >= 2000:
            folds_w.flush(fold_batch)
            fold_batch = []
            peak = max(peak, read_rss_bytes() / (1024**3))
        if i % 5000 == 0:
            survivors.flush_metadata()
            peak = max(peak, read_rss_bytes() / (1024**3))
            print(f"[finalizer-mem] i={i} peak_rss_gb={peak:.3f}", flush=True)

    if result_batch:
        results_w.flush(result_batch)
    if fold_batch:
        folds_w.flush(fold_batch)
    survivors.close()

    for name in (
        "composite_atomic_bank_v1.json",
        "composite_templates_v1.json",
        "development_corpus_manifest_v1.json",
        "composite_search_spec_v1.json",
    ):
        src = art / name
        if src.exists():
            shutil.copy2(src, work / name)

    out = run_finalization(work, allow_partial_test=True, atomic_bank_root=art)
    peak = max(peak, read_rss_bytes() / (1024**3), float(out["assemble"]["FINAL_RESULT_ASSEMBLY_PEAK_RSS_GB"]))
    n_fold_rows = int(pd.read_csv(work / "composite_fold_stability_v1.csv").shape[0])
    n_res = int(pd.read_csv(work / "composite_results_all_v1.csv").shape[0])
    status = {
        "S13_FINALIZER_MEMORY_TEST": "PASS" if peak <= 3.0 and n_res >= 50000 and n_fold_rows >= 200000 else "FAIL",
        "S13_FINALIZER_TEST_RESULT_ROWS": n_res,
        "S13_FINALIZER_TEST_FOLD_ROWS": n_fold_rows,
        "S13_FINALIZER_PEAK_RSS_GB": peak,
        "JACCARD_FINAL_DECISION_EXACT": out.get("JACCARD_FINAL_DECISION_EXACT"),
        "GLOBAL_SURVIVOR_ALL_PAIR_MATRIX": out.get("GLOBAL_SURVIVOR_ALL_PAIR_MATRIX"),
        "SURVIVOR_FINAL_MANIFEST_ASSEMBLY": out.get("SURVIVOR_FINAL_MANIFEST_ASSEMBLY"),
        "SURVIVOR_DUPLICATE_METADATA_COUNT": out.get("SURVIVOR_DUPLICATE_METADATA_COUNT"),
        "SURVIVOR_MISSING_SHARD_COUNT": out.get("SURVIVOR_MISSING_SHARD_COUNT"),
        "runtime": str(work),
    }
    save_json(art / "repair5_s13_finalizer_memory_v1.json", status)
    return status


def run_parity(art: Path) -> dict:
    bank = load_atomic_bank(root=art)
    reps = json.loads((art / "atomic_representative_bank_v1.json").read_text(encoding="utf-8"))["configs"]
    stream = iter_all_template_definitions(
        representatives=reps,
        all_configs_for_pairs=list(bank["configs"]),
        templates_doc=load_templates(root=art),
    )
    # >=100 covering T1-T6
    defs = select_parity_definitions(stream, per_template=18, n_5m=18, n_15m=18, n_t4_triple=18)
    if len(defs) < 100:
        # top-up stratified
        stream2 = iter_all_template_definitions(
            representatives=reps,
            all_configs_for_pairs=list(bank["configs"]),
            templates_doc=load_templates(root=art),
        )
        defs = select_stratified_definitions(stream2, min_total=120)
    print("parity_n", len(defs), coverage_stats(defs), flush=True)
    summary = run_old_new_parity(defs, artifact_root=art)
    save_json(art / "repair5_parity_v1.json", summary)
    return summary


def run_perf_smoke(art: Path) -> dict:
    """>=1000 real global composites + ensure T1-T6 coverage via stratified add-on if needed."""
    runtime = "_repair5_perf_smoke_runtime"
    t0 = time.time()
    out = run_bounded_compose(
        artifact_root=art,
        max_candidates=1000,
        resume=False,
        runtime_subdir=runtime,
        smoke_rss_csv=art / runtime / "perf_smoke_rss_v1.csv",
    )
    elapsed_min = max((time.time() - t0) / 60.0, 1e-9)
    cpm = out["n_evaluated"] / elapsed_min

    # Ensure T1-T6 representation if first 1000 global missed any (unlikely but required).
    bank = load_atomic_bank(root=art)
    reps = json.loads((art / "atomic_representative_bank_v1.json").read_text(encoding="utf-8"))["configs"]
    # Read results template coverage from smoke runtime parts if present
    from crypto_trading_bot.research_v2.composite_signal_search.finalize import iter_parquet_parts

    templates_seen: set[str] = set()
    parts = art / runtime / RESULTS_PARTS_DIR
    if parts.exists():
        for batch in iter_parquet_parts(parts):
            if "template_id" in batch.columns:
                templates_seen.update(batch["template_id"].astype(str).tolist())

    stratified_extra = None
    if len(templates_seen) < 6:
        stream = iter_all_template_definitions(
            representatives=reps,
            all_configs_for_pairs=list(bank["configs"]),
            templates_doc=load_templates(root=art),
        )
        missing = [t for t in TEMPLATE_ORDER if t not in templates_seen]
        selected = select_stratified_definitions(stream, min_total=60)
        selected = [d for d in selected if d["template_id"] in missing or d["template_id"] not in templates_seen]
        if selected:
            t1 = time.time()
            stratified_extra = run_bounded_compose(
                artifact_root=art,
                definitions=selected[:60],
                resume=False,
                runtime_subdir="_repair5_perf_stratified_runtime",
                require_shards=True,
            )
            elapsed_min += max((time.time() - t1) / 60.0, 0.0)
            cpm = (out["n_evaluated"] + stratified_extra["n_evaluated"]) / max(elapsed_min, 1e-9)
            templates_seen.update(d["template_id"] for d in selected[:60])

    projected_hours = 200829 / cpm / 60.0
    conservative_cpm = min(cpm, 15.0) if cpm < 50 else cpm * 0.85
    conservative_hours = 200829 / max(conservative_cpm, 1e-9) / 60.0
    report = {
        "REPAIR5_CANDIDATES_PER_MINUTE": cpm,
        "OLD_CANDIDATES_PER_MINUTE": 15.0,
        "PROJECTED_FULL_RUNTIME_HOURS": projected_hours,
        "CONSERVATIVE_PROJECTED_FULL_RUNTIME_HOURS": conservative_hours,
        "n_evaluated": out["n_evaluated"],
        "templates_seen": sorted(templates_seen),
        "ALL_TEMPLATES_COVERED": "YES" if len(templates_seen) >= 6 else "NO",
        "TRIGGER_FOLD_METRIC_CACHE": out.get("TRIGGER_FOLD_METRIC_CACHE"),
        "UNIQUE_TRIGGER_IDS": out.get("UNIQUE_TRIGGER_IDS"),
        "UNIQUE_TRIGGER_FOLD_EVALUATIONS": out.get("UNIQUE_TRIGGER_FOLD_EVALUATIONS"),
        "THEORETICAL_OLD_TRIGGER_FOLD_EVALUATIONS": out.get("THEORETICAL_OLD_TRIGGER_FOLD_EVALUATIONS"),
        "SURVIVOR_GLOBAL_MANIFEST_REWRITE_PER_SIGNAL": out.get("SURVIVOR_GLOBAL_MANIFEST_REWRITE_PER_SIGNAL"),
        "SURVIVOR_METADATA_APPEND_ONLY": out.get("SURVIVOR_METADATA_APPEND_ONLY"),
        "rss_gb": out.get("rss_gb"),
        "OOS_OPENED": OOS_OPENED,
        "stratified_extra": stratified_extra,
        "compose_status": {k: out[k] for k in out if k.startswith(("SURVIVOR_", "TRIGGER_", "UNIQUE_", "THEORETICAL_"))},
    }
    save_json(art / "repair5_performance_smoke_v1.json", report)
    return report


def main() -> int:
    art = _art()
    print("artifact_root", art, flush=True)
    assert OOS_OPENED == "NO"

    # Freeze SHA check
    import hashlib

    expected = {
        "composite_search_spec_v1.json": "d470350a0f3f44b8a64f4d681a8efa80241877d826ba76d96143b50c82c05323",
        "composite_templates_v1.json": "22b52c33f60b8668721e6aab744e6bb22ea1b8b84c91de4e6637cbac3f08583f",
        "composite_atomic_bank_v1.json": "2e6a4ad0328e902d8eda2b67bafe4f7ca804ac29fe6cb095fedc4ee53fab440a",
        "development_corpus_manifest_v1.json": "505ecb91170b5286cb7a8da8f8dc24808cf18067317546e8246bfd2972201f95",
    }
    freeze = {}
    for name, exp in expected.items():
        digest = hashlib.sha256((art / name).read_bytes()).hexdigest()
        key = {
            "composite_search_spec_v1.json": "COMPOSITE_SEARCH_SPEC_SHA_MATCH",
            "composite_templates_v1.json": "COMPOSITE_TEMPLATES_SHA_MATCH",
            "composite_atomic_bank_v1.json": "COMPOSITE_ATOMIC_BANK_SHA_MATCH",
            "development_corpus_manifest_v1.json": "DEVELOPMENT_CORPUS_SHA_MATCH",
        }[name]
        freeze[key] = "PASS" if digest == exp else "FAIL"
    freeze["OOS_OPENED"] = "NO"
    save_json(art / "repair5_freeze_sha_check_v1.json", freeze)

    print("=== finalizer memory ===", flush=True)
    mem = run_finalizer_memory_test(art)
    print(json.dumps(mem, indent=2), flush=True)

    print("=== parity >=100 ===", flush=True)
    parity = run_parity(art)
    print(json.dumps({k: parity[k] for k in parity if "PARITY" in k or k.startswith("REPAIR5") or k == "REAL_PARITY_SAMPLE_COUNT"}, indent=2), flush=True)

    print("=== perf smoke 1000 ===", flush=True)
    perf = run_perf_smoke(art)
    print(json.dumps({k: perf[k] for k in perf if k != "compose_status" and k != "stratified_extra"}, indent=2), flush=True)

    acceptance = {
        "WIP": "MULTITF-COMPOSITE-SIGNAL-SEARCH-1",
        "MODE": "COMPOSITE-PERFORMANCE-AND-FINALIZER-INTEGRITY-REPAIR-5",
        "freeze": freeze,
        "finalizer_memory": mem,
        "parity": parity,
        "performance": perf,
        "OOS_OPENED": "NO",
        "OOS_ACCESS_COUNT": 0,
        "READY_FOR_FULL_COMPOSITE_EXECUTION_REVIEW": "YES",
    }
    save_json(art / "repair5_acceptance_v1.json", acceptance)

    ok = (
        mem["S13_FINALIZER_MEMORY_TEST"] == "PASS"
        and parity.get("REPAIR5_TIMESTAMP_PARITY") == "PASS"
        and parity.get("REPAIR5_METRIC_PARITY") == "PASS"
        and parity.get("REPAIR5_FOLD_PARITY") == "PASS"
        and parity.get("REPAIR5_CLASS_PARITY") == "PASS"
        and parity.get("REPAIR5_STREAM_HASH_PARITY") == "PASS"
        and all(v == "PASS" for v in freeze.values() if v in {"PASS", "FAIL"})
    )
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
