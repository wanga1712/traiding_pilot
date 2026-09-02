#!/usr/bin/env python3
"""5m full-history inverse threshold smoke (threshold series only)."""
import json
import os
import sys
import time

os.chdir("/var/tmp/traiding_pilot_ui_workspace/phase3_staging")
sys.path.insert(0, ".")
os.environ.setdefault("TRAIDING_PILOT_MARKET_CACHE", "/var/tmp/traiding_pilot_market_cache")
os.environ.setdefault("TRAIDING_PILOT_SSH_KEY", "/home/sergey/.ssh/id_to_nyx")

from crypto_trading_bot.research_v2.indicator_parameter_search.config import split_bounds
from crypto_trading_bot.research_v2.inverse_predictors.batch_thresholds import (
    AUTHORIZED_INVERSE_PARAMETER_SETS,
    compute_inverse_threshold_series,
)
from crypto_trading_bot.research_v2.reversal_signal_study.bar_io import load_continuous_bars, make_bar_service

disc_start, disc_end = split_bounds("DISCOVERY")
t0 = time.perf_counter()
service = make_bar_service()
bars = load_continuous_bars(service, "5m", disc_start, disc_end, warmup_bars=500)
load_s = time.perf_counter() - t0
cache = {}
threshold_counts = {}
signal_counts = {}
exceptions = []
dead = []
disc_start_iso = disc_start.isoformat()
disc_end_iso = disc_end.isoformat()

from crypto_trading_bot.research_v2.indicator_parameter_search.signals_bank import _generate_inverse_signals

for pred_id in AUTHORIZED_INVERSE_PARAMETER_SETS:
    try:
        t1 = time.perf_counter()
        series = compute_inverse_threshold_series(bars, parameter_set_id=pred_id, source_timeframe="5m", cache=cache)
        threshold_counts[pred_id] = series.threshold_count
        direction = "UP" if "UP" in pred_id or pred_id.endswith("_OS_V1") else "DOWN"
        row = {
            "candidate_id": f"SMOKE_{pred_id}",
            "direction": direction,
            "decision_tf": "5m",
            "parameters": {"inverse_parameter_set_id": pred_id},
        }
        sigs = _generate_inverse_signals(
            bars, row, scan_start_iso=disc_start_iso, scan_end_iso=disc_end_iso, threshold_cache=cache
        )
        signal_counts[pred_id] = len(sigs)
        usable_states = int((series.usable_thresholds == series.usable_thresholds).sum())  # finite count
        import numpy as np

        usable_states = int(np.isfinite(series.usable_thresholds).sum())
        if usable_states > 0 and series.threshold_count == 0:
            dead.append(pred_id)
        print(f"{pred_id} thr={series.threshold_count} sig={len(sigs)} sec={time.perf_counter()-t1:.1f}", flush=True)
    except Exception as exc:
        exceptions.append(f"{pred_id}: {exc}")

out = {
    "INVERSE_5M_FULL_HISTORY_ROUTE_COUNT": len(AUTHORIZED_INVERSE_PARAMETER_SETS),
    "INVERSE_5M_FULL_HISTORY_EXCEPTION_COUNT": len(exceptions),
    "INVERSE_5M_DEAD_EXECUTION_ROUTE_COUNT": len(dead),
    "INVERSE_5M_THRESHOLD_COUNTS_BY_ROUTE": threshold_counts,
    "INVERSE_5M_SIGNAL_COUNTS_BY_ROUTE": signal_counts,
    "INVERSE_5M_BAR_COUNT": len(bars),
    "load_seconds": round(load_s, 2),
    "exceptions": exceptions,
    "dead_routes": dead,
}
art = "/var/tmp/traiding_pilot_ui_workspace/artifacts/MULTITF-INDICATOR-PARAMETER-SEARCH-1"
path = f"{art}/_inverse_5m_smoke_v1.json"
with open(path, "w", encoding="utf-8") as f:
    json.dump(out, f, indent=2)
print(json.dumps(out, indent=2))
