#!/usr/bin/env python3
"""Operational runtime projection from Repair-2/3 smoke evidence (no candidate pruning)."""
from __future__ import annotations

import json
from pathlib import Path

from crypto_trading_bot.research_v2.composite_signal_search.memory_guard import save_json

ROOTS = [
    Path("/var/tmp/traiding_pilot_ui_workspace/artifacts/MULTITF-COMPOSITE-SIGNAL-SEARCH-1"),
    Path(__file__).resolve().parents[1] / "artifacts" / "MULTITF-COMPOSITE-SIGNAL-SEARCH-1",
]
TOTAL = 200829
ENUM_SHA = "397533c24eb48bd7e0c1f18dedc4d94393c5965107cc6165eb59ecad592f7b3e"


def main() -> int:
    root = next((p for p in ROOTS if p.exists()), ROOTS[-1])
    # Repair-3 full-path smoke: 300 candidates ~20 minutes wall (from S13 log 15:42→~16:02 clean300).
    # Conservative estimate from observed ~15 candidates/minute during bounded compose.
    candidates_per_minute = 15.0
    # Cross-check repair-2 stratified 190 in ~24 min ≈ 7.9/min — use blended conservative.
    repair2_cpm = 190.0 / 24.0
    blended = min(candidates_per_minute, repair2_cpm)
    # Prefer repair-3 full-path rate for projection (same code path as full run).
    cpm = candidates_per_minute
    hours = (TOTAL / cpm) / 60.0
    out = {
        "artifact": "composite_full_runtime_projection_v1",
        "TOTAL_COMPOSITE_CANDIDATE_COUNT": TOTAL,
        "COMPOSITE_ENUMERATION_SHA256": ENUM_SHA,
        "evidence": {
            "repair3_full_path_smoke_count": 300,
            "repair3_observed_candidates_per_minute_approx": candidates_per_minute,
            "repair2_stratified_190_per_minute_approx": repair2_cpm,
            "note": "Operational only — do not prune the 200829 set based on runtime.",
        },
        "CANDIDATES_PER_MINUTE": cpm,
        "PROJECTED_FULL_RUNTIME_HOURS": hours,
        "blended_conservative_cpm": blended,
        "blended_projected_hours": (TOTAL / blended) / 60.0,
    }
    save_json(root / "composite_full_runtime_projection_v1.json", out)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
