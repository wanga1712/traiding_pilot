from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import multiprocessing as mp
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from .config import RUN1_END, RUN1_START, RUN2_END, RUN2_START, portfolio_matrix
from .data import prepare_dataset
from .simulator import SimulationResult, simulate_portfolio
from .strategy import build_decision_frame, execution_events


_WORK_FRAME: pd.DataFrame | None = None
_WORK_FUNDING: pd.DataFrame | None = None
_WORK_EVENTS: list[tuple[int, dict]] | None = None


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
    global _WORK_FRAME, _WORK_FUNDING, _WORK_EVENTS
    decisions = build_decision_frame(frame)
    events = execution_events(decisions, frame["open_time"])
    configs = portfolio_matrix()
    workers = min(6, max(1, (os.cpu_count() or 1) - 1))
    _WORK_FRAME, _WORK_FUNDING, _WORK_EVENTS = frame, funding, events
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=workers,
        mp_context=mp.get_context("fork"),
    ) as pool:
        stage_results = list(pool.map(_run_config_worker, configs))
    results: list[SimulationResult] = []
    metrics = []
    for result in stage_results:
        result_dir = stage_root / result.portfolio
        result_dir.mkdir(parents=True, exist_ok=True)
        result.trades.to_csv(result_dir / "trades.csv", index=False)
        result.events.to_csv(result_dir / "events.csv", index=False)
        result.equity.to_parquet(result_dir / "equity.parquet", index=False)
        write_json(result_dir / "metrics.json", result.metrics)
        results.append(result)
        metrics.append(result.metrics)
    pd.DataFrame(metrics).to_csv(stage_root / "portfolio_metrics.csv", index=False)
    _write_journals(results, stage_root)
    _plot_equity(results, stage_root / "equity_curves.png")
    return results


def _run_config_worker(config) -> SimulationResult:
    assert _WORK_FRAME is not None and _WORK_FUNDING is not None and _WORK_EVENTS is not None
    return simulate_portfolio(_WORK_FRAME, _WORK_FUNDING, _WORK_EVENTS, config)


def _write_journals(results: list[SimulationResult], stage_root: Path) -> None:
    trade_frames = []
    event_frames = []
    for result in results:
        if not result.trades.empty:
            trades = result.trades.copy()
            trades.insert(0, "portfolio", result.portfolio)
            trade_frames.append(trades)
        if not result.events.empty:
            events = result.events.copy()
            events.insert(0, "portfolio", result.portfolio)
            event_frames.append(events)
        _plot_role_pnl(result, stage_root / result.portfolio / "primary_hedge_pnl.png")
    if trade_frames:
        pd.concat(trade_frames, ignore_index=True, sort=False).to_csv(stage_root / "all_trades.csv", index=False)
    if event_frames:
        pd.concat(event_frames, ignore_index=True, sort=False).to_csv(stage_root / "all_events.csv", index=False)


def _plot_role_pnl(result: SimulationResult, path: Path) -> None:
    if result.trades.empty:
        return
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.figure(figsize=(10, 4))
    for role, color in (("PRIMARY", "#42a5f5"), ("HEDGE", "#ef5350")):
        frame = result.trades[result.trades["role"] == role].copy()
        if frame.empty:
            continue
        frame["exit_time"] = pd.to_datetime(frame["exit_time"], utc=True)
        frame = frame.sort_values("exit_time")
        frame["cumulative_net_pnl"] = frame["net_pnl"].cumsum()
        plt.step(frame["exit_time"], frame["cumulative_net_pnl"], where="post", label=role, color=color)
    plt.axhline(0.0, color="grey", linewidth=1)
    plt.ylabel("Cumulative net PnL, USDT")
    plt.legend()
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()


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


def _write_artifact_manifest(root: Path) -> dict[str, Any]:
    manifest_path = root / "artifact_manifest_v1.json"
    files = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path == manifest_path:
            continue
        if "INVALIDATED_" in path.as_posix():
            continue
        files[str(path.relative_to(root))] = {
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    manifest = {"version": "CAPITAL_GROWTH_ARTIFACT_MANIFEST_V1", "files": files, "file_count": len(files)}
    write_json(manifest_path, manifest)
    return manifest


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
    all_results = {"RUN1": run1_results, "RUN2": run2_results}
    hedged_wins = sum(
        int(row.get("beats_unhedged", False))
        for stage in comparisons.values()
        for row in stage.values()
    )
    liquidations_prevented = sum(
        int(row.get("liquidations_prevented", 0))
        for stage in comparisons.values()
        for row in stage.values()
    )
    best = {}
    for stage_name, stage_results in all_results.items():
        winner = max(stage_results, key=lambda result: result.metrics["final_equity"])
        best[stage_name] = {
            "portfolio": winner.portfolio,
            "final_equity": winner.metrics["final_equity"],
            "buy_hold_equivalent": 100.0 * (1.0 + winner.metrics["buy_hold_return"]),
        }
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
        "decision": {
            "HEDGED_BEATS_UNHEDGED_COUNT": hedged_wins,
            "HEDGED_COMPARISON_COUNT": sum(len(stage) for stage in comparisons.values()),
            "NET_LIQUIDATIONS_PREVENTED": liquidations_prevented,
            "BEST_BY_RUN": best,
            "BEATS_BUY_AND_HOLD": all(
                row["final_equity"] > row["buy_hold_equivalent"] for row in best.values()
            ),
        },
        "data_preflight": preflight,
        "OOS_OPENED": "NO",
        "LIVE_TRADING": "NO",
    }
    write_json(data_root / "summary_v1.json", summary)
    _write_artifact_manifest(data_root)
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
