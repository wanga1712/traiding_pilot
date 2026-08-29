#!/usr/bin/env python3
"""CLI: build REVERSAL_EVENT_DATASET_V1 from WAVE_DATASET_V1."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from crypto_trading_bot.research_v2.market_data import TimeframeBarService
from crypto_trading_bot.research_v2.reversal_events.build_dataset import run_build
from crypto_trading_bot.research_v2.reversal_events.test_anti_leakage import (
    test_filter_excludes_future_closes,
    test_get_event_history_scopes_event_and_tf,
    test_unfinished_higher_tf_bar_excluded,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--wave-dir",
        type=Path,
        default=Path("/var/tmp/traiding_pilot_ui_workspace/wave_dataset_v1"),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("/var/tmp/traiding_pilot_ui_workspace/reversal_event_dataset_v1"),
    )
    parser.add_argument("--git-commit", default=None)
    args = parser.parse_args(argv)

    # Unit anti-leakage tests first
    test_filter_excludes_future_closes()
    test_get_event_history_scopes_event_and_tf()
    test_unfinished_higher_tf_bar_excluded()
    print("PASS unit anti-leakage tests", flush=True)

    service = TimeframeBarService(
        symbol="ETHUSDT",
        canonical_root=Path("/srv/traiding_pilot/market/binance/spot/ETHUSDT/1m"),
        cache_root=Path("/var/tmp/traiding_pilot_market_cache"),
        ssh_host="wanga@10.8.0.7",
        ssh_key=Path("/home/sergey/.ssh/id_to_nyx"),
    )
    report = run_build(
        wave_dir=args.wave_dir,
        out_dir=args.out_dir,
        service=service,
        git_commit=args.git_commit,
    )
    m = report["manifest"]
    print(
        json.dumps(
            {
                "overall_ok": report["overall_ok"],
                "event_dataset_version": m["dataset_version"],
                "wave_dataset_v1_unchanged": m["wave_dataset_v1_unchanged"],
                "event_counts": m["event_counts"],
                "partition": m["partition"],
                "anti_leakage": m["validations"]["anti_leakage"],
                "out_dir": report["out_dir"],
            },
            indent=2,
            default=str,
        )
    )
    return 0 if report["overall_ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
