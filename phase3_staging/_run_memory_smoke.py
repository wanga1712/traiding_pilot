#!/usr/bin/env python3
"""Run bounded-memory smoke (>=100 composites) and write acceptance summary."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from crypto_trading_bot.research_v2.composite_signal_search.bounded_compose import run_bounded_compose
from crypto_trading_bot.research_v2.composite_signal_search.memory_guard import save_json

ART = Path("/var/tmp/traiding_pilot_ui_workspace/artifacts/MULTITF-COMPOSITE-SIGNAL-SEARCH-1")
smoke_csv = ART / "composite_memory_smoke_v1.csv"

out = run_bounded_compose(
    artifact_root=ART,
    max_candidates=120,
    smoke_rss_csv=smoke_csv,
    resume=False,
)
print(json.dumps(out, indent=2, default=str)[:3000])

peak = growth = None
status = "FAIL"
if smoke_csv.exists():
    df = pd.read_csv(smoke_csv)
    if not df.empty:
        rss = df["rss_mb"].astype(float)
        peak = float(rss.max()) / 1024.0
        n = len(rss)
        first = float(rss.iloc[: max(1, n // 2)].mean())
        last = float(rss.iloc[n // 2 :].mean())
        growth = (last - first) / 1024.0
        status = "PASS" if peak <= 8.0 and growth <= 1.0 and int(out.get("n_evaluated") or 0) >= 100 else "FAIL"

report = {
    "artifact": "composite_memory_smoke_acceptance_v1",
    "MEMORY_SMOKE_CANDIDATE_COUNT": out.get("n_evaluated"),
    "MEMORY_SMOKE_PEAK_RSS_GB": peak,
    "MEMORY_SMOKE_RSS_GROWTH_GB": growth,
    "BOUNDED_MEMORY_SMOKE": status,
    "run": out,
}
save_json(ART / "composite_memory_smoke_acceptance_v1.json", report)
print(json.dumps(report, indent=2, default=str)[:2000])
raise SystemExit(0 if status == "PASS" else 2)
