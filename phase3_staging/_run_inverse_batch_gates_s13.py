#!/usr/bin/env python3
import json
import os
import sys

os.chdir("/var/tmp/traiding_pilot_ui_workspace/phase3_staging")
sys.path.insert(0, ".")
os.environ.setdefault("TRAIDING_PILOT_MARKET_CACHE", "/var/tmp/traiding_pilot_market_cache")
os.environ.setdefault("TRAIDING_PILOT_SSH_KEY", "/home/sergey/.ssh/id_to_nyx")

from crypto_trading_bot.research_v2.indicator_parameter_search.candidate_routing import (
    run_inverse_5m_full_history_smoke,
    run_inverse_batch_complexity,
    run_inverse_batch_reference_parity,
    run_inverse_production_path_audit,
    run_v2_integrity_gates,
)

out = {
    "smoke": run_inverse_5m_full_history_smoke(),
    "complexity": run_inverse_batch_complexity(),
    "production_path": run_inverse_production_path_audit(),
}
art = "/var/tmp/traiding_pilot_ui_workspace/artifacts/MULTITF-INDICATOR-PARAMETER-SEARCH-1"
with open(f"{art}/_inverse_batch_gates_v1.json", "w", encoding="utf-8") as f:
    json.dump(out, f, indent=2)
print(json.dumps(out, indent=2))
