"""Validate PREDICTOR_CONFLUENCE_ENGINE_V1 and write artifacts."""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from crypto_trading_bot.research_v2.indicator_engine.tests.fixtures import make_bars
from crypto_trading_bot.research_v2.predictor_confluence.engine import compute_predictor_confluence
from crypto_trading_bot.research_v2.predictor_confluence.registry import (
    FEATURE_REGISTRY,
    PARAMETER_REGISTRY,
    SCHEMA_COLUMNS,
)
from crypto_trading_bot.research_v2.predictor_confluence.version import CONFLUENCE_ENGINE_VERSION
import numpy as np


def _run() -> list[dict]:
    import crypto_trading_bot.research_v2.predictor_confluence.tests.test_confluence as t

    cases = [
        ("raw_family_normalized", t.test_raw_and_family_normalized),
        ("cross_tf", t.test_cross_tf_confluence),
        ("temporal", t.test_temporal_fields_present),
        ("future_mutation", t.test_future_mutation),
        ("true_c_outcome_leakage", t.test_true_c_outcome_leakage),
        ("unfinished_htf", t.test_unfinished_htf),
        ("batch_streaming", t.test_batch_streaming),
    ]
    rows = []
    for name, fn in cases:
        try:
            fn()
            rows.append({"test": name, "status": "PASS", "detail": ""})
            print(f"PASS {name}", flush=True)
        except Exception as exc:  # noqa: BLE001
            rows.append({"test": name, "status": "FAIL", "detail": str(exc)})
            print(f"FAIL {name}: {exc}", flush=True)
            traceback.print_exc()
    return rows


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _descriptive_stats(out: Path) -> None:
    closes = [100 + np.sin(i / 6) * 2 + i * 0.04 for i in range(100)]
    bars = make_bars(closes, minutes=60)
    rows = []
    for i in (40, 60, 80, 95):
        decision = bars[i]["close_time"]
        snap = compute_predictor_confluence({"1H": bars}, decision_time=decision, timeframes=["1H"])
        f = snap["within_tf"]["RAW"]["1H"]["features"]
        rows.append(
            {
                "decision_index": i,
                "valid_triggers": f.get("VALID_TRIGGER_COUNT"),
                "cluster_count": f.get("CLUSTER_COUNT"),
                "nearest_cluster_size": f.get("NEAREST_CLUSTER_SIZE"),
                "distinct_families": f.get("DISTINCT_FAMILY_COUNT"),
                "dispersion_pct": f.get("TRIGGER_DISPERSION_PCT"),
                "unsupported_or_intrabar": f.get("REQUIRES_INTRABAR_COUNT", 0) + f.get("UNSUPPORTED_COUNT", 0),
            }
        )
    with (out / "predictor_confluence_descriptive_stats_v1.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "artifacts/PREDICTOR-CONFLUENCE-FEATURES-1")
    out.mkdir(parents=True, exist_ok=True)
    try:
        git_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001
        git_commit = "UNKNOWN"

    results = _run()
    overall = all(r["status"] == "PASS" for r in results)

    # expand feature registry from a live snapshot keys
    closes = [100 + i * 0.1 for i in range(80)]
    bars = make_bars(closes, minutes=60)
    live = compute_predictor_confluence({"1H": bars}, decision_time=bars[-2]["close_time"], timeframes=["1H"])
    feature_keys = sorted(live["within_tf"]["RAW"]["1H"]["features"].keys())
    cross_keys = sorted((live["cross_tf"]["RAW"] or {}).keys())

    with (out / "predictor_confluence_feature_registry_v1.csv").open("w", newline="", encoding="utf-8") as f:
        fields = ["feature_id", "family", "description", "raw_family_normalized", "within_cross_tf", "unit", "causal", "engine_version"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        known = {r["feature_id"]: r for r in FEATURE_REGISTRY}
        for k in feature_keys:
            if k in known:
                w.writerow({fld: known[k].get(fld, "") for fld in fields})
            else:
                w.writerow(
                    {
                        "feature_id": k,
                        "family": "EXTENDED",
                        "description": "auto-registered from engine output",
                        "raw_family_normalized": "BOTH",
                        "within_cross_tf": "WITHIN_TF",
                        "unit": "varies",
                        "causal": "YES",
                        "engine_version": CONFLUENCE_ENGINE_VERSION,
                    }
                )
        for k in cross_keys:
            w.writerow(
                {
                    "feature_id": k,
                    "family": "CROSS_TF",
                    "description": "cross-timeframe confluence",
                    "raw_family_normalized": "BOTH",
                    "within_cross_tf": "CROSS_TF",
                    "unit": "varies",
                    "causal": "YES",
                    "engine_version": CONFLUENCE_ENGINE_VERSION,
                }
            )

    (out / "predictor_confluence_parameter_registry_v1.json").write_text(
        json.dumps(PARAMETER_REGISTRY, indent=2), encoding="utf-8"
    )
    with (out / "predictor_confluence_schema_v1.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["column", "class", "note"])
        for a, b, c in SCHEMA_COLUMNS:
            w.writerow([a, b, c])

    def write_csv(name: str, rows: list[dict]) -> None:
        with (out / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["test", "status", "detail"])
            w.writeheader()
            w.writerows(rows)

    write_csv("predictor_confluence_validation_v1.csv", results)
    anti = [r for r in results if r["test"] in ("future_mutation", "true_c_outcome_leakage", "unfinished_htf")]
    stream = [r for r in results if r["test"] == "batch_streaming"]
    write_csv("predictor_confluence_anti_leakage_validation_v1.csv", anti)
    write_csv("predictor_confluence_streaming_validation_v1.csv", stream)
    _descriptive_stats(out)

    docs = Path(__file__).with_name("docs_predictor_confluence_engine_v1.md")
    if docs.exists():
        shutil.copy(docs, out / "predictor_confluence_engine_v1.md")

    files = [
        "predictor_confluence_feature_registry_v1.csv",
        "predictor_confluence_parameter_registry_v1.json",
        "predictor_confluence_schema_v1.csv",
        "predictor_confluence_validation_v1.csv",
        "predictor_confluence_anti_leakage_validation_v1.csv",
        "predictor_confluence_streaming_validation_v1.csv",
        "predictor_confluence_descriptive_stats_v1.csv",
        "predictor_confluence_engine_v1.md",
    ]
    checksums = {n: _sha(out / n) for n in files if (out / n).exists()}
    feature_count = len(feature_keys) + len(cross_keys)

    manifest = {
        "confluence_engine_version": CONFLUENCE_ENGINE_VERSION,
        "wip": "PREDICTOR-CONFLUENCE-FEATURES-1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit,
        "overall_ok": overall,
        "feature_count": feature_count,
        "parameter_set_count": len(PARAMETER_REGISTRY),
        "clustering_method": "sorted_adjacent_gap_OR_pct_ATR",
        "pct_thresholds": [0.10, 0.25, 0.50, 1.00],
        "atr_thresholds": [0.25, 0.50, 1.00],
        "views": ["RAW", "FAMILY_NORMALIZED"],
        "api": "compute_predictor_confluence",
        "validation_results": results,
        "frozen_inputs": [
            "WAVE_DATASET_V1",
            "REVERSAL_EVENT_DATASET_V1",
            "INDICATOR_ENGINE_V1",
            "VOLUME_ACCUMULATION_ENGINE_V1",
            "INVERSE_PREDICTOR_ENGINE_V1",
        ],
        "checksums_sha256": checksums,
        "notes": ["No WHEN tournament", "No outcome-conditioned ranking", "Descriptive stats only"],
    }
    (out / "predictor_confluence_engine_manifest_v1.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps({"overall_ok": overall, "manifest": manifest}, indent=2), encoding="utf-8")
    print(json.dumps({"overall_ok": overall, "out": str(out), "feature_count": feature_count}, indent=2))
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
