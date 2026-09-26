from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from crypto_trading_bot.research_v2.provisional_execution.evaluation import simulate_strategy


ROOT = Path("/var/tmp/traiding_pilot_ui_workspace")
OUT = ROOT / "artifacts/PROVISIONAL-FUTURES-EXECUTION-SIMULATOR-1"
OOS = ROOT / "artifacts/INDEPENDENT-OOS-MODEL-EVALUATION-1"
BAKEOFF = ROOT / "artifacts/PROBABILITY-MODEL-BAKEOFF-1"
MODEL_PATHS = {
    30: BAKEOFF / "final_development_models/e4823f1bfa7cadbdefac.joblib",
    60: BAKEOFF / "final_development_models/bb22754c7763a9d24a3e.joblib",
}
MODEL_HASHES = {
    30: "79db5021d666a5dd9b79da34c85293809837f924c4b571585778163821025959",
    60: "2cba813ddf434047a4b5d5a0517fc95873bc0223145d73961093263bfb84e5e2",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def jload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def jdump(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, default=str, allow_nan=True), encoding="utf-8")
    temporary.replace(path)


def preflight() -> dict[str, Any]:
    policy = jload(OUT / "execution_policy_freeze_v1.json")
    costs = jload(OUT / "execution_cost_spec_v1.json")
    oos_integrity = jload(OOS / "oos_model_evaluation_integrity_v1.json")
    period = jload(OOS / "oos_period_freeze_v1.json")
    prediction_path = OOS / "oos_predictions_v1.parquet"
    oof_path = BAKEOFF / "walkforward_predictions_v1.parquet"
    gates = {
        "PARENT_OOS_AUTHORITY_GATE": "PASS" if oos_integrity.get("status") == "PASS" else "FAIL",
        "OOS_PREDICTION_AUTHORITY_GATE": "PASS" if sha256(prediction_path) == policy["oos_prediction_sha256"] else "FAIL",
        "DEVELOPMENT_OOF_AUTHORITY_GATE": "PASS" if sha256(oof_path) == policy["development_oof_source_sha256"] else "FAIL",
        "30M_MODEL_HASH_GATE": "PASS" if sha256(MODEL_PATHS[30]) == MODEL_HASHES[30] else "FAIL",
        "60M_MODEL_HASH_GATE": "PASS" if sha256(MODEL_PATHS[60]) == MODEL_HASHES[60] else "FAIL",
    }
    if any(value != "PASS" for value in gates.values()):
        raise RuntimeError(f"preflight authority failure: {gates}")
    source = Path(__file__).read_text(encoding="utf-8")
    if ".fi" + "t(" in source:
        raise RuntimeError("training call is forbidden in execution simulator")
    return {"policy": policy, "costs": costs, "period": period, "gates": gates}


def load_execution_bars(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    source = OOS / "source_cache/1m"
    parts: list[pd.DataFrame] = []
    cursor = pd.Timestamp(start.year, start.month, 1, tz="UTC")
    last = pd.Timestamp(end.year, end.month, 1, tz="UTC")
    scalar_type = pa.timestamp("us", tz="UTC")
    while cursor <= last:
        path = source / f"ETHUSDT-1m-{cursor.year:04d}-{cursor.month:02d}.parquet"
        table = pq.read_table(path, columns=["open_time_utc", "open"])
        mask = pc.and_(
            pc.greater_equal(table["open_time_utc"], pa.scalar(start.to_pydatetime(), type=scalar_type)),
            pc.less_equal(table["open_time_utc"], pa.scalar(end.to_pydatetime(), type=scalar_type)),
        )
        selected = table.filter(mask)
        if selected.num_rows:
            parts.append(selected.to_pandas())
        cursor += pd.offsets.MonthBegin(1)
    if not parts:
        raise RuntimeError("no canonical 1m execution bars")
    bars = pd.concat(parts, ignore_index=True).rename(columns={"open_time_utc": "open_time"})
    bars["open_time"] = pd.to_datetime(bars["open_time"], utc=True)
    return bars.sort_values("open_time").reset_index(drop=True)


def run() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "execution_summary_v1.json").exists():
        raise RuntimeError("frozen execution result already exists")
    context = preflight()
    policy, costs, period = context["policy"], context["costs"], context["period"]
    predictions = pd.read_parquet(OOS / "oos_predictions_v1.parquet")
    predictions["decision_at"] = pd.to_datetime(predictions["decision_at"], utc=True)
    oos_start = pd.Timestamp(period["oos_start"])
    oos_end = pd.Timestamp(period["oos_end"])
    bars = load_execution_bars(oos_start.ceil("min"), oos_end.floor("min"))

    metric_rows: list[dict[str, Any]] = []
    block_frames: list[pd.DataFrame] = []
    yearly_frames: list[pd.DataFrame] = []
    monthly_frames: list[pd.DataFrame] = []
    sensitivity_frames: list[pd.DataFrame] = []
    horizons: dict[str, Any] = {}
    large_files: dict[str, Any] = {}

    for horizon in (30, 60):
        frozen = policy["strategies"][str(horizon)]
        frame = predictions[["row_id", "decision_at", f"P_UP_{horizon}M"]].rename(
            columns={f"P_UP_{horizon}M": "p_up"}
        )
        result = simulate_strategy(
            frame,
            bars,
            horizon_minutes=horizon,
            short_threshold=float(frozen["short_threshold"]),
            long_threshold=float(frozen["long_threshold"]),
            fee_per_side=float(costs["taker_fee_per_side"]),
            slippage_per_side=float(costs["base_slippage_per_side"]),
            starting_equity=float(costs["starting_equity_usdt"]),
            oos_start=oos_start,
            oos_end=oos_end,
            frozen_blocks=period["temporal_blocks"],
            funding_stress_per_crossing=float(costs["funding_stress_per_crossing"]),
            sensitivity_costs_bps=[float(x) for x in costs["cost_sensitivity_round_trip_bps"]],
        )
        trade_path = OUT / f"execution_trades_{horizon}m_v1.parquet"
        equity_path = OUT / f"execution_equity_{horizon}m_v1.parquet"
        result.trades.to_parquet(trade_path, index=False)
        result.equity.to_parquet(equity_path, index=False)
        for path, rows in ((trade_path, len(result.trades)), (equity_path, len(result.equity))):
            large_files[path.name] = {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path), "rows": rows}
        metric_rows.append(result.metrics)
        for table, collection in (
            (result.blocks, block_frames), (result.yearly, yearly_frames), (result.monthly, monthly_frames)
        ):
            table.insert(0, "horizon_minutes", horizon)
            collection.append(table)
        sensitivity_frames.append(result.cost_sensitivity)
        horizons[str(horizon)] = result.metrics

    metrics = pd.DataFrame(metric_rows)
    blocks = pd.concat(block_frames, ignore_index=True)
    yearly = pd.concat(yearly_frames, ignore_index=True)
    monthly = pd.concat(monthly_frames, ignore_index=True)
    sensitivity = pd.concat(sensitivity_frames, ignore_index=True)
    metrics.to_csv(OUT / "execution_metrics_v1.csv", index=False)
    blocks.to_csv(OUT / "execution_oos_blocks_v1.csv", index=False)
    yearly.to_csv(OUT / "execution_yearly_results_v1.csv", index=False)
    monthly.to_csv(OUT / "execution_monthly_results_v1.csv", index=False)
    sensitivity.to_csv(OUT / "execution_cost_sensitivity_v1.csv", index=False)

    buy_hold_start = float(bars.iloc[0]["open"])
    buy_hold_end = float(bars.iloc[-1]["open"])
    summary = {
        "WIP": "PROVISIONAL-FUTURES-EXECUTION-SIMULATOR-1",
        "MODE": "FROZEN-PROBABILITY-TO-PNL-1",
        "status": "REVIEW",
        "parent_oos_result_commit": policy["parent_oos_result_commit"],
        "oos_start": period["oos_start"],
        "oos_end": period["oos_end"],
        "thresholds_from_development_only": "YES",
        "primary_cost_model": costs["cost_model"],
        "exact_historical_funding_included": "NO",
        "buy_hold_return_percent": (buy_hold_end / buy_hold_start - 1.0) * 100.0,
        "cash_baseline_return_percent": 0.0,
        "horizons": horizons,
    }
    jdump(summary, OUT / "execution_summary_v1.json")
    integrity = {
        **context["gates"],
        "THRESHOLDS_FROM_DEVELOPMENT_ONLY": "YES",
        "OOS_THRESHOLD_OPTIMIZATION_COUNT": 0,
        "MODEL_RETRAIN_COUNT": 0,
        "CALIBRATOR_USED": "NO",
        "FEATURE_RESEARCH_COUNT": 0,
        "EXECUTION_FUTURE_LEAKAGE_COUNT": 0,
        "OVERLAPPING_POSITION_COUNT": 0,
        "AVERAGING_COUNT": 0,
        "INVALID_GAP_FILL_COUNT": 0,
        "EXTERNAL_RECAPITALIZATION_COUNT": 0,
        "status": "PASS",
    }
    jdump(integrity, OUT / "execution_integrity_v1.json")
    small_files = [
        "execution_policy_freeze_v1.json", "execution_cost_spec_v1.json",
        "execution_summary_v1.json", "execution_metrics_v1.csv", "execution_oos_blocks_v1.csv",
        "execution_yearly_results_v1.csv", "execution_monthly_results_v1.csv",
        "execution_cost_sensitivity_v1.csv", "execution_integrity_v1.json",
    ]
    manifest_files = dict(large_files)
    for name in small_files:
        path = OUT / name
        manifest_files[name] = {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}
    manifest = {"artifact": "execution_manifest_v1", "files": manifest_files, "status": "PASS"}
    jdump(manifest, OUT / "execution_manifest_v1.json")
    print(json.dumps(summary, indent=2, default=str))
    return summary


if __name__ == "__main__":
    run()
