"""Run validation suite and write INDICATOR_ENGINE_V1 artifacts."""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from crypto_trading_bot.research_v2.indicator_engine.registry import (
    INDICATOR_REGISTRY,
    PARAMETER_REGISTRY,
    SCHEMA_COLUMNS,
)
from crypto_trading_bot.research_v2.indicator_engine.version import INDICATOR_ENGINE_VERSION


def _run_tests() -> list[dict]:
    import crypto_trading_bot.research_v2.indicator_engine.tests.test_dma as t_dma
    import crypto_trading_bot.research_v2.indicator_engine.tests.test_reference_and_leakage as t_ref
    import crypto_trading_bot.research_v2.indicator_engine.tests.test_mtf_warmup_gaps as t_mtf

    cases = [
        ("DMA3x3_numeric", t_dma.test_dma_3x3_numeric_and_semantics),
        ("DMA7x5_DMA25x5", t_dma.test_dma_7x5_and_25x5_warmup_and_shift),
        ("DMA_anti_leakage", t_dma.test_dma_anti_leakage_future_mutation),
        ("Stochastic_correctness", t_ref.test_stochastic_correctness_manual),
        ("Displaced_Stochastic_anti_leakage", t_ref.test_displaced_stochastic_anti_leakage),
        ("MACD_correctness", t_ref.test_macd_correctness_vs_manual_ema),
        ("Displaced_MACD_anti_leakage", t_ref.test_displaced_macd_anti_leakage),
        ("RSI_correctness", t_ref.test_rsi_warmup_and_bounds),
        ("ATR_correctness", t_ref.test_atr_vs_manual_wilder),
        ("Bollinger_correctness", t_ref.test_bollinger_mid_is_sma),
        ("Higher_TF_closed_bar", t_mtf.test_higher_tf_closed_bar_availability),
        ("Warmup", t_mtf.test_warmup_null_not_zero),
        ("Gap_handling", t_mtf.test_gap_marks_invalid),
        ("Reproducibility", t_mtf.test_reproducibility),
    ]
    rows = []
    for name, fn in cases:
        try:
            fn()
            rows.append({"test": name, "status": "PASS", "detail": ""})
            print(f"PASS {name}", flush=True)
        except Exception as exc:  # noqa: BLE001
            rows.append({"test": name, "status": "FAIL", "detail": f"{exc}"})
            print(f"FAIL {name}: {exc}", flush=True)
            traceback.print_exc()
    return rows


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "artifacts/REVERSAL-INDICATOR-ENGINE-1")
    out.mkdir(parents=True, exist_ok=True)
    git_commit = "UNKNOWN"
    try:
        git_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001
        pass

    results = _run_tests()
    overall = all(r["status"] == "PASS" for r in results)

    # registries
    with (out / "indicator_registry_v1.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["indicator_id", "family", "description"])
        w.writeheader()
        for row in INDICATOR_REGISTRY:
            w.writerow(row)

    (out / "indicator_parameter_registry_v1.json").write_text(
        json.dumps(PARAMETER_REGISTRY, indent=2), encoding="utf-8"
    )

    with (out / "indicator_schema_registry_v1.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["column", "class", "note"])
        for col, cls, note in SCHEMA_COLUMNS:
            w.writerow([col, cls, note])

    anti = [r for r in results if "leakage" in r["test"].lower() or "Higher_TF" in r["test"] or "DMA_anti" in r["test"]]
    ref = [r for r in results if r["test"] not in {x["test"] for x in anti}]

    with (out / "indicator_anti_leakage_validation_v1.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["test", "status", "detail"])
        w.writeheader()
        w.writerows(anti)

    with (out / "indicator_reference_validation_v1.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["test", "status", "detail"])
        w.writeheader()
        w.writerows(ref)

    readme_src = Path(__file__).with_name("README.md")
    if readme_src.exists():
        (out / "README.md").write_text(readme_src.read_text(encoding="utf-8"), encoding="utf-8")

    artifact_files = [
        "indicator_registry_v1.csv",
        "indicator_parameter_registry_v1.json",
        "indicator_schema_registry_v1.csv",
        "indicator_reference_validation_v1.csv",
        "indicator_anti_leakage_validation_v1.csv",
        "README.md",
    ]
    checksums = {}
    for name in artifact_files:
        p = out / name
        if p.exists():
            checksums[name] = _sha256(p)

    manifest = {
        "indicator_engine_version": INDICATOR_ENGINE_VERSION,
        "wip": "REVERSAL-INDICATOR-ENGINE-1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit,
        "overall_ok": overall,
        "parameter_set_count": len(PARAMETER_REGISTRY),
        "indicator_count": len(INDICATOR_REGISTRY),
        "time_semantics": {
            "CALCULATED_AT": "close_time of last source bar used",
            "AVAILABLE_AT": "equals CALCULATED_AT for closed-candle indicators",
            "DISPLAYED_AT": "optional chart shift; never availability",
        },
        "baselines": {
            "DMA": ["DMA_3X3_V1", "DMA_7X5_V1", "DMA_25X5_V1"],
            "STOCHASTIC": ["STOCH_14_3_3_V1"],
            "DISPLACED_STOCHASTIC": ["DISPLACED_STOCH_14_3_3_SHIFT3_V1"],
            "MACD": ["MACD_12_26_9_V1"],
            "DISPLACED_MACD": ["DISPLACED_MACD_12_26_9_SHIFT3_V1"],
            "RSI": ["RSI_7_V1", "RSI_14_V1", "RSI_21_V1"],
        },
        "validation_results": results,
        "checksums_sha256": checksums,
        "notes": [
            "No true-pivot tournament in this WIP",
            "Displaced Stoch/MACD presets marked PROJECT_EXPERIMENTAL",
            "Do not modify WAVE_DATASET_V1 or REVERSAL_EVENT_DATASET_V1",
        ],
    }
    (out / "indicator_engine_manifest_v1.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps({"overall_ok": overall, "manifest": manifest}, indent=2), encoding="utf-8")
    print(json.dumps({"overall_ok": overall, "out": str(out)}, indent=2))
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
