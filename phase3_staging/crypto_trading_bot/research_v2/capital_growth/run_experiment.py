from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from .config import RUN1_END, RUN1_START, RUN2_END, RUN2_START, portfolio_matrix
from .data import prepare_dataset
from .simulator import SimulationResult, simulate_portfolio
from .strategy import build_decision_frame, execution_events


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, default=str, allow_nan=True), encoding="utf-8")
    temporary.replace(path)


def frozen_configuration() -> dict[str, Any]:
    return {
        "version": "CAPITAL_GROWTH_EXPERIMENT_CONFIG_V1",
        "run1": {"start": RUN1_START.isoformat(), "end": RUN1_END.isoformat()},
        "run2": {"start": RUN2_START.isoformat(), "end": RUN2_END.isoformat()},
        "portfolios": [asdict(config) for config in portfolio_matrix()],
        "strategy_rule": "LONG when close>SMA20>SMA50; SHORT when close<SMA20<SMA50",
        "hedge_rule": "opposite confirmed trend after adverse excursion >= 2 ATR; size by risk",
        "averaging_rule": "at 2 and 4 ATR adverse while thesis trend persists; max twice",
        "exit_rule": "opposite trend after minimum 72h or end of run",
        "data_policy": "Binance public spot/futures/mark/funding data only; no OOS",
    }


def freeze_config(root: Path) -> str:
    path = root / "frozen_config_v1.json"
    if path.exists():
        raise RuntimeError("configuration freeze already exists")
    write_json(path, frozen_configuration())
    return sha256_file(path)


def verify_freeze(root: Path, expected_sha: str) -> None:
    path = root / "frozen_config_v1.json"
    if not path.is_file():
        raise RuntimeError("RUN 2 blocked: frozen_config_v1.json missing")
    actual = sha256_file(path)
    if actual != expected_sha:
        raise RuntimeError(f"RUN 2 blocked: config SHA mismatch expected={expected_sha} actual={actual}")


def _run_stage(
    *,
    frame: pd.DataFrame,
    funding: pd.DataFrame,
    stage_root: Path,
) -> list[SimulationResult]:
    decisions = build_decision_frame(frame)
    events = execution_events(decisions, frame["open_time"])
    results: list[SimulationResult] = []
    metrics = []
    for config in portfolio_matrix():
        result = simulate_portfolio(frame, funding, events, config)
        result_dir = stage_root / config.name
        result_dir.mkdir(parents=True, exist_ok=True)
        result.trades.to_csv(result_dir / "trades.csv", index=False)
        result.events.to_csv(result_dir / "events.csv", index=False)
        result.equity.to_parquet(result_dir / "equity.parquet", index=False)
        write_json(result_dir / "metrics.json", result.metrics)
        results.append(result)
        metrics.append(result.metrics)
    pd.DataFrame(metrics).to_csv(stage_root / "portfolio_metrics.csv", index=False)
    _plot_equity(results, stage_root / "equity_curves.png")
    return results


def _plot_equity(results: list[SimulationResult], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.figure(figsize=(14, 8))
    for result in results:
        plt.plot(result.equity["time"], result.equity["equity"], label=result.portfolio, linewidth=1)
    plt.axhline(100.0, color="grey", linestyle="--", linewidth=1)
    plt.yscale("symlog")
    plt.ylabel("Portfolio equity, USDT")
    plt.legend(ncol=2, fontsize=7)
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()


def _comparison(results: list[SimulationResult]) -> dict[str, Any]:
    by_name = {result.portfolio: result.metrics for result in results}
    comparisons = {}
    for result in results:
        if not result.portfolio.endswith("HEDGED_AVG"):
            continue
        prefix = result.portfolio.removesuffix("HEDGED_AVG")
        unhedged = by_name.get(prefix + "UNHEDGED_AVG")
        noavg = by_name.get(prefix + "HEDGED_NOAVG")
        if unhedged:
            comparisons[result.portfolio] = {
                "beats_unhedged": result.metrics["final_equity"] > unhedged["final_equity"],
                "unhedged_final_equity": unhedged["final_equity"],
                "liquidations_prevented": unhedged["liquidation_count"] - result.metrics["liquidation_count"],
                "hedged_return_percent": result.metrics["return_percent"],
                "unhedged_return_percent": unhedged["return_percent"],
            }
            if noavg:
                comparisons[result.portfolio]["averaging_effect_usdt"] = (
                    result.metrics["final_equity"] - noavg["final_equity"]
                )
    return comparisons


def run_experiment(
    *,
    data_root: Path,
    spot_cache_root: Path,
    download: bool = False,
) -> dict[str, Any]:
    data_root = Path(data_root)
    stage_data = data_root / "data"
    run1_root = data_root / "RUN1_DISCOVERY"
    run2_root = data_root / "RUN2_VALIDATION"
    frame, funding, preflight = prepare_dataset(
        spot_cache_root=Path(spot_cache_root),
        data_root=stage_data,
        start=RUN1_START,
        end=RUN2_END,
        download=download,
    )
    write_json(stage_data / "data_preflight_v1.json", preflight)
    if preflight["status"] != "PASS":
        blockers = {"stage": "RUN1", "status": "BLOCKED", "preflight": preflight}
        write_json(data_root / "run_blocker_v1.json", blockers)
        return blockers

    run1_frame = frame[(frame["open_time"] >= pd.Timestamp(RUN1_START)) & (frame["open_time"] < pd.Timestamp(RUN1_END))].copy()
    if run1_frame.empty:
        raise RuntimeError("RUN 1 frame empty")
    run1_results = _run_stage(frame=run1_frame, funding=funding, stage_root=run1_root)
    config_sha = freeze_config(data_root)
    verify_freeze(data_root, config_sha)

    run2_frame = frame[(frame["open_time"] >= pd.Timestamp(RUN2_START)) & (frame["open_time"] < pd.Timestamp(RUN2_END))].copy()
    if run2_frame.empty:
        raise RuntimeError("RUN 2 frame empty")
    run2_results = _run_stage(frame=run2_frame, funding=funding, stage_root=run2_root)

    comparisons = {
        "run1": _comparison(run1_results),
        "run2": _comparison(run2_results),
    }
    write_json(data_root / "control_comparisons_v1.json", comparisons)
    summary = {
        "WIP": "TRADING-PILOT-CAPITAL-GROWTH-EXPERIMENT-1",
        "status": "REVIEW",
        "CONFIG_SHA": config_sha,
        "RUN1": {
            "start": RUN1_START.isoformat(),
            "end": RUN1_END.isoformat(),
            "portfolios": {r.portfolio: r.metrics for r in run1_results},
        },
        "RUN2": {
            "start": RUN2_START.isoformat(),
            "end": RUN2_END.isoformat(),
            "portfolios": {r.portfolio: r.metrics for r in run2_results},
        },
        "comparisons": comparisons,
        "data_preflight": preflight,
        "OOS_OPENED": "NO",
        "LIVE_TRADING": "NO",
    }
    write_json(data_root / "summary_v1.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("/var/tmp/traiding_pilot_ui_workspace/capital_growth_experiment_v1"),
    )
    parser.add_argument(
        "--spot-cache-root",
        type=Path,
        default=Path("/var/tmp/traiding_pilot_market_cache"),
    )
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    summary = run_experiment(
        data_root=args.data_root,
        spot_cache_root=args.spot_cache_root,
        download=args.download,
    )
    print(json.dumps(summary, indent=2, default=str))
    return 0 if summary.get("status") != "BLOCKED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
