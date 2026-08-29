#!/usr/bin/env python3
"""CLI: freeze WAVE_ENGINE_V1 / WAVE_DATASET_V1 (immutable)."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from crypto_trading_bot.research_v2.market_data import TimeframeBarService
from crypto_trading_bot.research_v2.resampling import TIMEFRAMES, UI_TIMEFRAMES
from crypto_trading_bot.research_v2.wave_engine.freeze_dataset import run_freeze
from crypto_trading_bot.research_v2.wave_engine.v1_config import CONFIG_BY_TF, TIMEFRAMES as ENGINE_TFS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("/var/tmp/traiding_pilot_ui_workspace/wave_dataset_v1"),
    )
    parser.add_argument("--end", default="2024-06-30")
    parser.add_argument("--limit", type=int, default=120000)
    parser.add_argument("--years", type=float, default=5.0)
    parser.add_argument("--git-commit", default=None)
    args = parser.parse_args(argv)

    end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    service = TimeframeBarService(
        symbol="ETHUSDT",
        canonical_root=Path("/srv/traiding_pilot/market/binance/spot/ETHUSDT/1m"),
        cache_root=Path("/var/tmp/traiding_pilot_market_cache"),
        ssh_host="wanga@10.8.0.7",
        ssh_key=Path("/home/sergey/.ssh/id_to_nyx"),
    )

    candles_by_tf: dict[str, list[dict]] = {}
    for tf in ENGINE_TFS:
        minutes = TIMEFRAMES[tf]
        needed = int(args.years * 365.25 * 24 * 60 / minutes) + 50
        limit = min(args.limit, max(needed, 800))
        print(f"[load] {tf} limit={limit} cfg={CONFIG_BY_TF[tf]}", flush=True)
        candles_by_tf[tf] = service.get_bars(tf, before=end, limit=limit)
        print(f"[load] {tf} got={len(candles_by_tf[tf])}", flush=True)

    report = run_freeze(
        candles_by_tf,
        out_dir=args.out_dir,
        git_commit=args.git_commit,
    )
    print(
        json.dumps(
            {
                "wave_engine_version": report["wave_engine_version"],
                "wave_dataset_version": report["wave_dataset_version"],
                "overall_validation_ok": report["overall_validation_ok"],
                "pivots_by_tf": report["dataset_manifest"]["pivots_by_tf"],
                "legs_by_tf": report["dataset_manifest"]["legs_by_tf"],
                "rolling_windows_by_tf": report["dataset_manifest"]["rolling_windows_by_tf"],
                "r_median_by_tf": report["dataset_manifest"]["r_median_by_tf"],
                "dataset_time_from": report["dataset_manifest"]["dataset_time_from"],
                "dataset_time_to": report["dataset_manifest"]["dataset_time_to"],
                "out_dir": report["out_dir"],
            },
            indent=2,
            default=str,
        )
    )
    return 0 if report["overall_validation_ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
