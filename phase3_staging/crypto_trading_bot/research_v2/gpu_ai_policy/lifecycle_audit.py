from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from .hedge_attribution import (
    _attribution,
    _churn,
    _price_map,
    _read_run,
)


def _cycle_integrity(
    lifecycle: pd.DataFrame,
    orders: pd.DataFrame,
) -> dict[str, Any]:
    lifecycle = lifecycle.copy()
    lifecycle["time"] = pd.to_datetime(
        lifecycle["time"],
        utc=True,
        format="mixed",
        errors="coerce",
    )
    lifecycle = lifecycle.sort_values(["cycle_id", "time", "state"])
    terminal = {"EXITED", "LIQUIDATED"}
    anomalies: Counter[str] = Counter()
    completed = 0
    for cycle_id, group in lifecycle.groupby("cycle_id"):
        states = group["state"].tolist()
        if "PRIMARY_OPEN" not in states:
            anomalies["MISSING_PRIMARY_OPEN"] += 1
        if not any(state in terminal for state in states):
            anomalies["MISSING_TERMINAL_STATE"] += 1
        elif any(state in terminal for state in states):
            completed += 1
        if "FLAT" not in states and any(state in terminal for state in states):
            anomalies["MISSING_FLAT_TRANSITION"] += 1

    exit_times = (
        lifecycle.loc[lifecycle["state"].isin(terminal)]
        .set_index("cycle_id")["time"]
        .groupby(level=0)
        .max()
    )
    executed = orders.loc[orders["executed"] == 1].copy()
    executed["time"] = pd.to_datetime(
        executed["time"],
        utc=True,
        format="mixed",
        errors="coerce",
    )
    orders_after_exit = 0
    for row in executed.itertuples(index=False):
        exit_time = exit_times.get(int(row.cycle_id))
        if exit_time is not None and row.time > exit_time:
            orders_after_exit += 1
    primary_orders_per_cycle = (
        executed.loc[executed["role"] == "PRIMARY"]
        .groupby("cycle_id")
        .size()
        .astype(str)
        .value_counts()
        .to_dict()
    )
    return {
        "cycles": int(lifecycle["cycle_id"].nunique()),
        "completed_cycles": completed,
        "state_counts": {
            str(key): int(value)
            for key, value in lifecycle["state"].value_counts().items()
        },
        "anomalies": dict(anomalies),
        "executed_orders_after_terminal_state": orders_after_exit,
        "executed_orders_missing_cycle_id": int(
            (
                (executed["role"] != "SPOT")
                & (
                    (executed["cycle_id"].isna())
                    | (executed["cycle_id"] <= 0)
                )
            ).sum()
        ),
        "primary_orders_per_cycle_distribution": {
            str(key): int(value)
            for key, value in primary_orders_per_cycle.items()
        },
    }


def audit_lifecycle_run(
    *,
    root: Path,
    minute_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    prices = _price_map(minute_path)
    summary = json.loads(
        (root / "event_policy_summary_v1.json").read_text(encoding="utf-8")
    )
    metrics = {
        (item["split"], float(item["spot_fraction"])): item
        for item in summary["metrics"]
    }
    result: dict[str, Any] = {
        "root": str(root.resolve()),
        "runs": {},
    }
    for prefix in ("RUN1_60", "RUN1_40", "RUN2_60", "RUN2_40"):
        split, spot = prefix.split("_")
        key = (split, float(f"0.{spot}"))
        run = _read_run(root, prefix)
        lifecycle = pd.read_csv(root / f"{prefix}_lifecycle_events.csv")
        churn = _churn(run)
        attribution = _attribution(run, prices, metrics[key])
        result["runs"][prefix] = {
            "metrics": metrics[key],
            "churn": churn,
            "lifecycle_integrity": _cycle_integrity(
                lifecycle,
                run["orders"],
            ),
            "accounting": attribution,
            "cash_reconciliation": {
                "final_free_collateral": float(
                    run["equity"].iloc[-1]["free_collateral"]
                ),
                "final_used_margin": float(
                    run["equity"].iloc[-1]["used_margin"]
                ),
                "initial_futures_collateral": (
                    100.0 * (1.0 - float(f"0.{spot}"))
                ),
                "trade_net_pnl": (
                    float(run["trades"]["net_pnl"].sum())
                ),
                "isolated_deficit": (
                    float(run["trades"]["isolated_deficit"].sum())
                ),
                "residual_vs_futures_net": (
                    float(run["equity"].iloc[-1]["futures_equity"])
                    - 100.0 * (1.0 - float(f"0.{spot}"))
                    - float(run["trades"]["net_pnl"].sum())
                    - float(run["trades"]["isolated_deficit"].sum())
                ),
            },
        }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, indent=2, default=str),
        encoding="utf-8",
    )
    return result


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--minute-path", type=Path, required=True)
    parser.add_argument("--output-path", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            audit_lifecycle_run(
                root=args.root,
                minute_path=args.minute_path,
                output_path=args.output_path,
            ),
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
