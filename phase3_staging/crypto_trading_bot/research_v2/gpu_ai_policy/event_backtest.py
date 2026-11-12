from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, CatBoostRegressor

from .backtest import _run_policy
from .config import (
    MAX_THESIS_LOSS_FRACTION,
    RUN1_END,
    RUN1_START,
    RUN2_END,
    RUN2_START,
    SPOT_FRACTIONS,
)
from .event_monitor import EventConfig, EventMonitor
from .qwen_adapter import QwenConfig, QwenPolicyAdapter
from .train import ACTION_NAMES, build_matrix, load_bundle


def _load_minute_hour_features(path: Path) -> pd.DataFrame:
    minute = pd.read_parquet(
        path,
        columns=[
            "open_time",
            "futures_open",
            "futures_high",
            "futures_low",
            "futures_close",
            "mark_open",
            "mark_high",
            "mark_low",
            "mark_close",
        ],
    )
    minute["open_time"] = pd.to_datetime(minute["open_time"], utc=True)
    minute["hour"] = minute["open_time"].dt.floor("1h")
    grouped = (
        minute.groupby("hour", sort=True)
        .agg(
            futures_open=("futures_open", "first"),
            minute_high=("mark_high", "max"),
            minute_low=("mark_low", "min"),
            minute_close=("mark_close", "last"),
            mark_open=("mark_open", "first"),
            futures_high=("futures_high", "max"),
            futures_low=("futures_low", "min"),
            futures_close=("futures_close", "last"),
            minute_count=("open_time", "count"),
        )
        .reset_index()
    )
    return grouped


def _context(
    dataset_root: Path,
    training_root: Path,
    minute_path: Path,
    funding_path: Path,
) -> dict[str, Any]:
    bundle = load_bundle(dataset_root)
    metrics = json.loads((training_root / "training_metrics_v1.json").read_text())
    selection = json.loads(
        (training_root / "feature_selection_manifest_v1.json").read_text()
    )
    entry_model = CatBoostClassifier()
    entry_model.load_model(training_root / "entry_direction_gpu_v1.cbm")
    risk_model = CatBoostRegressor()
    risk_model.load_model(training_root / "entry_risk_gpu_v1.cbm")
    management_model = CatBoostClassifier()
    management_model.load_model(training_root / "position_management_gpu_v1.cbm")
    row_ids = bundle.rows["row_id"].to_numpy()
    entry_matrix, entry_names = build_matrix(
        bundle,
        selection["entry"],
        row_ids=row_ids,
    )
    if entry_names != metrics["features"]:
        raise ValueError("entry feature order drift")
    entry_probability = entry_model.predict_proba(entry_matrix)
    risk_prediction = risk_model.predict(entry_matrix)
    management_general, _ = build_matrix(
        bundle,
        selection["management"],
        row_ids=row_ids,
    )
    frame = bundle.features[
        [
            "row_id",
            "decision_at",
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "sma20",
            "sma50",
            "1H.DMA_3X3_V1.DISTANCE_PRICE_DMA_PCT",
            "4H.DMA_3X3_V1.DISTANCE_PRICE_DMA_PCT",
            "1H.MACD_12_26_9_V1.histogram",
            "4H.MACD_12_26_9_V1.histogram",
            "1H.STOCH_14_3_3_V1.k",
            "1H.STOCH_14_3_3_V1.d",
            "4H.STOCH_14_3_3_V1.k",
            "4H.STOCH_14_3_3_V1.d",
            "1H.ADX_14_V1.adx",
            "1H.ATR_14_V1.atr",
            "1H.ATR_14_V1.atr_norm",
        ]
    ].copy()
    minute_hourly = _load_minute_hour_features(minute_path)
    frame = frame.merge(
        minute_hourly,
        left_on="open_time",
        right_on="hour",
        how="left",
        validate="one_to_one",
    ).drop(columns=["hour"])
    frame["open"] = frame["futures_open"].fillna(frame["open"])
    frame["high"] = frame["minute_high"]
    frame["low"] = frame["minute_low"]
    frame["close"] = frame["minute_close"].fillna(frame["close"])
    funding = pd.read_parquet(funding_path)
    funding["funding_time"] = pd.to_datetime(funding["funding_time"], utc=True)
    funding_by_time = {
        pd.Timestamp(row.funding_time): float(row.funding_rate)
        for row in funding.itertuples(index=False)
        if pd.notna(row.funding_rate)
    }
    return {
        "bundle": bundle,
        "metrics": metrics,
        "entry_probability": entry_probability,
        "risk_prediction": risk_prediction,
        "management_general": management_general,
        "management_model": management_model,
        "management_features": metrics["management"]["features"],
        "management_state_columns": selection["management_state_features"],
        "frame": frame,
        "funding_by_time": funding_by_time,
    }


def run_event_policy(
    *,
    dataset_root: Path,
    training_root: Path,
    output_root: Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    context = _context(
        dataset_root,
        training_root,
        Path(
            "/var/tmp/traiding_pilot_ui_workspace/"
            "capital_growth_experiment_v1/data/ETHUSDT_1m_combined.parquet"
        ),
        Path(
            "/var/tmp/traiding_pilot_ui_workspace/"
            "capital_growth_experiment_v1/data/funding_ETHUSDT.parquet"
        ),
    )
    output_root.mkdir(parents=True, exist_ok=True)
    frame = context["frame"]
    splits = {
        "RUN1": frame[
            (frame["decision_at"] >= pd.Timestamp(RUN1_START))
            & (frame["decision_at"] < pd.Timestamp(RUN1_END))
        ],
        "RUN2": frame[
            (frame["decision_at"] >= pd.Timestamp(RUN2_START))
            & (frame["decision_at"] < pd.Timestamp(RUN2_END))
        ],
    }
    results = []
    event_config = EventConfig()
    for split_name, split_frame in splits.items():
        row_ids = split_frame["row_id"].to_numpy()
        for spot_fraction in SPOT_FRACTIONS:
            qwen_log = (
                output_root
                / f"qwen_event_requests_{split_name}_{int(spot_fraction * 100)}.jsonl"
            )
            adapter = (
                None
                if dry_run
                else QwenPolicyAdapter(
                    config=QwenConfig(
                        model_id="qwen2.5:7b",
                        timeout_seconds=30.0,
                        num_predict=64,
                    ),
                    log_path=qwen_log,
                )
            )
            monitor = EventMonitor(event_config)
            result = _run_policy(
                name=(
                    "CATBOOST_EVENT_DRY_RUN"
                    if dry_run
                    else "CATBOOST_QWEN_EVENT_DRIVEN"
                ),
                split_name=split_name,
                frame=split_frame,
                spot_fraction=spot_fraction,
                spot_mode="HOLD",
                funding_by_time=context["funding_by_time"],
                entry_probabilities=context["entry_probability"][row_ids],
                risk_predictions=context["risk_prediction"][row_ids],
                management_general=context["management_general"][row_ids],
                management_model=context["management_model"],
                management_feature_names=context["management_features"],
                management_state_columns=context["management_state_columns"],
                qwen_adapter=adapter,
                qwen_context={
                    "run": split_name,
                    "spot_fraction": spot_fraction,
                    "spot_mode": "HOLD",
                    "policy": (
                        "EVENT_DRIVEN_DRY_RUN"
                        if dry_run
                        else "EVENT_DRIVEN_QWEN"
                    ),
                },
                event_monitor=monitor,
            )
            results.append(result)
            safe = f"{split_name}_{int(spot_fraction * 100)}"
            result.equity.to_parquet(
                output_root / f"{safe}_equity.parquet",
                index=False,
            )
            result.trades.to_csv(output_root / f"{safe}_trades.csv", index=False)
            result.decisions.to_csv(
                output_root / f"{safe}_decisions.csv",
                index=False,
            )
            result.qwen_events.to_csv(
                output_root / f"{safe}_qwen_events.csv",
                index=False,
            )
            result.market_events.to_csv(
                output_root / f"{safe}_market_events.csv",
                index=False,
            )
            result.order_trace.to_csv(
                output_root / f"{safe}_order_trace.csv",
                index=False,
            )
            result.action_trace.to_csv(
                output_root / f"{safe}_action_trace.csv",
                index=False,
            )
    metrics_frame = pd.DataFrame([result.metrics for result in results])
    metrics_frame.to_csv(output_root / "policy_metrics_v1.csv", index=False)
    all_events = pd.concat(
        [
            result.market_events.assign(split=result.split_name, spot_fraction=result.spot_fraction)
            for result in results
            if not result.market_events.empty
        ],
        ignore_index=True,
    ) if any(not result.market_events.empty for result in results) else pd.DataFrame()
    all_qwen = pd.concat(
        [
            result.qwen_events.assign(split=result.split_name, spot_fraction=result.spot_fraction)
            for result in results
            if not result.qwen_events.empty
        ],
        ignore_index=True,
    ) if any(not result.qwen_events.empty for result in results) else pd.DataFrame()
    latencies = (
        all_qwen.loc[all_qwen["latency_seconds"] > 0, "latency_seconds"].astype(float).tolist()
        if not all_qwen.empty
        else []
    )
    summary = {
        "status": "PASS",
        "mode": "DRY_RUN" if dry_run else "EVENT_DRIVEN",
        "event_config": event_config.__dict__,
        "metrics": metrics_frame.to_dict(orient="records"),
        "market_events_detected": int(
            (all_events["status"] == "TRIGGERED").sum()
        ) if not all_events.empty else 0,
        "market_events_suppressed": int(
            (all_events["status"] == "SUPPRESSED").sum()
        ) if not all_events.empty else 0,
        "qwen_eligible_events": int(
            (
                (all_events["status"] == "TRIGGERED")
                & (all_events["requires_qwen"] == True)  # noqa: E712
            ).sum()
        )
        if not all_events.empty
        else 0,
        "event_type_counts": all_events["event_type"].value_counts().to_dict()
        if not all_events.empty
        else {},
        "qwen_calls": int(sum(result.metrics["qwen_requests"] for result in results)),
        "qwen_action_changes": int(
            sum(result.metrics["qwen_action_changes"] for result in results)
        ),
        "fallbacks": int(sum(result.metrics["qwen_fallbacks"] for result in results)),
        "hedge_open_events": int(
            sum(result.metrics["hedge_signal_count"] for result in results)
        ),
        "hedge_proposed_count": int(
            sum(result.metrics["hedge_proposed_count"] for result in results)
        ),
        "hedge_approved_count": int(
            sum(result.metrics["hedge_approved_count"] for result in results)
        ),
        "hedge_rejected_count": int(
            sum(result.metrics["hedge_rejected_count"] for result in results)
        ),
        "hedge_filled_count": int(
            sum(result.metrics["hedge_filled_count"] for result in results)
        ),
        "hedge_close_events": int(
            sum(result.metrics["hedge_close_events"] for result in results)
        ),
        "hedge_closed_count": int(
            sum(result.metrics["hedge_closed_count"] for result in results)
        ),
        "hedge_rejection_reasons": {
            reason: int(
                sum(
                    result.metrics["hedge_rejection_reasons"].get(reason, 0)
                    for result in results
                )
            )
            for reason in {
                reason
                for result in results
                for reason in result.metrics["hedge_rejection_reasons"]
            }
        },
        "executed_order_count": int(
            sum(result.metrics["executed_order_count"] for result in results)
        ),
        "completed_trade_cycles": int(
            sum(result.metrics["completed_trade_cycles"] for result in results)
        ),
        "total_notional_turnover": float(
            sum(result.metrics["total_notional_turnover"] for result in results)
        ),
        "total_fees": float(sum(result.metrics["fees"] for result in results)),
        "total_slippage": float(
            sum(result.metrics["slippage"] for result in results)
        ),
        "risk_events": int(
            sum(result.metrics["risk_events"] for result in results)
        ),
        "median_latency": float(statistics.median(latencies)) if latencies else None,
        "p90_latency": float(np.percentile(latencies, 90)) if latencies else None,
        "liquidations": int(sum(result.metrics["liquidations"] for result in results)),
        "max_drawdown": float(
            max(result.metrics["max_drawdown"] for result in results)
        ),
        "oos_opened": "NO",
        "live_trading": "NO",
    }
    (output_root / "event_policy_summary_v1.json").write_text(
        json.dumps(summary, indent=2, default=str),
        encoding="utf-8",
    )
    return summary


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--training-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            run_event_policy(
                dataset_root=args.dataset_root,
                training_root=args.training_root,
                output_root=args.output_root,
                dry_run=args.dry_run,
            ),
            indent=2,
            default=str,
        )
    )
