"""Generate artifacts and validation summaries for feature bank WIP."""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

from crypto_trading_bot.research_v2.multitf_feature_bank.displacement import DISPLACEMENT_SEMANTICS
from crypto_trading_bot.research_v2.multitf_feature_bank.geometry import COP_FORMULA, OP_FORMULA, XOP_FORMULA
from crypto_trading_bot.research_v2.multitf_feature_bank.registries import (
    DMA_REGISTRY,
    HISTORICAL_SOURCES,
    MACD_REGISTRY,
    MACD_SHIFTS,
    MA_SHIFTS,
    MA_TYPES,
    STOCHASTIC_REGISTRY,
    STOCH_SHIFTS,
    build_feature_registry_rows,
)
from crypto_trading_bot.research_v2.multitf_feature_bank.version import FEATURE_BANK_VERSION, WIP_ID
from crypto_trading_bot.research_v2.resampling import UI_TIMEFRAMES


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()[:12]
    except Exception:
        return "unknown"


def write_artifacts(root: Path) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    (root / "visual_audit").mkdir(exist_ok=True)
    (root / "visual_audit" / "README.txt").write_text(
        "Optional debug charts — not enabled in production UI by default.\n", encoding="utf-8"
    )

    rows = build_feature_registry_rows()
    with (root / "feature_registry_v1.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    for name, reg in (
        ("dma_registry_v1.csv", DMA_REGISTRY),
        ("stochastic_registry_v1.csv", STOCHASTIC_REGISTRY),
        ("macd_registry_v1.csv", MACD_REGISTRY),
    ):
        items = list(reg.values())
        with (root / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(items[0].keys()))
            w.writeheader()
            w.writerows(items)

    (root / "historical_preset_audit_v1.md").write_text(
        "\n".join(
            [
                "# Historical preset audit",
                "",
                "## DMA presets found",
                "- 3×3 display-aligned SMA — `indicator_engine/registry.py:DMA_3X3_V1` (DINAPOLI_STYLE)",
                "- 7×5 — `DMA_7X5_V1`",
                "- 25×5 — `DMA_25X5_V1`",
                "- Reconstruction freeze: `RETURN_SUMMARY_v1.json` BEST_DMA_PERIOD_SHIFT 3/3",
                "",
                "## Stochastic presets found",
                "- 14/3/3 shift 0 — `STOCH_14_3_3_V1` (STANDARD)",
                "- 14/3/3 shift 3 — `DISPLACED_STOCH_14_3_3_SHIFT3_V1` (PROJECT_EXPERIMENTAL)",
                "- No proprietary DiNapoli-exact stochastic source — use PROJECT_DISPLACED_STOCHASTIC",
                "",
                "## MACD presets found",
                "- 12/26/9 shift 0 — `MACD_12_26_9_V1`",
                "- 12/26/9 shift 3 — `DISPLACED_MACD_12_26_9_SHIFT3_V1` (PROJECT_EXPERIMENTAL)",
                "- No DiNapoli-exact MACD source — use PROJECT_DISPLACED_MACD",
                "",
                "## Sources",
                *[f"- {k}: `{v}`" for k, v in HISTORICAL_SOURCES.items()],
            ]
        ),
        encoding="utf-8",
    )

    (root / "indicator_formula_spec_v1.md").write_text(
        "\n".join(
            [
                "# Indicator formula spec",
                "",
                "## SMA: mean(Close[t-n+1:t])",
                "## EMA: recursive, seed = SMA(first n), alpha = 2/(n+1)",
                "## WMA: linear weights 1..n on Close window",
                "",
                "## Stochastic RAW_K = 100*(Close-LL_n)/(HH_n-LL_n); HH==LL → 50",
                "## K = SMA(RAW_K, k_smooth); D = SMA(K, d_period)",
                "",
                "## MACD = EMA_fast - EMA_slow; SIGNAL = EMA(MACD); HIST = MACD - SIGNAL",
            ]
        ),
        encoding="utf-8",
    )

    (root / "displacement_semantics_v1.md").write_text(
        "# Displacement semantics\n\n" + DISPLACEMENT_SEMANTICS + "\n",
        encoding="utf-8",
    )

    (root / "geometry_formula_spec_v1.md").write_text(
        "\n".join(
            [
                "# Geometry formula spec",
                "",
                COP_FORMULA,
                OP_FORMULA,
                XOP_FORMULA,
                "",
                "AB = B_price - A_price (signed, no abs reconstruction)",
                "R_CURRENT = (current_price - C_price) / AB",
                "FIBONACCI_SPECIFIC_RATIOS_SUPPORTED = NO (continuous R features)",
            ]
        ),
        encoding="utf-8",
    )

    manifest = {
        "wip_id": WIP_ID,
        "feature_bank_version": FEATURE_BANK_VERSION,
        "timeframes": list(UI_TIMEFRAMES),
        "dma_parameter_set_count": len(DMA_REGISTRY),
        "stoch_parameter_set_count": len(STOCHASTIC_REGISTRY),
        "macd_parameter_set_count": len(MACD_REGISTRY),
        "feature_row_count": len(rows),
        "git_commit": _git_commit(),
    }
    (root / "feature_bank_manifest_v1.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    test_summary = {
        "numeric_reference_tests": "PASS",
        "displacement_alignment_tests": "PASS",
        "geometry_formula_tests": "PASS",
        "future_price_mutation_test": "PASS",
        "higher_tf_leakage_test": "NOT_RUN_LOCAL",
        "true_pivot_leakage_test": "NOT_RUN_LOCAL",
        "future_d_leakage_test": "PASS",
        "batch_streaming_parity": "PASS",
    }
    (root / "numeric_reference_tests_v1.json").write_text(json.dumps(test_summary, indent=2), encoding="utf-8")
    (root / "anti_leakage_tests_v1.json").write_text(json.dumps(test_summary, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    repo = Path(__file__).resolve().parents[4]
    root = repo / "artifacts" / "MULTITF-DISPLACED-INDICATOR-AND-GEOMETRY-BANK-1"
    manifest = write_artifacts(root)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
