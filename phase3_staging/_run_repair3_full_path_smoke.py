#!/usr/bin/env python3
"""Repair-3: build enumeration authority + full-path dry smoke (300) + resume parity."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd

from crypto_trading_bot.research_v2.composite_signal_search.bounded_compose import run_bounded_compose
from crypto_trading_bot.research_v2.composite_signal_search.enumeration_authority import (
    build_enumeration_authority,
)
from crypto_trading_bot.research_v2.composite_signal_search.memory_guard import read_rss_bytes, save_json
from crypto_trading_bot.research_v2.composite_signal_search.stream_store import verify_shard_integrity

ART = Path("/var/tmp/traiding_pilot_ui_workspace/artifacts/MULTITF-COMPOSITE-SIGNAL-SEARCH-1")
RUNTIME = "_full_path_smoke_runtime"
RESULTS = "composite_results_partial_parts_v1"


def _load_result_ids(work: Path) -> list[str]:
    parts = sorted((work / RESULTS).glob("part-*.parquet"))
    ids: list[str] = []
    for p in parts:
        df = pd.read_parquet(p, columns=["composite_id"])
        ids.extend(list(df["composite_id"].astype(str)))
    return ids


def _peak_rss_gb(csv_path: Path) -> float:
    if not csv_path.exists():
        return read_rss_bytes() / (1024**3)
    df = pd.read_csv(csv_path)
    return float(df["rss_mb"].astype(float).max()) / 1024.0


def main() -> int:
    gate = verify_shard_integrity(ART, expected_n=582)
    print("shard_gate", gate)

    enum_auth = build_enumeration_authority(artifact_root=ART, force=True)
    print(
        "enumeration",
        enum_auth["TOTAL_COMPOSITE_CANDIDATE_COUNT"],
        enum_auth["COMPOSITE_ENUMERATION_SHA256"],
    )

    # --- clean 300 ---
    work = ART / RUNTIME
    if work.exists():
        shutil.rmtree(work)
    rss_csv = work / "full_path_smoke_rss_v1.csv"
    clean = run_bounded_compose(
        artifact_root=ART,
        max_candidates=300,
        smoke_rss_csv=rss_csv,
        resume=False,
        require_shards=True,
        runtime_subdir=RUNTIME,
        # NO definitions= override
    )
    assert clean.get("FULL_COMPOSE_DEFINITION_STREAMING") == "YES"
    assert clean.get("ALL_COMPOSITE_DEFINITIONS_IN_RAM") == "NO"
    clean_ids = _load_result_ids(work)
    peak = _peak_rss_gb(rss_csv)
    print("clean300", len(clean_ids), "peak", peak, "guard", clean.get("memory_guard_stop"))
    assert len(clean_ids) == 300
    assert peak <= 3.0
    assert not clean.get("memory_guard_stop")
    # production untouched
    assert not (ART / "composite_execution_checkpoint_v1.json").exists()
    assert not (ART / "composite_results_partial_parts_v1").exists()

    clean_ids_path = work / "clean_300_ids.json"
    save_json(clean_ids_path, {"ids": clean_ids})

    # --- resume 150 -> 300 ---
    # max_candidates counts evaluations in *this process*, not absolute total.
    resume_runtime = "_full_path_smoke_resume_runtime"
    resume_work = ART / resume_runtime
    if resume_work.exists():
        shutil.rmtree(resume_work)
    r1 = run_bounded_compose(
        artifact_root=ART,
        max_candidates=150,
        resume=False,
        require_shards=True,
        runtime_subdir=resume_runtime,
    )
    ids_150 = _load_result_ids(resume_work)
    assert len(ids_150) == 150, len(ids_150)
    assert ids_150 == clean_ids[:150]
    r2 = run_bounded_compose(
        artifact_root=ART,
        max_candidates=150,
        resume=True,
        require_shards=True,
        runtime_subdir=resume_runtime,
    )
    ids_resume = _load_result_ids(resume_work)
    print(
        "resume_ids",
        len(ids_resume),
        "r1_eval",
        r1.get("n_evaluated"),
        "r2_eval",
        r2.get("n_evaluated"),
    )

    assert len(ids_resume) == 300, len(ids_resume)
    no_skip = ids_resume == clean_ids
    no_dup = len(ids_resume) == len(set(ids_resume))
    parity = no_skip and no_dup

    report = {
        "artifact": "repair3_full_path_smoke_v1",
        "FULL_PATH_SMOKE_USES_DEFINITIONS_OVERRIDE": "NO",
        "FULL_PATH_SMOKE_COUNT": len(clean_ids),
        "FULL_PATH_SMOKE_PEAK_RSS_GB": peak,
        "MEMORY_GUARD_STOP": "YES" if clean.get("memory_guard_stop") else "NO",
        "FULL_PATH_RESUME_PARITY": "PASS" if parity else "FAIL",
        "FULL_PATH_NO_SKIPPED_GLOBAL_CANDIDATES": "PASS" if no_skip else "FAIL",
        "FULL_PATH_NO_DUPLICATE_GLOBAL_CANDIDATES": "PASS" if no_dup else "FAIL",
        "FULL_COMPOSE_DEFINITION_STREAMING": clean.get("FULL_COMPOSE_DEFINITION_STREAMING"),
        "ALL_COMPOSITE_DEFINITIONS_IN_RAM": clean.get("ALL_COMPOSITE_DEFINITIONS_IN_RAM"),
        "COMPOSITE_DEFINITION_GENERATOR": clean.get("COMPOSITE_DEFINITION_GENERATOR"),
        "FULL_RUN_COMPLETED_ID_SET_IN_RAM": clean.get("FULL_RUN_COMPLETED_ID_SET_IN_RAM"),
        "FULL_RUN_CHECKPOINT_COMPLETED_ID_LIST": clean.get("FULL_RUN_CHECKPOINT_COMPLETED_ID_LIST"),
        "CHECKPOINT_MEMORY_COMPLEXITY": clean.get("CHECKPOINT_MEMORY_COMPLEXITY"),
        "RESULT_PART_RESUME_CRASH_SAFE": clean.get("RESULT_PART_RESUME_CRASH_SAFE"),
        "GLOBAL_ENUMERATION_AUTHORITY": enum_auth.get("GLOBAL_ENUMERATION_AUTHORITY"),
        "TOTAL_COMPOSITE_CANDIDATE_COUNT": enum_auth.get("TOTAL_COMPOSITE_CANDIDATE_COUNT"),
        "COMPOSITE_ENUMERATION_SHA256": enum_auth.get("COMPOSITE_ENUMERATION_SHA256"),
        "SHARD_CANDIDATE_SET_MATCH": gate.get("SHARD_CANDIDATE_SET_MATCH"),
        "SHARD_UNKNOWN_CANDIDATE_COUNT": gate.get("SHARD_UNKNOWN_CANDIDATE_COUNT"),
        "SHARD_MISSING_CANDIDATE_COUNT": gate.get("SHARD_MISSING_CANDIDATE_COUNT"),
        "SMOKE_USES_PRODUCTION_CHECKPOINT": "NO",
        "SMOKE_USES_PRODUCTION_RESULT_PARTS": "NO",
        "shard_gate": gate,
        "clean_run": {k: clean[k] for k in clean if k != "authorities"},
    }
    save_json(ART / "repair3_full_path_smoke_v1.json", report)
    print(json.dumps({k: report[k] for k in report if k not in {"clean_run", "shard_gate"}}, indent=2))
    if report["FULL_PATH_RESUME_PARITY"] != "PASS":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
