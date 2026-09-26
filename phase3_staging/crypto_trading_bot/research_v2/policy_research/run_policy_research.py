from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import multiprocessing as mp
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from crypto_trading_bot.research_v2.policy_research.evaluation import (
    discovery_eligible,
    simulate_policy,
    validation_eligible,
)


ROOT = Path("/var/tmp/traiding_pilot_ui_workspace")
OUT = ROOT / "artifacts/PROBABILITY-TRADING-POLICY-RESEARCH-1"
BAKEOFF = ROOT / "artifacts/PROBABILITY-MODEL-BAKEOFF-1"
DATASET = ROOT / "artifacts/PROBABILITY-MODEL-TRAINING-DATASET-1/full_v2"
OOF = BAKEOFF / "walkforward_predictions_v1.parquet"
ROW_INDEX = DATASET / "training_row_index_v2.parquet"
PRICES = OUT / "source_cache/development_1m_open_v1.parquet"
OOF_SHA256 = "dc3c90f88513a5023299ae6b19d9b8cef102c65d0cfcc402a153cf44f698b862"

_DECISIONS: pd.DataFrame | None = None
_OPENS: pd.Series | None = None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def jdump(value: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, default=str, allow_nan=True), encoding="utf-8")
    temporary.replace(path)


def load_stage(fold: str) -> pd.DataFrame:
    filters = [
        ("family", "==", "CATBOOST"), ("feature_set", "==", "FS_FULL"),
        ("wfv", "==", fold), ("horizon_minutes", "in", [30, 60]),
    ]
    pred = pd.read_parquet(OOF, filters=filters)
    left = pred[pred.horizon_minutes == 30][["row_id", "wfv", "p_up"]].rename(columns={"p_up": "p30"})
    right = pred[pred.horizon_minutes == 60][["row_id", "wfv", "p_up"]].rename(columns={"p_up": "p60"})
    aligned = left.merge(right, on=["row_id", "wfv"], how="inner", validate="one_to_one")
    index = pd.read_parquet(ROW_INDEX, columns=["row_id", "decision_at"])
    aligned = aligned.merge(index, on="row_id", how="left", validate="one_to_one")
    if aligned[["p30", "p60", "decision_at"]].isna().any().any():
        raise RuntimeError("invalid aligned OOF rows")
    return aligned.sort_values(["decision_at", "row_id"]).reset_index(drop=True)


def load_opens(start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    bars = pd.read_parquet(PRICES, columns=["open_time_utc", "open"])
    bars["open_time_utc"] = pd.to_datetime(bars["open_time_utc"], utc=True)
    bars = bars[(bars.open_time_utc >= start.floor("min")) & (bars.open_time_utc <= end.ceil("min"))]
    if bars.open_time_utc.duplicated().any():
        raise RuntimeError("duplicate canonical 1m bars")
    return pd.Series(bars.open.to_numpy(dtype=np.float64), index=bars.open_time_utc)


def thresholds(discovery: pd.DataFrame) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for quantile in (0.95, 0.975, 0.99, 0.995):
        result[str(quantile)] = {
            "long_threshold_30m": float(discovery.p30.quantile(quantile, interpolation="linear")),
            "short_threshold_30m": float(discovery.p30.quantile(1.0 - quantile, interpolation="linear")),
            "long_threshold_60m": float(discovery.p60.quantile(quantile, interpolation="linear")),
            "short_threshold_60m": float(discovery.p60.quantile(1.0 - quantile, interpolation="linear")),
        }
    return result


def candidate_grid(frozen_thresholds: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
    rows = []
    values = itertools.product(
        ("30M_ONLY", "60M_ONLY", "BOTH_AGREE"),
        (0.95, 0.975, 0.99, 0.995), (1, 2), (0, 60, 240),
        ("NEUTRAL_CROSS", "REVERSE_THRESHOLD", "CONFIDENCE_LOSS"),
        (15, 30), (60, 120, 240, 480),
    )
    for number, (source, quantile, persistence, cooldown, exit_family, minimum, maximum) in enumerate(values, 1):
        rows.append({
            "candidate_id": f"POLICY-{number:04d}", "entry_source": source,
            "confidence_quantile": quantile, **frozen_thresholds[str(quantile)],
            "entry_persistence_decisions": persistence, "cooldown_minutes": cooldown,
            "exit_family": exit_family, "minimum_hold_minutes": minimum,
            "maximum_hold_minutes": maximum,
        })
    if len(rows) != 1728:
        raise RuntimeError("candidate grid is not exactly 1728")
    return rows


def _initialize(frame: pd.DataFrame, opens: pd.Series) -> None:
    global _DECISIONS, _OPENS
    _DECISIONS, _OPENS = frame, opens


def _score(candidate: dict[str, Any]) -> dict[str, Any]:
    assert _DECISIONS is not None and _OPENS is not None
    return simulate_policy(_DECISIONS, _OPENS, candidate).metrics


def score_many(frame: pd.DataFrame, opens: pd.Series, candidates: list[dict[str, Any]], workers: int) -> pd.DataFrame:
    context = mp.get_context("fork")
    with context.Pool(workers, initializer=_initialize, initargs=(frame, opens)) as pool:
        rows = list(pool.imap(_score, candidates, chunksize=max(1, len(candidates) // (workers * 8))))
    return pd.DataFrame(rows)


def rank(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.sort_values(
        ["arithmetic_net_expectancy_bps_per_trade", "profit_factor", "max_drawdown_percent", "trade_count"],
        ascending=[False, False, True, False], kind="mergesort",
    ).reset_index(drop=True)


def run_search(workers: int) -> dict[str, Any]:
    if sha256(OOF) != OOF_SHA256:
        raise RuntimeError("DEVELOPMENT OOF SHA256 mismatch")
    discovery = load_stage("WFV_1")
    validation = load_stage("WFV_2")
    frozen_thresholds = thresholds(discovery)
    candidates = candidate_grid(frozen_thresholds)
    discovery_opens = load_opens(discovery.decision_at.min(), discovery.decision_at.max() + pd.Timedelta(minutes=1))
    discovery_results = score_many(discovery, discovery_opens, candidates, workers)
    discovery_results["eligible"] = discovery_results.apply(lambda row: discovery_eligible(row.to_dict()), axis=1)
    discovery_results.to_parquet(OUT / "policy_discovery_results_v1.parquet", index=False)
    eligible = rank(discovery_results[discovery_results.eligible]).head(20).copy()
    eligible.insert(0, "discovery_rank", range(1, len(eligible) + 1))
    eligible.to_csv(OUT / "policy_discovery_top20_v1.csv", index=False)

    top_candidates = [next(item for item in candidates if item["candidate_id"] == cid) for cid in eligible.candidate_id]
    validation_opens = load_opens(validation.decision_at.min(), validation.decision_at.max() + pd.Timedelta(minutes=1))
    validation_results = score_many(validation, validation_opens, top_candidates, workers) if top_candidates else pd.DataFrame()
    if not validation_results.empty:
        validation_results["eligible"] = validation_results.apply(lambda row: validation_eligible(row.to_dict()), axis=1)
        validation_results = rank(validation_results)
    validation_results.to_csv(OUT / "policy_validation_results_v1.csv", index=False)
    survivors = validation_results[validation_results.eligible].copy() if not validation_results.empty else pd.DataFrame()

    payload: dict[str, Any] = {
        "discovery_candidates": 1728, "discovery_eligible": int(discovery_results.eligible.sum()),
        "discovery_retained": int(len(eligible)), "validation_evaluated": int(len(validation_results)),
        "validation_eligible": int(len(survivors)), "selected_policy_exists": "YES" if len(survivors) else "NO",
        "policy_research_result": "VALIDATED_POLICY_SELECTED" if len(survivors) else "NO_VALIDATED_POLICY",
        "confirmation_touched": "NO", "confirmation_run_count": 0,
    }
    jdump(frozen_thresholds, OUT / "policy_discovery_thresholds_v1.json")
    if len(survivors):
        winner_id = str(survivors.iloc[0].candidate_id)
        winner = next(item for item in candidates if item["candidate_id"] == winner_id).copy()
        winner["fee_per_side"] = 0.00055
        winner["slippage_per_side"] = 0.00010
        winner["discovery_metrics"] = discovery_results[discovery_results.candidate_id == winner_id].iloc[0].to_dict()
        winner["validation_metrics"] = survivors.iloc[0].to_dict()
        canonical = json.dumps(winner, sort_keys=True, separators=(",", ":"), default=str).encode()
        winner["sha256"] = hashlib.sha256(canonical).hexdigest()
        jdump(winner, OUT / "policy_candidate_freeze_v1.json")
        payload["selected_candidate_id"] = winner_id
    jdump(payload, OUT / "policy_search_summary_v1.json")
    print(json.dumps(payload, indent=2))
    return payload


def run_confirmation(freeze_commit: str) -> dict[str, Any]:
    freeze_path = OUT / "policy_candidate_freeze_v1.json"
    if not freeze_path.exists():
        raise RuntimeError("no frozen validated policy")
    marker = OUT / "confirmation_run_marker_v1.json"
    if marker.exists():
        raise RuntimeError("confirmation was already attempted")
    jdump({"confirmation_run_count": 1, "policy_freeze_commit": freeze_commit}, marker)
    candidate = json.loads(freeze_path.read_text(encoding="utf-8"))
    confirmation = load_stage("WFV_3")
    opens = load_opens(confirmation.decision_at.min(), pd.Timestamp("2023-06-20T06:08:00Z"))
    result = simulate_policy(confirmation, opens, candidate)
    result.trades.to_parquet(OUT / "policy_confirmation_trades_v1.parquet", index=False)
    result.equity.to_parquet(OUT / "policy_confirmation_equity_v1.parquet", index=False)
    metrics = result.metrics
    boundaries = [
        pd.Timestamp("2022-06-10T04:44:59.999999Z"), pd.Timestamp("2022-10-13T04:49:59.999999Z"),
        pd.Timestamp("2023-02-15T04:54:59.999999Z"), pd.Timestamp("2023-06-20T05:00:00Z"),
    ]
    blocks = []
    for number in range(3):
        trades = result.trades[(result.trades.signal_decision_at >= boundaries[number]) & (result.trades.signal_decision_at < boundaries[number + 1])]
        raw = trades.gross_return.to_numpy(dtype=float)
        net = trades.net_return.to_numpy(dtype=float)
        gross = (100 * np.prod(1 + raw) - 100) if len(raw) else 0.0
        net_return = (100 * np.prod(1 + net) - 100) if len(net) else 0.0
        gains, losses = net[net > 0].sum(), -net[net < 0].sum()
        pf = float(gains / losses) if losses else (float("inf") if gains else float("nan"))
        from crypto_trading_bot.research_v2.policy_research.evaluation import break_even_cost_bps
        blocks.append({"block": number + 1, "trades": len(trades), "gross_return_percent": gross, "net_return_percent": net_return, "profit_factor": pf, "break_even_cost_bps": break_even_cost_bps(raw)})
    block_frame = pd.DataFrame(blocks)
    block_frame.to_csv(OUT / "policy_confirmation_blocks_v1.csv", index=False)
    supported = bool(metrics["trade_count"] >= 30 and metrics["gross_return_percent"] > 0 and metrics["net_return_percent"] > 0 and metrics["arithmetic_net_expectancy_bps_per_trade"] > 0 and metrics["profit_factor"] > 1 and metrics["break_even_round_trip_cost_bps"] >= 13 and (block_frame.net_return_percent > 0).sum() >= 2 and metrics["account_ruined"] == "NO")
    policy_class = "POLICY_DEV_SUPPORTED" if supported else "POLICY_DEV_WEAK" if metrics["gross_return_percent"] > 0 else "POLICY_DEV_NOT_SUPPORTED"
    metrics["policy_dev_class"] = policy_class
    metrics["policy_freeze_commit"] = freeze_commit
    jdump(metrics, OUT / "policy_confirmation_metrics_v1.json")
    sensitivity = []
    raw = result.trades.gross_return.to_numpy(dtype=float)
    for cost in (0, 5, 10, 13, 20, 30):
        ending = 100.0 * np.prod(1 + raw - cost / 10000.0)
        sensitivity.append({"round_trip_cost_bps": cost, "ending_equity_normalized_100": ending, "net_return_percent": ending - 100.0})
    pd.DataFrame(sensitivity).to_csv(OUT / "policy_cost_sensitivity_v1.csv", index=False)
    print(json.dumps({"policy_dev_class": policy_class, **metrics}, indent=2, default=str))
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["search", "confirmation"])
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--freeze-commit")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.stage == "search":
        run_search(args.workers)
    else:
        if not args.freeze_commit:
            parser.error("--freeze-commit is required")
        run_confirmation(args.freeze_commit)


if __name__ == "__main__":
    main()
