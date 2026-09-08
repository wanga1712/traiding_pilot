#!/usr/bin/env python3
"""Re-run only real old/new parity after class-input field completeness fix."""
from __future__ import annotations

import json
from pathlib import Path

from crypto_trading_bot.research_v2.composite_signal_search.compose import iter_all_template_definitions
from crypto_trading_bot.research_v2.composite_signal_search.config import load_atomic_bank, load_templates
from crypto_trading_bot.research_v2.composite_signal_search.memory_guard import save_json
from crypto_trading_bot.research_v2.composite_signal_search.parity_runner import run_old_new_parity
from crypto_trading_bot.research_v2.composite_signal_search.smoke_selection import (
    coverage_stats,
    select_parity_definitions,
)

ART = Path("/var/tmp/traiding_pilot_ui_workspace/artifacts/MULTITF-COMPOSITE-SIGNAL-SEARCH-1")


def main() -> int:
    reps = json.loads((ART / "atomic_representative_bank_v1.json").read_text(encoding="utf-8"))
    configs = list(load_atomic_bank(root=ART)["configs"])
    parity_stream = iter_all_template_definitions(
        representatives=list(reps["configs"]),
        all_configs_for_pairs=configs,
        templates_doc=load_templates(root=ART),
    )
    parity_defs = select_parity_definitions(parity_stream)
    print("parity_n", len(parity_defs), coverage_stats(parity_defs), flush=True)
    parity = run_old_new_parity(parity_defs, artifact_root=ART)
    print("parity", parity, flush=True)

    # refresh combined acceptance without redoing smoke/stress
    prior = {}
    acc_path = ART / "repair2_acceptance_v1.json"
    if acc_path.exists():
        prior = json.loads(acc_path.read_text(encoding="utf-8"))
    prior["parity"] = parity
    prior["parity_includes_price_baseline"] = True
    save_json(acc_path, prior)

    if (
        parity["COMPOSITE_TIMESTAMP_PARITY"] != "PASS"
        or parity["COMPOSITE_METRIC_PARITY"] != "PASS"
        or parity["COMPOSITE_CLASS_INPUT_PARITY"] != "PASS"
    ):
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
