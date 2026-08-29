"""Run VOLUME_ACCUMULATION_ENGINE_V1 validation and write artifacts."""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from crypto_trading_bot.research_v2.volume_accumulation.registry import (
    FEATURE_REGISTRY,
    PARAMETER_REGISTRY,
    SCHEMA_COLUMNS,
)
from crypto_trading_bot.research_v2.volume_accumulation.version import FEATURE_ENGINE_VERSION


def _run() -> list[dict]:
    import crypto_trading_bot.research_v2.volume_accumulation.tests.test_volume_accumulation as t

    cases = [
        ("reference_obv_vwap_efficiency", t.test_obv_vwap_efficiency_manual),
        ("reference_cmf_mfi", t.test_cmf_mfi_bounds),
        ("reference_compression_ratio", t.test_compression_ratio),
        ("batch_streaming", t.test_batch_equals_streaming),
        ("future_price_mutation", t.test_future_price_and_volume_mutation),
        ("true_pivot_outcome_leakage", t.test_true_pivot_and_outcome_leakage_rejected),
        ("forbidden_keys", t.test_forbidden_keys_documented),
        ("unfinished_htf", t.test_unfinished_htf),
        ("warmup_gap", t.test_warmup_and_gap),
        ("context_snapshot_api", t.test_context_snapshot_api),
        ("no_c_centered_window", t.test_no_c_centered_window_api),
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
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "artifacts/VOLUME-ACCUMULATION-FEATURES-1")
    out.mkdir(parents=True, exist_ok=True)
    try:
        git_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001
        git_commit = "UNKNOWN"

    results = _run()
    overall = all(r["status"] == "PASS" for r in results)

    with (out / "volume_accumulation_feature_registry_v1.csv").open("w", newline="", encoding="utf-8") as f:
        fields = ["feature_id", "family", "description", "unit", "causal", "warmup"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in FEATURE_REGISTRY:
            w.writerow({k: row.get(k, "") for k in fields})

    (out / "volume_accumulation_parameter_registry_v1.json").write_text(
        json.dumps(PARAMETER_REGISTRY, indent=2), encoding="utf-8"
    )

    with (out / "volume_accumulation_schema_v1.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["column", "class", "note"])
        for a, b, c in SCHEMA_COLUMNS:
            w.writerow([a, b, c])

    anti = [r for r in results if any(x in r["test"] for x in ("mutation", "leakage", "forbidden", "htf", "no_c_"))]
    ref = [r for r in results if r["test"].startswith("reference_")]
    stream = [r for r in results if "streaming" in r["test"] or r["test"] in ("warmup_gap", "context_snapshot_api")]

    def write_csv(name: str, rows: list[dict]) -> None:
        with (out / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["test", "status", "detail"])
            w.writeheader()
            w.writerows(rows)

    write_csv("volume_accumulation_anti_leakage_validation_v1.csv", anti)
    write_csv("volume_accumulation_reference_validation_v1.csv", ref)
    write_csv("volume_accumulation_streaming_validation_v1.csv", stream)

    readme = Path(__file__).with_name("README.md")
    if readme.exists():
        (out / "README.md").write_text(readme.read_text(encoding="utf-8"), encoding="utf-8")

    # optional tiny diagnostic plot data (no major UI)
    (out / "diagnostic_sample_note.txt").write_text(
        "Diagnostic-only: use CONTEXT_BUNDLE_V1 values with price/volume charts; do not tune on true C.\n",
        encoding="utf-8",
    )

    files = [
        "volume_accumulation_feature_registry_v1.csv",
        "volume_accumulation_parameter_registry_v1.json",
        "volume_accumulation_schema_v1.csv",
        "volume_accumulation_reference_validation_v1.csv",
        "volume_accumulation_anti_leakage_validation_v1.csv",
        "volume_accumulation_streaming_validation_v1.csv",
        "README.md",
    ]
    checksums = {n: _sha(out / n) for n in files if (out / n).exists()}

    families = sorted({f["family"] for f in FEATURE_REGISTRY})
    manifest = {
        "feature_engine_version": FEATURE_ENGINE_VERSION,
        "wip": "VOLUME-ACCUMULATION-FEATURES-1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit,
        "overall_ok": overall,
        "feature_count": len(FEATURE_REGISTRY),
        "parameter_set_count": len(PARAMETER_REGISTRY),
        "feature_families": families,
        "timeframes_supported": ["5m", "15m", "1H", "4H"],
        "context_snapshot_api": "compute_market_context",
        "validation_results": results,
        "frozen_inputs": [
            "WAVE_DATASET_V1",
            "REVERSAL_EVENT_DATASET_V1",
            "INDICATOR_ENGINE_V1",
        ],
        "checksums_sha256": checksums,
        "notes": [
            "No WHEN tournament",
            "Neutral terminology: no ACCUMULATION/DISTRIBUTION ground truth",
            "Spot OHLCV proxies only — not taker/orderflow",
        ],
    }
    (out / "volume_accumulation_engine_manifest_v1.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps({"overall_ok": overall, "manifest": manifest}, indent=2), encoding="utf-8")
    print(json.dumps({"overall_ok": overall, "out": str(out), "feature_count": len(FEATURE_REGISTRY)}, indent=2))
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
