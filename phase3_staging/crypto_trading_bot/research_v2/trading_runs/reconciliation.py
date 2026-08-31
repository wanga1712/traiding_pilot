"""Economic reconciliation for TRADING_RUN_RESULT_V1."""
from __future__ import annotations

from typing import Any

from .null_semantics import is_available, structural_only_blocks_monetary

TOLERANCE_ABS = 0.02
TOLERANCE_REL = 1e-6


def _num(v: Any) -> float | None:
    if v is None:
        return None
    return float(v)


def reconcile_run(run: dict[str, Any]) -> dict[str, Any]:
    """
    Validate:
      final_equity ≈ start + gross_pnl - fees + net_funding - spread - slippage - liquidation
    """
    if structural_only_blocks_monetary(run):
        return {
            "ECONOMIC_RECONCILIATION_STATUS": "NOT_AVAILABLE",
            "reason": "STRUCTURAL_ONLY run has no monetary economics",
        }

    status = run.get("run_status")
    if status not in ("COMPLETED",):
        return {"ECONOMIC_RECONCILIATION_STATUS": "NOT_AVAILABLE", "reason": f"run_status={status}"}

    cap = run.get("capital") or {}
    perf = run.get("performance") or {}
    costs = run.get("costs") or {}

    start = _num(cap.get("start_equity"))
    final = _num(cap.get("final_equity"))
    if start is None or final is None:
        return {"ECONOMIC_RECONCILIATION_STATUS": "NOT_AVAILABLE", "reason": "missing start/final equity"}

    gross = _num(perf.get("gross_pnl"))
    fees = _num(costs.get("total_trading_fees"))
    net_funding = _num(costs.get("net_funding"))
    spread = _num(costs.get("spread_cost"))
    slippage = _num(costs.get("slippage_cost"))
    liq = _num(costs.get("liquidation_cost"))

    required = [gross, fees, net_funding, spread, slippage, liq]
    if any(v is None for v in required):
        return {"ECONOMIC_RECONCILIATION_STATUS": "NOT_AVAILABLE", "reason": "incomplete cost fields"}

    expected = start + gross - fees + net_funding - spread - slippage - liq
    diff = final - expected
    tol = max(TOLERANCE_ABS, abs(expected) * TOLERANCE_REL)
    ok = abs(diff) <= tol
    return {
        "ECONOMIC_RECONCILIATION_STATUS": "PASS" if ok else "FAIL",
        "expected_final_equity": expected,
        "actual_final_equity": final,
        "difference": diff,
        "tolerance": tol,
    }
