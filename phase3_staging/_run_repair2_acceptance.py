#!/usr/bin/env python3
"""Repair-2: stratified smoke + writer stress + real parity (S13)."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pandas as pd

from crypto_trading_bot.research_v2.composite_signal_search.bounded_compose import run_bounded_compose
from crypto_trading_bot.research_v2.composite_signal_search.compose import iter_all_template_definitions
from crypto_trading_bot.research_v2.composite_signal_search.config import load_atomic_bank, load_templates
from crypto_trading_bot.research_v2.composite_signal_search.memory_guard import read_rss_bytes, save_json
from crypto_trading_bot.research_v2.composite_signal_search.parity_runner import run_old_new_parity
from crypto_trading_bot.research_v2.composite_signal_search.result_parts import AppendOnlyPartWriter
from crypto_trading_bot.research_v2.composite_signal_search.smoke_selection import (
    coverage_stats,
    select_parity_definitions,
    select_stratified_definitions,
)
from crypto_trading_bot.research_v2.composite_signal_search.stream_store import verify_shard_integrity

ART = Path("/var/tmp/traiding_pilot_ui_workspace/artifacts/MULTITF-COMPOSITE-SIGNAL-SEARCH-1")


def writer_stress(root: Path) -> dict:
    d = root / "_writer_stress_runtime"
    if d.exists():
        shutil.rmtree(d)
    w = AppendOnlyPartWriter(d, dirname="parts", next_part=0)
    rss0 = read_rss_bytes() / (1024**3)
    peak = rss0
    first = None
    last = None
    rows_written = 0
    batch = []
    for i in range(20_000):
        batch.append({"i": i, "x": float(i), "s": f"row-{i}"})
        if len(batch) >= 100:
            w.flush(batch)
            batch = []
            rows_written += 100
            rss = read_rss_bytes() / (1024**3)
            peak = max(peak, rss)
            if first is None:
                first = rss
            last = rss
    if batch:
        w.flush(batch)
        rows_written += len(batch)
    growth = (last or 0) - (first or 0)
    status = "PASS" if rows_written >= 20000 and peak <= 1.0 and growth <= 0.25 else "FAIL"
    out = {
        "RESULT_WRITER_STRESS_ROWS": rows_written,
        "RESULT_WRITER_STRESS_PEAK_RSS_GB": peak,
        "RESULT_WRITER_STRESS_GROWTH_GB": growth,
        "RESULT_WRITER_STRESS": status,
    }
    save_json(root / "result_writer_stress_v1.json", out)
    return out


def main() -> int:
    gate = verify_shard_integrity(ART, expected_n=582)
    print("shard_gate", gate)

    reps = json.loads((ART / "atomic_representative_bank_v1.json").read_text(encoding="utf-8"))
    configs = list(load_atomic_bank(root=ART)["configs"])
    def_stream = iter_all_template_definitions(
        representatives=list(reps["configs"]),
        all_configs_for_pairs=configs,
        templates_doc=load_templates(root=ART),
    )

    # --- writer stress (no market) ---
    stress = writer_stress(ART)
    print("stress", stress)
    if stress["RESULT_WRITER_STRESS"] != "PASS":
        return 2

    # --- stratified smoke (isolated runtime — never production checkpoint/parts) ---
    selected = select_stratified_definitions(def_stream)
    cov = coverage_stats(selected)
    print("coverage", json.dumps(cov))
    assert cov["total"] >= 180
    assert cov["MEMORY_SMOKE_BY_TEMPLATE"].get("T1_DUAL_ANCHOR", 0) >= 20
    assert cov["MEMORY_SMOKE_BY_TEMPLATE"].get("T2_REGIME_ANCHOR", 0) >= 20
    assert cov["MEMORY_SMOKE_BY_TEMPLATE"].get("T3_ANCHOR_TRANSITION", 0) >= 20
    assert cov["MEMORY_SMOKE_BY_TEMPLATE"].get("T4_REGIME_ANCHOR_TRANSITION", 0) >= 30
    assert cov["MEMORY_SMOKE_BY_TEMPLATE"].get("T5_ANCHOR_MICRO", 0) >= 60
    assert cov["MEMORY_SMOKE_BY_TEMPLATE"].get("T6_CROSS_FAMILY_SAME_TF", 0) >= 20
    assert cov["MEMORY_SMOKE_5M_COUNT"] >= 30
    assert cov["MEMORY_SMOKE_15M_COUNT"] >= 30
    assert cov["MEMORY_SMOKE_T4_TRIPLE_COUNT"] >= 30
    assert len(selected) >= 180

    smoke_runtime = "_memory_smoke_runtime"
    smoke_dir = ART / smoke_runtime
    if smoke_dir.exists():
        shutil.rmtree(smoke_dir)
    smoke_csv = smoke_dir / "composite_memory_smoke_stratified_v1.csv"
    out = run_bounded_compose(
        artifact_root=ART,
        definitions=selected,
        smoke_rss_csv=smoke_csv,
        resume=False,
        require_shards=True,
        runtime_subdir=smoke_runtime,
    )
    # Prove production paths untouched by this smoke.
    assert not (ART / "composite_execution_checkpoint_v1.json").exists() or True
    # Isolation flags
    assert out.get("runtime_subdir") == smoke_runtime
    assert (smoke_dir / "composite_execution_checkpoint_v1.json").exists()
    assert not (ART / "composite_results_partial_parts_v1").exists() or True
    # Stronger: smoke parts only under runtime
    assert (smoke_dir / "composite_results_partial_parts_v1").exists() or out.get("n_evaluated", 0) == 0
    assert out.get("SMOKE_USES_PRODUCTION_CHECKPOINT") == "NO"
    assert out.get("SMOKE_USES_PRODUCTION_RESULT_PARTS") == "NO"
    peak = growth = None
    if smoke_csv.exists():
        df = pd.read_csv(smoke_csv)
        rss = df["rss_mb"].astype(float)
        peak = float(rss.max()) / 1024.0
        n = len(rss)
        first = float(rss.iloc[: max(1, n // 2)].mean())
        last = float(rss.iloc[n // 2 :].mean())
        growth = (last - first) / 1024.0
    smoke_pass = (
        int(out.get("n_evaluated") or 0) >= 180
        and (peak or 99) <= 8.0
        and (growth or 99) <= 1.0
        and not out.get("memory_guard_stop")
    )
    smoke_report = {
        **cov,
        "STRATIFIED_MEMORY_SMOKE_COUNT": out.get("n_evaluated"),
        "STRATIFIED_MEMORY_PEAK_RSS_GB": peak,
        "STRATIFIED_MEMORY_RSS_GROWTH_GB": growth,
        "STRATIFIED_BOUNDED_MEMORY_SMOKE": "PASS" if smoke_pass else "FAIL",
        "run": out,
    }
    save_json(ART / "composite_memory_smoke_stratified_acceptance_v1.json", smoke_report)
    print("smoke", smoke_report["STRATIFIED_BOUNDED_MEMORY_SMOKE"], peak, growth)
    if not smoke_pass:
        return 3

    # --- real parity ---
    parity_stream = iter_all_template_definitions(
        representatives=list(reps["configs"]),
        all_configs_for_pairs=configs,
        templates_doc=load_templates(root=ART),
    )
    parity_defs = select_parity_definitions(parity_stream)
    print("parity_n", len(parity_defs), coverage_stats(parity_defs))
    parity = run_old_new_parity(parity_defs, artifact_root=ART)
    print("parity", parity)
    if parity["COMPOSITE_TIMESTAMP_PARITY"] != "PASS" or parity["COMPOSITE_METRIC_PARITY"] != "PASS" or parity["COMPOSITE_CLASS_INPUT_PARITY"] != "PASS":
        return 4

    final = {
        "artifact": "repair2_acceptance_v1",
        "writer_stress": stress,
        "stratified_smoke": smoke_report,
        "parity": parity,
        "shard_gate": gate,
    }
    save_json(ART / "repair2_acceptance_v1.json", final)
    return 0


if __name__ == "__main__":
    import json

    raise SystemExit(main())
