#!/usr/bin/env python3
"""CLI: multi-timeframe DiNapoli sweep with fixed ZigZag."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from crypto_trading_bot.research_v2.dinapoli.multitf_sweep import run_multitf_sweep
from crypto_trading_bot.research_v2.market_data import TimeframeBarService
from crypto_trading_bot.research_v2.resampling import TIMEFRAMES, UI_TIMEFRAMES


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("/var/tmp/traiding_pilot_ui_workspace/dinapoli_multitf_sweep"),
    )
    parser.add_argument("--end", default="2024-06-30")
    parser.add_argument(
        "--limit",
        type=int,
        default=120000,
        help="Max bars per TF (raise for 5m/15m coverage)",
    )
    parser.add_argument(
        "--years",
        type=float,
        default=5.0,
        help="Target calendar span years per TF (capped by --limit)",
    )
    args = parser.parse_args(argv)

    end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    service = TimeframeBarService(
        symbol="ETHUSDT",
        canonical_root=Path("/srv/traiding_pilot/market/binance/spot/ETHUSDT/1m"),
        cache_root=Path("/var/tmp/traiding_pilot_market_cache"),
        ssh_host=os.environ.get("TRAIDING_PILOT_SSH_HOST", "wanga@s7"),
        ssh_key=Path(os.environ.get("TRAIDING_PILOT_SSH_KEY", "/home/sergey/.ssh/id_to_nyx")),
    )

    candles_by_tf: dict[str, list[dict]] = {}
    for tf in UI_TIMEFRAMES:
        # Aim for similar calendar span where possible.
        minutes = TIMEFRAMES[tf]
        needed = int(args.years * 365.25 * 24 * 60 / minutes) + 50
        limit = min(args.limit, max(needed, 800))
        print(f"[load] {tf} limit={limit} needed_for_{args.years}y={needed}", flush=True)
        candles_by_tf[tf] = service.get_bars(tf, before=end, limit=limit)
        print(f"[load] {tf} got={len(candles_by_tf[tf])}", flush=True)

    report = run_multitf_sweep(candles_by_tf, out_dir=args.out_dir)
    print(
        json.dumps(
            {
                "timeframes_tested": report["timeframes_tested"],
                "zigzag_config_fixed": report["zigzag_config_fixed"],
                "best_tf_target_clustering": report["best_tf_target_clustering"],
                "best_tf_path_progression": report["best_tf_path_progression"],
                "best_tf_target_error": report["best_tf_target_error"],
                "most_stable_tf": report["most_stable_tf"],
                "most_reliable_tf": report["most_reliable_tf"],
                "cop_mode_special": report["cop_mode_special"],
                "op_mode_special": report["op_mode_special"],
                "xop_mode_special": report["xop_mode_special"],
                "dinapoli_ratios_beat_control_ratios": report["dinapoli_ratios_beat_control_ratios"],
                "tf_requiring_normalized_zigzag": report["tf_requiring_normalized_zigzag"],
                "best_overall_research_tf": report["best_overall_research_tf"],
                "summary_table": report["summary_table"],
                "out_dir": str(args.out_dir),
            },
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
