"""Load expert gold + candles and run classic ZigZag reconstruction."""
from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from crypto_trading_bot.research_v2.market_data import TimeframeBarService
from crypto_trading_bot.research_v2.zigzag.classic import pivots_to_dicts
from crypto_trading_bot.research_v2.zigzag.match import align_chronological
from crypto_trading_bot.research_v2.zigzag.overlay import write_overlay_html
from crypto_trading_bot.research_v2.zigzag.search import (
    ZigZagParams,
    assess_stability,
    evaluate_params,
    grid_search,
    iter_absolute_grid,
    iter_atr_grid,
    iter_percent_grid,
    run_zigzag,
)


ANNOTATION_ID = "fc08e5a8-d633-4cf8-8dc3-6eb7928c4ff8"
DEFAULT_POINTS_CSV = Path("/var/tmp/expert_annotation_fc08e5a8_points.csv")
DEFAULT_OUT_DIR = Path("/var/tmp/traiding_pilot_ui_workspace/zigzag_reconstruction")


def _parse_ts(value: str) -> datetime:
    text = str(value).replace("Z", "+00:00")
    if text.endswith("+00"):
        text += ":00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def load_expert_points(csv_path: Path) -> list[dict]:
    rows: list[dict] = []
    with csv_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append(
                {
                    "annotation_id": row.get("annotation_id"),
                    "point_index": int(row["point_index"]),
                    "timestamp": row["timestamp"],
                    "price": float(row["price"]),
                    "snap_source": row.get("snap_source", "NONE"),
                }
            )
    rows.sort(key=lambda r: r["point_index"])
    return rows


def attach_bar_indices(expert_points: list[dict], candles: list[dict]) -> list[dict]:
    times = [_parse_ts(c["open_time_utc"]) for c in candles]
    out = []
    for p in expert_points:
        ts = _parse_ts(p["timestamp"])
        # Exact or nearest bar open.
        best_i = min(range(len(times)), key=lambda i: abs(times[i] - ts))
        row = dict(p)
        row["bar_index"] = best_i
        row["bar_timestamp"] = candles[best_i]["open_time_utc"]
        row["bar_time_error_hours"] = abs((times[best_i] - ts).total_seconds()) / 3600.0
        out.append(row)
    return out


def chronological_split(points: list[dict], discovery_frac: float = 0.70) -> tuple[list[dict], list[dict]]:
    n = len(points)
    cut = max(1, int(round(n * discovery_frac)))
    cut = min(cut, n - 1) if n > 1 else n
    return points[:cut], points[cut:]


def load_candles_for_experts(
    service: TimeframeBarService,
    expert_points: list[dict],
    timeframe: str = "4H",
    pad_days: int = 14,
) -> list[dict]:
    start = min(_parse_ts(p["timestamp"]) for p in expert_points) - timedelta(days=pad_days)
    end = max(_parse_ts(p["timestamp"]) for p in expert_points) + timedelta(days=pad_days)
    # Estimate bars needed.
    minutes = {"5m": 5, "15m": 15, "30m": 30, "1H": 60, "2H": 120, "4H": 240, "6H": 360, "8H": 480, "12H": 720, "1D": 1440}[
        timeframe
    ]
    span_minutes = (end - start).total_seconds() / 60.0
    limit = int(span_minutes / minutes) + 200
    limit = max(limit, 3000)
    candles = service.get_bars(timeframe, before=end + timedelta(minutes=minutes), after=start, limit=limit)
    # Filter to window.
    filtered = []
    for c in candles:
        ts = _parse_ts(c["open_time_utc"])
        if start <= ts <= end:
            filtered.append(c)
    return filtered or candles


def result_summary(result) -> dict[str, Any]:
    return result.to_dict()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classic ZigZag expert geometry reconstruction")
    parser.add_argument("--points-csv", type=Path, default=DEFAULT_POINTS_CSV)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--timeframe", default="4H")
    parser.add_argument("--discovery-frac", type=float, default=0.70)
    parser.add_argument("--max-bar-error", type=int, default=3)
    parser.add_argument("--max-price-error-pct", type=float, default=1.5)
    parser.add_argument("--skip-absolute", action="store_true")
    parser.add_argument("--skip-atr", action="store_true")
    parser.add_argument("--quick", action="store_true", help="Smaller percent grid for smoke test")
    args = parser.parse_args(argv)

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    expert = load_expert_points(args.points_csv)
    service = TimeframeBarService(
        symbol="ETHUSDT",
        canonical_root=Path("/srv/traiding_pilot/market/binance/spot/ETHUSDT/1m"),
        cache_root=Path("/var/tmp/traiding_pilot_market_cache"),
        ssh_host=os.environ.get("TRAIDING_PILOT_SSH_HOST", "wanga@s7"),
        ssh_key=Path(os.environ.get("TRAIDING_PILOT_SSH_KEY", "/home/sergey/.ssh/id_to_nyx")),
    )
    candles = load_candles_for_experts(service, expert, timeframe=args.timeframe)
    expert = attach_bar_indices(expert, candles)
    discovery, holdout = chronological_split(expert, args.discovery_frac)

    report: dict[str, Any] = {
        "wip": "CLASSIC-ZIGZAG-EXPERT-GEOMETRY-RECONSTRUCTION-1",
        "annotation_id": ANNOTATION_ID,
        "timeframe": args.timeframe,
        "expert_points": len(expert),
        "discovery_points": len(discovery),
        "holdout_points": len(holdout),
        "candle_count": len(candles),
        "match_tolerance": {
            "max_bar_error": args.max_bar_error,
            "max_price_error_pct": args.max_price_error_pct,
        },
    }

    def progress(i, params, result):
        print(f"[grid] {i} last={params.label()} f1={result.f1:.3f}", flush=True)

    if args.quick:
        percent_iter = iter_percent_grid(
            deviations=(1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0),
            depths=(1, 2, 3, 5, 8, 12, 16),
            backsteps=(0, 1, 2, 3, 5),
        )
    else:
        percent_iter = iter_percent_grid()

    print("Searching percent ZigZag grid on discovery...", flush=True)
    percent_ranked = grid_search(
        candles,
        discovery,
        percent_iter,
        max_bar_error=args.max_bar_error,
        max_price_error_pct=args.max_price_error_pct,
        on_progress=progress,
    )

    families = [("percent", percent_ranked)]
    if not args.skip_absolute:
        print("Searching absolute ZigZag grid on discovery...", flush=True)
        abs_ranked = grid_search(
            candles,
            discovery,
            iter_absolute_grid(),
            max_bar_error=args.max_bar_error,
            max_price_error_pct=args.max_price_error_pct,
            on_progress=progress,
        )
        families.append(("absolute", abs_ranked))
    if not args.skip_atr:
        print("Searching ATR ZigZag grid on discovery...", flush=True)
        atr_ranked = grid_search(
            candles,
            discovery,
            iter_atr_grid(),
            max_bar_error=args.max_bar_error,
            max_price_error_pct=args.max_price_error_pct,
            on_progress=progress,
        )
        families.append(("atr", atr_ranked))

    best_row = min((row for _, ranked in families for row in ranked[:1]), key=lambda r: r["score"])
    # Actually pick global best across all ranked first entries properly:
    all_top = []
    for name, ranked in families:
        if ranked:
            all_top.append(ranked[0])
    best_row = min(all_top, key=lambda r: r["score"])
    # Prefer classic percent when within a small F1 epsilon of the global best.
    percent_best = percent_ranked[0] if percent_ranked else None
    if percent_best is not None:
        if best_row["params"].kind != "percent":
            if (best_row["result"].f1 - percent_best["result"].f1) <= 0.02:
                best_row = percent_best
    best_params: ZigZagParams = best_row["params"]

    # Freeze and evaluate holdout + full.
    disc_result, disc_pivots = evaluate_params(
        candles,
        discovery,
        best_params,
        max_bar_error=args.max_bar_error,
        max_price_error_pct=args.max_price_error_pct,
    )
    hold_result, hold_pivots = evaluate_params(
        candles,
        holdout,
        best_params,
        max_bar_error=args.max_bar_error,
        max_price_error_pct=args.max_price_error_pct,
    )
    full_result, full_pivots = evaluate_params(
        candles,
        expert,
        best_params,
        max_bar_error=args.max_bar_error,
        max_price_error_pct=args.max_price_error_pct,
    )

    stability = assess_stability(
        candles,
        discovery,
        best_params,
        disc_result.f1,
        max_bar_error=args.max_bar_error,
        max_price_error_pct=args.max_price_error_pct,
    )

    overlay_path = write_overlay_html(
        out_dir / "overlay_expert_vs_zigzag.html",
        candles=candles,
        expert_points=expert,
        zigzag_pivots=full_pivots,
        match_pairs=full_result.pairs,
        title="Expert vs Classic ZigZag",
        params_label=best_params.label(),
    )

    sufficient = (
        hold_result.f1 >= 0.85
        and hold_result.median_bar_error is not None
        and hold_result.median_bar_error <= 2.0
        and hold_result.median_price_error_pct is not None
        and hold_result.median_price_error_pct <= 1.0
    )
    # Ready for wave dataset only if holdout quality passes; unstable params remain flagged.
    ready_waves = sufficient

    report.update(
        {
            "best_zigzag_type": best_params.kind,
            "best_deviation": best_params.deviation,
            "best_depth": best_params.depth,
            "best_backstep": best_params.backstep,
            "best_label": best_params.label(),
            "discovery": result_summary(disc_result),
            "holdout": result_summary(hold_result),
            "full": result_summary(full_result),
            "discovery_precision": disc_result.precision,
            "discovery_recall": disc_result.recall,
            "discovery_f1": disc_result.f1,
            "holdout_precision": hold_result.precision,
            "holdout_recall": hold_result.recall,
            "holdout_f1": hold_result.f1,
            "holdout_median_bar_error": hold_result.median_bar_error,
            "holdout_median_price_error_pct": hold_result.median_price_error_pct,
            "extra_pivots_holdout": hold_result.extra,
            "missed_pivots_holdout": hold_result.missed,
            "extra_pivots_full": full_result.extra,
            "missed_pivots_full": full_result.missed,
            "parameter_stability": stability["status"],
            "stability_detail": {
                "neighborhood_min_f1": stability["neighborhood_min_f1"],
                "neighborhood_max_f1": stability["neighborhood_max_f1"],
                "sample_count": len(stability["samples"]),
            },
            "visual_overlay_created": True,
            "visual_overlay_path": str(overlay_path),
            "classic_zigzag_sufficient": sufficient,
            "ready_to_generate_full_wave_dataset": ready_waves,
            "top_percent": [
                {
                    "label": r["label"],
                    "f1": r["result"].f1,
                    "precision": r["result"].precision,
                    "recall": r["result"].recall,
                    "median_bar_error": r["result"].median_bar_error,
                    "extra": r["result"].extra,
                    "zigzag_count": r["zigzag_count"],
                }
                for r in percent_ranked[:15]
            ],
            "family_best": {
                name: {
                    "label": ranked[0]["label"],
                    "f1": ranked[0]["result"].f1,
                    "precision": ranked[0]["result"].precision,
                    "recall": ranked[0]["result"].recall,
                }
                if ranked
                else None
                for name, ranked in families
            },
        }
    )

    # Persist artifacts (immutable expert not modified).
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    (out_dir / "best_params.json").write_text(
        json.dumps(
            {
                "kind": best_params.kind,
                "deviation": best_params.deviation,
                "depth": best_params.depth,
                "backstep": best_params.backstep,
                "frozen": sufficient,
                "engine": "ZIGZAG_GEOMETRY_ENGINE_V1" if sufficient else None,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (out_dir / "zigzag_pivots_full.json").write_text(
        json.dumps(pivots_to_dicts(full_pivots), indent=2),
        encoding="utf-8",
    )
    (out_dir / "match_full.json").write_text(
        json.dumps(
            {
                "pairs": full_result.pairs,
                "missed": full_result.missed_experts,
                "extra": full_result.extra_zigs,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    (out_dir / "stability.json").write_text(json.dumps(stability, indent=2), encoding="utf-8")

    print(json.dumps({k: report[k] for k in (
        "expert_points",
        "discovery_points",
        "holdout_points",
        "best_label",
        "discovery_f1",
        "holdout_f1",
        "holdout_median_bar_error",
        "holdout_median_price_error_pct",
        "parameter_stability",
        "classic_zigzag_sufficient",
        "visual_overlay_path",
    )}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
