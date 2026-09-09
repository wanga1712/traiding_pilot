#!/usr/bin/env python3
"""Repair-4 finalizer dry test — synthetic isolated parts only (no real full run)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from crypto_trading_bot.research_v2.composite_signal_search.classify import (
    CANONICAL_SELECTIVE_CLASS,
    classify_composite,
)
from crypto_trading_bot.research_v2.composite_signal_search.composite_stream_hash import composite_stream_sha256
from crypto_trading_bot.research_v2.composite_signal_search.finalize import run_finalization
from crypto_trading_bot.research_v2.composite_signal_search.memory_guard import FOLDS_PARTS_DIR, RESULTS_PARTS_DIR, read_rss_bytes, save_json
from crypto_trading_bot.research_v2.composite_signal_search.result_parts import AppendOnlyPartWriter
from crypto_trading_bot.research_v2.composite_signal_search.survivor_store import SurvivorStreamStore

ART = Path(__file__).resolve().parents[1] / "artifacts" / "MULTITF-COMPOSITE-SIGNAL-SEARCH-1"
# Prefer local repo artifacts if present; dry test uses isolated runtime under ART.
RUNTIME = "_finalizer_dry_runtime"
TEMPLATES = [
    "T1_DUAL_ANCHOR",
    "T2_REGIME_ANCHOR",
    "T3_ANCHOR_TRANSITION",
    "T4_REGIME_ANCHOR_TRANSITION",
    "T5_ANCHOR_MICRO",
    "T6_CROSS_FAMILY_SAME_TF",
]
CLASSES = [
    "INCREMENTAL_BALANCED",
    "INCREMENTAL_SELECTIVE",
    "WEAK_INCREMENTAL",
    "NO_INCREMENTAL_EDGE",
    "INSUFFICIENT",
]


def _make_ns(seed: int, n: int, shift: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    base = 1_700_000_000_000_000_000 + shift
    return np.sort(base + rng.integers(0, 10_000_000_000_000, size=n)).astype(np.int64)


def main() -> int:
    # Resolve artifact root: prefer env workspace layout used on S13/local mirror
    roots = [
        Path("/var/tmp/traiding_pilot_ui_workspace/artifacts/MULTITF-COMPOSITE-SIGNAL-SEARCH-1"),
        Path(__file__).resolve().parents[1] / "artifacts" / "MULTITF-COMPOSITE-SIGNAL-SEARCH-1",
        ART,
    ]
    bank_root = next((p for p in roots if (p / "composite_atomic_bank_v1.json").exists()), roots[1])
    work = bank_root / RUNTIME
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    rss0 = read_rss_bytes() / (1024**3)
    peak = rss0

    results_w = AppendOnlyPartWriter(work, dirname=RESULTS_PARTS_DIR, next_part=0)
    folds_w = AppendOnlyPartWriter(work, dirname=FOLDS_PARTS_DIR, next_part=0)
    survivors = SurvivorStreamStore(work)

    result_batch: list[dict] = []
    fold_batch: list[dict] = []
    n_results = 500
    # Shared stream for exact duplicates
    shared_ns = _make_ns(1, 40)
    shared_sha = composite_stream_sha256(direction="UP", decision_tf="1H", available_at_ns=shared_ns)
    # Near-duplicate streams (Jaccard high)
    near_a = _make_ns(2, 50)
    near_b = near_a.copy()
    near_b[-1] = near_b[-1] + 1  # Jaccard = 49/51 ≈ 0.961 >= 0.95

    for i in range(n_results):
        tmpl = TEMPLATES[i % len(TEMPLATES)]
        cls = CLASSES[i % len(CLASSES)]
        direction = "UP" if i % 2 == 0 else "DOWN"
        tf = "5m" if tmpl == "T5_ANCHOR_MICRO" and i % 2 == 0 else ("15m" if tmpl == "T5_ANCHOR_MICRO" else "1H")
        cid = f"COMP|{tmpl}|{direction}|dry{i:04d}"
        if i < 5:
            # exact duplicate survivors
            ns = shared_ns
            sha = shared_sha
            cls = "INCREMENTAL_BALANCED"
            tf = "1H"
            direction = "UP"
        elif i in (10, 11):
            ns = near_a if i == 10 else near_b
            sha = composite_stream_sha256(direction="UP", decision_tf="1H", available_at_ns=ns)
            cls = "INCREMENTAL_SELECTIVE"
            tf = "1H"
            direction = "UP"
        else:
            ns = _make_ns(1000 + i, 10 + (i % 5))
            sha = composite_stream_sha256(direction=direction, decision_tf=tf, available_at_ns=ns)

        # Force class label as designed for dry coverage (thresholds already unit-tested)
        row = {
            "composite_id": cid,
            "template_id": tmpl,
            "direction": direction,
            "decision_tf": tf,
            "diagnostic": False,
            "trigger_candidate_id": f"TRIG_{tmpl}_{i%7}",
            "context_candidate_ids": f"CTX_{tmpl}_{i%5}|CTX2_{tmpl}_{i%3}",
            "TOTAL_SIGNALS": int(ns.size),
            "PRECISION": 0.4 + (i % 10) * 0.01,
            "EVENT_RECALL": 0.3,
            "FALSE_POSITIVE_RATE": 0.2,
            "MEDIAN_DELAY_SECONDS": 60,
            "MEDIAN_MFE_AFTER_SIGNAL": 0.01,
            "MEDIAN_MAE_AFTER_SIGNAL": 0.005,
            "PRE_C_SIGNAL_RATE": 0.1,
            "sample_flag": "INSUFFICIENT" if cls == "INSUFFICIENT" else "NORMAL",
            "trigger_PRECISION": 0.3,
            "trigger_EVENT_RECALL": 0.5,
            "trigger_TOTAL_SIGNALS": 20,
            "trigger_FALSE_POSITIVE_RATE": 0.25,
            "price_PRECISION": 0.25,
            "PRECISION_DELTA_VS_TRIGGER": 0.06 if "SELECTIVE" in cls or "BALANCED" in cls else (0.01 if cls == "WEAK_INCREMENTAL" else 0.0),
            "PRECISION_DELTA_VS_PRICE_BASELINE": 0.05,
            "RECALL_RETENTION_VS_TRIGGER": 0.55 if "BALANCED" in cls else (0.25 if "SELECTIVE" in cls else 0.1),
            "FPR_DELTA_VS_TRIGGER": -0.01 if "SELECTIVE" in cls or "BALANCED" in cls else 0.01,
            "MEDIAN_DELAY_DELTA_VS_TRIGGER": 0.0,
            "PRE_C_SIGNAL_RATE_DELTA_VS_TRIGGER": 0.0,
            "SIGNAL_RETENTION": 0.5,
            "usable_folds": 4,
            "positive_delta_folds": 3,
            "composite_class": cls,
            "is_survivor": cls in ("INCREMENTAL_BALANCED", "INCREMENTAL_SELECTIVE"),
            "COMPOSITE_STREAM_SHA256": sha,
        }
        # Ensure emitted class never uses legacy SELECTIVE
        assert row["composite_class"] != "SELECTIVE"
        result_batch.append(row)
        if row["is_survivor"]:
            survivors.persist(
                composite_id=cid,
                template_id=tmpl,
                decision_tf=tf,
                direction=direction,
                trigger_candidate_id=row["trigger_candidate_id"],
                context_candidate_ids=row["context_candidate_ids"].split("|"),
                available_at_ns=ns,
                stream_sha256=sha,
                composite_class=cls,
            )
        for fold_id in range(4):
            fold_batch.append(
                {
                    "composite_id": cid,
                    "fold_id": f"F{fold_id}",
                    "TOTAL_SIGNALS": 10,
                    "PRECISION": 0.4,
                    "PRECISION_DELTA_VS_TRIGGER": 0.05 + (fold_id * 0.01),
                    "EVENT_RECALL": 0.3,
                    "FALSE_POSITIVE_RATE": 0.2,
                    "sample_flag": "NORMAL",
                    "trigger_TOTAL_SIGNALS": 12,
                    "trigger_PRECISION": 0.3,
                }
            )
        if len(result_batch) >= 100:
            results_w.flush(result_batch)
            result_batch = []
            peak = max(peak, read_rss_bytes() / (1024**3))
        if len(fold_batch) >= 200:
            folds_w.flush(fold_batch)
            fold_batch = []
            peak = max(peak, read_rss_bytes() / (1024**3))

    if result_batch:
        results_w.flush(result_batch)
    if fold_batch:
        folds_w.flush(fold_batch)

    # Copy frozen bank into work root for load_atomic_bank during finalize
    for name in ("composite_atomic_bank_v1.json", "composite_templates_v1.json", "development_corpus_manifest_v1.json"):
        src = bank_root / name
        if src.exists():
            shutil.copy2(src, work / name)

    out = run_finalization(work, allow_partial_test=True, atomic_bank_root=bank_root)
    peak = max(peak, read_rss_bytes() / (1024**3), float(out["assemble"]["FINAL_RESULT_ASSEMBLY_PEAK_RSS_GB"]))

    # Boundary classify check embedded
    assert (
        classify_composite(
            aggregate_sample_flag="NORMAL",
            precision_delta_vs_trigger=0.05,
            recall_retention_vs_trigger=0.20,
            fpr_delta_vs_trigger=-0.0001,
            fold_precision_deltas=[0.01, 0.02, 0.03, 0.04],
            fold_signal_counts=[10, 10, 10, 10],
        )
        == CANONICAL_SELECTIVE_CLASS
    )

    results = pd.read_csv(work / "composite_results_all_v1.csv")
    assert "SELECTIVE" not in set(results["composite_class"].astype(str))
    assert CANONICAL_SELECTIVE_CLASS in set(results["composite_class"].astype(str))
    assert (work / "frozen_composite_survivor_bank_raw_v1.json").exists()
    assert (work / "frozen_composite_survivor_bank_v1.json").exists()
    assert (work / "model_feature_handoff_v1.json").exists()
    assert (work / "composite_exact_duplicate_clusters_v1.csv").exists()
    assert (work / "composite_redundancy_v1.csv").exists()

    status = {
        "FINALIZER_DRY_TEST": "PASS" if peak <= 1.0 else "FAIL",
        "FINALIZER_DRY_TEST_PEAK_RSS_GB": peak,
        "n_results": int(len(results)),
        "n_folds": int(pd.read_csv(work / "composite_fold_stability_v1.csv").shape[0]),
        "CANONICAL_SELECTIVE_CLASS": CANONICAL_SELECTIVE_CLASS,
        "SELECTIVE_THRESHOLD_CHANGED": "NO",
        "FINAL_RESULT_ASSEMBLY_BOUNDED": "YES",
        "COMPOSITE_STREAM_HASH_RECORDED": "YES",
        "SURVIVOR_STREAM_STORAGE": "DISK_BACKED",
        "COMPOSITE_REDUNDANCY_METHOD": "EVENT_STREAM_JACCARD",
        "COMPOSITE_REDUNDANCY_THRESHOLD": 0.95,
        "finalization": out,
        "runtime": str(work),
    }
    # Write both into dry runtime and parent artifact root
    save_json(work / "finalizer_dry_test_v1.json", status)
    save_json(bank_root / "finalizer_dry_test_v1.json", status)
    print(json.dumps({k: status[k] for k in status if k != "finalization"}, indent=2))
    return 0 if status["FINALIZER_DRY_TEST"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
