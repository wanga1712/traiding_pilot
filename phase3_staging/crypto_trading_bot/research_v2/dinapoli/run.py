#!/usr/bin/env python3
"""CLI: DiNapoli COP/OP/XOP validation on 4H ZigZag."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from crypto_trading_bot.research_v2.dinapoli.validate_4h import run_4h_validation
from crypto_trading_bot.research_v2.market_data import TimeframeBarService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("/var/tmp/traiding_pilot_ui_workspace/dinapoli_4h_validation"),
    )
    parser.add_argument("--end", default="2024-06-30")
    parser.add_argument("--limit", type=int, default=5000)
    args = parser.parse_args(argv)

    end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    service = TimeframeBarService(
        symbol="ETHUSDT",
        canonical_root=Path("/srv/traiding_pilot/market/binance/spot/ETHUSDT/1m"),
        cache_root=Path("/var/tmp/traiding_pilot_market_cache"),
        ssh_host=os.environ.get("TRAIDING_PILOT_SSH_HOST", "wanga@s7"),
        ssh_key=Path(os.environ.get("TRAIDING_PILOT_SSH_KEY", "/home/sergey/.ssh/id_to_nyx")),
    )
    candles = service.get_bars("4H", before=end, limit=args.limit)
    report = run_4h_validation(candles, out_dir=args.out_dir)
    print(
        json.dumps(
            {
                "total_pivots": report["total_pivots"],
                "total_abc_windows": report["total_abc_windows"],
                "discovery_windows": report["discovery_windows"],
                "validation_windows": report["validation_windows"],
                "r_median_full": report["full"]["r_median"],
                "r_mean_full": report["full"]["r_mean"],
                "validation_best_fixed": report["validation"]["best_fixed_target"],
                "cop_within_5pct_val": report["validation"]["endpoint_within_5pct"]["COP"],
                "op_within_5pct_val": report["validation"]["endpoint_within_5pct"]["OP"],
                "xop_within_5pct_val": report["validation"]["endpoint_within_5pct"]["XOP"],
                "cop_reach_val": report["validation"]["cop_reach_rate"],
                "op_reach_val": report["validation"]["op_reach_rate"],
                "xop_reach_val": report["validation"]["xop_reach_rate"],
                "signal": report["dinapoli_4h_signal"],
                "dinapoli_vs_baseline": report["dinapoli_vs_baseline"],
                "out_dir": str(args.out_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
