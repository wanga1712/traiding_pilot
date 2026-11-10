#!/usr/bin/env python3
"""CLI: ZigZag normalization + DiNapoli/R retest (does not overwrite FIXED_ZZ_BASELINE_V1)."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from crypto_trading_bot.research_v2.dinapoli.normalize_retest import run_normalize_and_retest
from crypto_trading_bot.research_v2.market_data import TimeframeBarService
from crypto_trading_bot.research_v2.resampling import TIMEFRAMES, UI_TIMEFRAMES


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("/var/tmp/traiding_pilot_ui_workspace/dinapoli_normalized_retest"),
    )
    parser.add_argument(
        "--fixed-baseline-summary",
        type=Path,
        default=Path("/var/tmp/traiding_pilot_ui_workspace/dinapoli_multitf_sweep/dinapoli_multitf_summary.csv"),
    )
    parser.add_argument("--end", default="2024-06-30")
    parser.add_argument("--limit", type=int, default=120000)
    parser.add_argument("--years", type=float, default=5.0)
    args = parser.parse_args(argv)

    # Protect immutable baseline directory
    baseline_dir = Path("/var/tmp/traiding_pilot_ui_workspace/dinapoli_multitf_sweep")
    marker = baseline_dir / "FIXED_ZZ_BASELINE_V1.txt"
    if baseline_dir.exists() and not marker.exists():
        marker.write_text(
            "IMMUTABLE BASELINE\nWIP=DINAPOLI-COP-OP-XOP-MULTITIMEFRAME-SWEEP-1\nLABEL=FIXED_ZZ_BASELINE_V1\n",
            encoding="utf-8",
        )
    if args.out_dir.resolve() == baseline_dir.resolve():
        raise SystemExit("Refusing to write into FIXED_ZZ_BASELINE_V1 directory")

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
        minutes = TIMEFRAMES[tf]
        needed = int(args.years * 365.25 * 24 * 60 / minutes) + 50
        limit = min(args.limit, max(needed, 800))
        print(f"[load] {tf} limit={limit}", flush=True)
        candles_by_tf[tf] = service.get_bars(tf, before=end, limit=limit)
        print(f"[load] {tf} got={len(candles_by_tf[tf])}", flush=True)

    report = run_normalize_and_retest(
        candles_by_tf,
        out_dir=args.out_dir,
        fixed_baseline_summary=args.fixed_baseline_summary,
    )
    print(
        json.dumps(
            {
                "global_normalized_zz_found": report["global_normalized_zz_found"],
                "normalized_zz_config": report["normalized_zz_config"],
                "geometry_comparable_across_tf": report["geometry_comparable_across_tf"],
                "r_median_by_tf": report["r_median_by_tf"],
                "r1_mae_by_tf": report["r1_mae_by_tf"],
                "cop_reach_by_tf": report["cop_reach_by_tf"],
                "op_reach_by_tf": report["op_reach_by_tf"],
                "xop_reach_by_tf": report["xop_reach_by_tf"],
                "p_op_given_cop_by_tf": report["p_op_given_cop_by_tf"],
                "p_xop_given_op_by_tf": report["p_xop_given_op_by_tf"],
                "cop_ratio_special": report["cop_ratio_special"],
                "op_ratio_special": report["op_ratio_special"],
                "xop_ratio_special": report["xop_ratio_special"],
                "leg_persistence_supported": report["leg_persistence_supported"],
                "continuous_wave_distribution_supported": report["continuous_wave_distribution_supported"],
                "best_geometry_tf": report["best_geometry_tf"],
                "dinapoli_specific_ratios_supported": report["dinapoli_specific_ratios_supported"],
                "ready_to_close_geometry_phase": report["ready_to_close_geometry_phase"],
                "ready_for_market_context_phase": report["ready_for_market_context_phase"],
                "freeze_note": report.get("freeze_note"),
                "decision_matrix": report["decision_matrix"],
                "out_dir": str(args.out_dir),
            },
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
