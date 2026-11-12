from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _distribution(values: pd.Series) -> dict[str, float | int | None]:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "p90": None,
            "min": None,
            "max": None,
        }
    return {
        "count": int(len(numeric)),
        "mean": float(numeric.mean()),
        "median": float(numeric.median()),
        "p90": float(np.percentile(numeric, 90)),
        "min": float(numeric.min()),
        "max": float(numeric.max()),
    }


def _safe_read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _counter(series: pd.Series) -> dict[str, int]:
    if series.empty:
        return {}
    return {
        str(key): int(value)
        for key, value in series.fillna("UNKNOWN").value_counts().items()
    }


def _parse_embedded_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        try:
            parsed = ast.literal_eval(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, SyntaxError):
            return {}


def audit_event_output(root: Path) -> dict[str, Any]:
    root = root.resolve()
    trade_files = sorted(root.glob("*_trades.csv"))
    if not trade_files:
        raise FileNotFoundError(f"no *_trades.csv under {root}")

    runs: list[dict[str, Any]] = []
    for trade_path in trade_files:
        prefix = trade_path.name.removesuffix("_trades.csv")
        trades = _safe_read_csv(trade_path)
        decisions = _safe_read_csv(root / f"{prefix}_decisions.csv")
        qwen_events = _safe_read_csv(root / f"{prefix}_qwen_events.csv")
        order_trace = _safe_read_csv(root / f"{prefix}_order_trace.csv")
        market_events = _safe_read_csv(root / f"{prefix}_market_events.csv")

        if not trades.empty:
            trades["entry_time"] = pd.to_datetime(
                trades["entry_time"],
                utc=True,
                errors="coerce",
            )
            trades["exit_time"] = pd.to_datetime(
                trades["exit_time"],
                utc=True,
                errors="coerce",
            )
            trades["holding_hours"] = (
                trades["exit_time"] - trades["entry_time"]
            ).dt.total_seconds() / 3600.0
            trades["entry_notional"] = (
                pd.to_numeric(trades["average_entry"], errors="coerce")
                * pd.to_numeric(trades["quantity"], errors="coerce")
            )
            trades["exit_notional"] = (
                pd.to_numeric(trades["exit_fill"], errors="coerce")
                * pd.to_numeric(trades["quantity"], errors="coerce")
            )
            trades["additions_numeric"] = pd.to_numeric(
                trades["additions"]
                if "additions" in trades
                else pd.Series(0, index=trades.index),
                errors="coerce",
            ).fillna(0)

        if not decisions.empty:
            decision_time_source = (
                decisions["decision_time"]
                if "decision_time" in decisions
                else decisions["time"]
            )
            execution_time_source = (
                decisions["execution_time"]
                if "execution_time" in decisions
                else decisions["time"]
            )
            decisions["decision_time"] = pd.to_datetime(
                decision_time_source,
                utc=True,
                errors="coerce",
            )
            decisions["execution_time"] = pd.to_datetime(
                execution_time_source,
                utc=True,
                errors="coerce",
            )
            decisions["decision_to_execution_seconds"] = (
                decisions["execution_time"] - decisions["decision_time"]
            ).dt.total_seconds()
            decisions["execution_gap_hours"] = (
                decisions["execution_time"].diff().dt.total_seconds() / 3600.0
            )

        qwen_read: list[dict[str, Any]] = []
        request_path = root / f"qwen_event_requests_{prefix}.jsonl"
        if request_path.exists():
            for line in request_path.read_text(encoding="utf-8").splitlines():
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                qwen_read.append(
                    {
                        "cached": bool(record.get("cache_replay", False)),
                        "valid": bool(record.get("decision", {}).get("valid", False)),
                        "fallback": bool(
                            record.get("decision", {}).get("fallback_used", False)
                        ),
                    }
                )

        executed_orders = (
            order_trace.loc[order_trace["executed"] == 1].copy()
            if not order_trace.empty and "executed" in order_trace
            else pd.DataFrame()
        )
        order_counts = (
            executed_orders.groupby(["role", "action"]).size().to_dict()
            if not executed_orders.empty
            else {}
        )
        order_counts = {
            f"{role}:{action}": int(count)
            for (role, action), count in order_counts.items()
        }
        order_turnover = (
            executed_orders.groupby(["role", "action"])["notional"].sum().to_dict()
            if not executed_orders.empty
            else {}
        )
        order_turnover = {
            f"{role}:{action}": float(value)
            for (role, action), value in order_turnover.items()
        }

        exact_action_changes = 0
        exact_action_change_actions: dict[str, int] = {}
        qwen_eligible_event_types: dict[str, int] = {}
        qwen_eligible_timestamps = 0
        if not market_events.empty and "signature" in market_events:
            action_rows = market_events.loc[
                (market_events["event_type"] == "CATBOOST_ACTION_CHANGE")
                & (market_events["status"] == "TRIGGERED")
            ]
            target_actions = (
                action_rows["signature"]
                .fillna("")
                .str.split("|")
                .apply(lambda parts: parts[-1] if parts else "")
            )
            recognized = {
                "OPEN_LONG",
                "OPEN_SHORT",
                "OPEN_HEDGE",
                "CLOSE_HEDGE",
                "AVERAGE_PRIMARY",
                "REDUCE_POSITION",
                "EXIT",
                "SKIP",
            }
            target_actions = target_actions.loc[target_actions.isin(recognized)]
            exact_action_changes = int(len(target_actions))
            exact_action_change_actions = _counter(target_actions)
            qwen_eligible = market_events.loc[
                (market_events["status"] == "TRIGGERED")
                & (market_events["requires_qwen"] == True)  # noqa: E712
            ]
            qwen_eligible_event_types = _counter(qwen_eligible["event_type"])
            qwen_eligible_timestamps = int(qwen_eligible["time"].nunique())

        run = {
            "prefix": prefix,
            "trades": int(len(trades)),
            "decisions": int(len(decisions)),
            "trade_cycles_by_reason": _counter(
                trades["reason"] if "reason" in trades else pd.Series(dtype=str)
            ),
            "trades_by_role_side": _counter(
                (
                    trades["role"].astype(str) + ":" + trades["side"].astype(str)
                )
                if {"role", "side"}.issubset(trades.columns)
                else pd.Series(dtype=str)
            ),
            "additions_distribution": _counter(
                trades["additions_numeric"].astype(int).astype(str)
                if "additions_numeric" in trades
                else pd.Series(dtype=str)
            ),
            "cycles_over_two_additions": int(
                (trades["additions_numeric"] > 2).sum()
                if "additions_numeric" in trades
                else 0
            ),
            "holding_hours": _distribution(
                trades["holding_hours"] if "holding_hours" in trades else pd.Series(dtype=float)
            ),
            "trade_notional_turnover_proxy": (
                float(
                    (
                        trades["entry_notional"].fillna(0.0)
                        + trades["exit_notional"].fillna(0.0)
                    ).sum()
                )
                if not trades.empty
                else 0.0
            ),
            "trades_fees": (
                float(
                    (
                        pd.to_numeric(trades["entry_fees"], errors="coerce").fillna(0.0)
                        + pd.to_numeric(trades["exit_fee"], errors="coerce").fillna(0.0)
                    ).sum()
                )
                if not trades.empty
                else 0.0
            ),
            "trades_net_pnl": (
                float(pd.to_numeric(trades["net_pnl"], errors="coerce").fillna(0.0).sum())
                if not trades.empty
                else 0.0
            ),
            "decision_actions": _counter(
                decisions["action"]
                if "action" in decisions
                else pd.Series(dtype=str)
            ),
            "decision_order_reasons": _counter(
                decisions["order_reasons"]
                if "order_reasons" in decisions
                else pd.Series(dtype=str)
            ),
            "decision_to_execution_seconds": _distribution(
                decisions["decision_to_execution_seconds"]
                if "decision_to_execution_seconds" in decisions
                else pd.Series(dtype=float)
            ),
            "execution_gap_hours": _distribution(
                decisions["execution_gap_hours"]
                if "execution_gap_hours" in decisions
                else pd.Series(dtype=float)
            ),
            "same_timestamp_reentries": int(
                (
                    decisions["execution_time"].duplicated(keep=False)
                    if "execution_time" in decisions
                    else pd.Series(dtype=bool)
                ).sum()
            ),
            "qwen_event_rows": int(len(qwen_events)),
            "qwen_actions": _counter(
                qwen_events["qwen_action"]
                if "qwen_action" in qwen_events
                else pd.Series(dtype=str)
            ),
            "qwen_applied_actions": _counter(
                qwen_events["applied_action"]
                if "applied_action" in qwen_events
                else pd.Series(dtype=str)
            ),
            "qwen_application_reasons": _counter(
                qwen_events["application_reason"]
                if "application_reason" in qwen_events
                else pd.Series(dtype=str)
            ),
            "qwen_request_log_rows": len(qwen_read),
            "qwen_cached": int(sum(item["cached"] for item in qwen_read)),
            "qwen_valid_logs": int(sum(item["valid"] for item in qwen_read)),
            "qwen_fallbacks_logs": int(sum(item["fallback"] for item in qwen_read)),
            "exact_catboost_action_change_events": exact_action_changes,
            "exact_catboost_action_change_actions": exact_action_change_actions,
            "qwen_eligible_events": int(
                sum(qwen_eligible_event_types.values())
            ),
            "qwen_eligible_timestamps": qwen_eligible_timestamps,
            "qwen_eligible_event_types": qwen_eligible_event_types,
            "order_counts": order_counts,
            "order_turnover": order_turnover,
        }
        runs.append(run)

    summary = {
        "root": str(root),
        "runs": runs,
        "aggregate": {
            "trades": int(sum(run["trades"] for run in runs)),
            "decisions": int(sum(run["decisions"] for run in runs)),
            "trade_notional_turnover_proxy": float(
                sum(run["trade_notional_turnover_proxy"] for run in runs)
            ),
            "trades_fees": float(sum(run["trades_fees"] for run in runs)),
            "trades_net_pnl": float(sum(run["trades_net_pnl"] for run in runs)),
            "qwen_event_rows": int(sum(run["qwen_event_rows"] for run in runs)),
            "qwen_request_log_rows": int(
                sum(run["qwen_request_log_rows"] for run in runs)
            ),
            "exact_catboost_action_change_events": int(
                sum(run["exact_catboost_action_change_events"] for run in runs)
            ),
        },
    }
    (root / "execution_audit_v1.json").write_text(
        json.dumps(summary, indent=2, default=str),
        encoding="utf-8",
    )
    return summary


def audit_qwen_log(path: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    decisions = [
        record.get("decision", {})
        for record in records
        if isinstance(record.get("decision"), dict)
    ]
    allowed_sets = [
        tuple(record.get("request", {}).get("allowed_actions", []))
        for record in records
    ]
    result = {
        "path": str(path.resolve()),
        "records": len(records),
        "valid": int(sum(bool(decision.get("valid")) for decision in decisions)),
        "fallbacks": int(
            sum(bool(decision.get("fallback_used")) for decision in decisions)
        ),
        "cached": int(sum(bool(decision.get("cached")) for decision in decisions)),
        "actions": _counter(
            pd.Series([decision.get("action") for decision in decisions])
        ),
        "directions": _counter(
            pd.Series([decision.get("direction") for decision in decisions])
        ),
        "validation_errors": _counter(
            pd.Series(
                [
                    decision.get("validation_error")
                    for decision in decisions
                    if decision.get("validation_error")
                ]
            )
        ),
        "allowed_action_sets": _counter(
            pd.Series(["|".join(allowed) for allowed in allowed_sets])
        ),
        "latency_seconds": _distribution(
            pd.Series(
                [decision.get("latency_seconds") for decision in decisions]
            )
        ),
        "request_bytes_mean": (
            float(
                np.mean(
                    [
                        len(
                            json.dumps(
                                record.get("request", {}),
                                sort_keys=True,
                                separators=(",", ":"),
                            )
                        )
                        for record in records
                    ]
                )
            )
            if records
            else None
        ),
    }
    path.with_name(f"{path.stem}_audit_v1.json").write_text(
        json.dumps(result, indent=2, default=str),
        encoding="utf-8",
    )
    return result


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path)
    parser.add_argument("--qwen-log", type=Path)
    args = parser.parse_args()
    if args.root is None and args.qwen_log is None:
        parser.error("provide --root or --qwen-log")
    result: dict[str, Any] = {}
    if args.root is not None:
        result["event_output"] = audit_event_output(args.root)
    if args.qwen_log is not None:
        result["qwen_log"] = audit_qwen_log(args.qwen_log)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
