"""TRADING_RUN_RESULT_V1 validation."""
from __future__ import annotations

from typing import Any

from .null_semantics import structural_only_blocks_monetary
from .reconciliation import reconcile_run
from .version import TRADING_RUN_RESULT_SCHEMA_VERSION

RUN_STATUSES = frozenset({"PENDING", "RUNNING", "COMPLETED", "FAILED", "INVALID"})
REALISM_LEVELS = frozenset(
    {
        "STRUCTURAL_ONLY",
        "OHLC_BACKTEST",
        "ONE_MINUTE_EXECUTION",
        "TRADE_LEVEL_EXECUTION",
        "ORDERBOOK_EXECUTION",
    }
)

MONETARY_CAPITAL_KEYS = ("start_equity", "final_equity", "net_return_pct", "peak_equity", "trough_equity")
MONETARY_COST_KEYS = (
    "entry_fees",
    "exit_fees",
    "total_trading_fees",
    "funding_paid",
    "funding_received",
    "net_funding",
    "spread_cost",
    "slippage_cost",
    "liquidation_cost",
    "total_costs",
)


def validate_run(run: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if run.get("schema_version") != TRADING_RUN_RESULT_SCHEMA_VERSION:
        errors.append(f"schema_version must be {TRADING_RUN_RESULT_SCHEMA_VERSION}")
    if not run.get("run_id"):
        errors.append("run_id required")
    status = run.get("run_status")
    if status not in RUN_STATUSES:
        errors.append(f"invalid run_status: {status}")
    exec_block = run.get("execution") or {}
    realism = exec_block.get("execution_realism_level")
    if realism and realism not in REALISM_LEVELS:
        errors.append(f"invalid execution_realism_level: {realism}")

    if structural_only_blocks_monetary(run):
        cap = run.get("capital") or {}
        for key in MONETARY_CAPITAL_KEYS:
            if cap.get(key) is not None:
                errors.append(f"STRUCTURAL_ONLY must not set capital.{key}")
        costs = run.get("costs") or {}
        for key in MONETARY_COST_KEYS:
            if costs.get(key) is not None:
                errors.append(f"STRUCTURAL_ONLY must not set costs.{key}")
        perf = run.get("performance") or {}
        for key in ("gross_pnl", "net_pnl", "realized_pnl"):
            if perf.get(key) is not None:
                errors.append(f"STRUCTURAL_ONLY must not set performance.{key}")

    if status == "COMPLETED" and not structural_only_blocks_monetary(run):
        rec = reconcile_run(run)
        if rec.get("ECONOMIC_RECONCILIATION_STATUS") == "FAIL":
            errors.append(f"economic reconciliation failed: diff={rec.get('difference')}")

    return errors


def validate_run_or_raise(run: dict[str, Any]) -> None:
    errors = validate_run(run)
    if errors:
        raise ValueError("; ".join(errors))
