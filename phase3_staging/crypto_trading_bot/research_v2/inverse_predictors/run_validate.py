"""Validate INVERSE_PREDICTOR_ENGINE_V1 and write artifacts."""
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

from crypto_trading_bot.research_v2.inverse_predictors.registry import (
    PARAMETER_REGISTRY,
    PREDICTOR_REGISTRY,
    SCHEMA_COLUMNS,
)
from crypto_trading_bot.research_v2.inverse_predictors.version import PREDICTOR_ENGINE_VERSION


def _run() -> list[dict]:
    import crypto_trading_bot.research_v2.inverse_predictors.tests.test_inverse_predictors as t

    cases = [
        ("dma_analytic_replay", t.test_dma_analytic_and_replay),
        ("rsi_replay", t.test_rsi_replay),
        ("macd_replay", t.test_macd_replay),
        ("stoch_feasibility", t.test_stoch_point_and_kd_limitation),
        ("project_oscillator", t.test_project_oscillator),
        ("bollinger_unsupported", t.test_bollinger_unsupported),
        ("future_mutation", t.test_future_mutation_leakage),
        ("true_c_outcome_leakage", t.test_true_c_outcome_leakage),
        ("unfinished_htf", t.test_unfinished_htf),
        ("batch_streaming", t.test_batch_streaming),
        ("engine_version", t.test_engine_version),
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


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "artifacts/INVERSE-INDICATOR-PREDICTOR-ENGINE-1")
    out.mkdir(parents=True, exist_ok=True)
    try:
        git_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001
        git_commit = "UNKNOWN"

    results = _run()
    overall = all(r["status"] == "PASS" for r in results)

    with (out / "inverse_predictor_registry_v1.csv").open("w", newline="", encoding="utf-8") as f:
        fields = [
            "predictor_id",
            "indicator_family",
            "solution_method",
            "hypothetical_input_type",
            "intrabar_assumption",
            "causal_eligible",
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in PREDICTOR_REGISTRY:
            w.writerow({k: row.get(k, "") for k in fields})

    (out / "inverse_predictor_parameter_registry_v1.json").write_text(
        json.dumps(PARAMETER_REGISTRY, indent=2), encoding="utf-8"
    )

    with (out / "inverse_predictor_schema_v1.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["column", "class", "note"])
        for a, b, c in SCHEMA_COLUMNS:
            w.writerow([a, b, c])

    def write_csv(name: str, rows: list[dict]) -> None:
        with (out / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["test", "status", "detail"])
            w.writeheader()
            w.writerows(rows)

    formula = [r for r in results if r["test"] in ("dma_analytic_replay", "rsi_replay", "macd_replay", "project_oscillator", "stoch_feasibility", "bollinger_unsupported")]
    replay = [r for r in results if "replay" in r["test"] or r["test"] in ("dma_analytic_replay", "rsi_replay", "macd_replay")]
    anti = [r for r in results if r["test"] in ("future_mutation", "true_c_outcome_leakage", "unfinished_htf")]
    stream = [r for r in results if r["test"] == "batch_streaming"]

    write_csv("inverse_predictor_formula_validation_v1.csv", formula)
    write_csv("inverse_predictor_synthetic_replay_validation_v1.csv", replay)
    write_csv("inverse_predictor_anti_leakage_validation_v1.csv", anti)
    write_csv("inverse_predictor_streaming_validation_v1.csv", stream)

    docs_src = Path(__file__).with_name("docs_inverse_predictor_engine_v1.md")
    if docs_src.exists():
        shutil.copy(docs_src, out / "inverse_predictor_engine_v1.md")

    files = [
        "inverse_predictor_registry_v1.csv",
        "inverse_predictor_parameter_registry_v1.json",
        "inverse_predictor_schema_v1.csv",
        "inverse_predictor_formula_validation_v1.csv",
        "inverse_predictor_synthetic_replay_validation_v1.csv",
        "inverse_predictor_anti_leakage_validation_v1.csv",
        "inverse_predictor_streaming_validation_v1.csv",
        "inverse_predictor_engine_v1.md",
    ]
    checksums = {n: _sha(out / n) for n in files if (out / n).exists()}

    manifest = {
        "predictor_engine_version": PREDICTOR_ENGINE_VERSION,
        "wip": "INVERSE-INDICATOR-PREDICTOR-ENGINE-1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit,
        "overall_ok": overall,
        "predictor_count": len(PREDICTOR_REGISTRY),
        "parameter_set_count": len(PARAMETER_REGISTRY),
        "hypothetical_input_type": "NEXT_BAR_CLOSE",
        "validation_results": results,
        "frozen_inputs": [
            "WAVE_DATASET_V1",
            "REVERSAL_EVENT_DATASET_V1",
            "INDICATOR_ENGINE_V1",
            "VOLUME_ACCUMULATION_ENGINE_V1",
        ],
        "notes": [
            "No ranking / WHEN tournament",
            "Stochastic K/D cross requires intrabar assumption",
            "Bollinger inverse UNSUPPORTED_V1",
            "Not proprietary DiNapoli",
        ],
        "checksums_sha256": checksums,
    }
    (out / "inverse_predictor_engine_manifest_v1.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps({"overall_ok": overall, "manifest": manifest}, indent=2), encoding="utf-8")
    print(json.dumps({"overall_ok": overall, "out": str(out)}, indent=2))
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
