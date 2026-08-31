"""TEST FIXTURE ONLY — synthetic trading runs for automated tests."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .version import TRADING_RUN_RESULT_SCHEMA_VERSION


def _base_equity_curve(start: float = 100.0) -> list[dict[str, Any]]:
    points = []
    equity = start
    for i in range(12):
        equity += (i % 3 - 1) * 2.5
        points.append(
            {
                "timestamp": f"2023-0{(i % 9) + 1}-01T00:00:00+00:00",
                "equity": round(equity, 2),
                "balance": round(equity, 2),
                "unrealized_pnl": 0.0,
            }
        )
    return points


def fixture_completed_realistic() -> dict[str, Any]:
    start = 100.0
    gross = 95.0
    fees = 8.5
    net_funding = -2.4
    spread = 3.1
    slippage = 1.9
    liq = 0.0
    final = start + gross - fees + net_funding - spread - slippage - liq
    return {
        "schema_version": TRADING_RUN_RESULT_SCHEMA_VERSION,
        "run_id": "FIXTURE_COMPLETED_REALISTIC_V1",
        "run_status": "COMPLETED",
        "created_at": "2026-08-31T08:00:00+00:00",
        "strategy": {
            "strategy_id": "FIXTURE_DMA_STOCH",
            "strategy_name": "Fixture DMA+Stoch",
            "strategy_version": "v1",
            "model_name": None,
            "model_version": None,
            "prompt_version": None,
        },
        "market": {
            "exchange": "bybit",
            "instrument": "ETHUSDT",
            "category": "linear",
            "start_time": "2023-01-01T00:00:00+00:00",
            "end_time": "2023-12-31T23:59:59+00:00",
        },
        "capital": {
            "start_equity": start,
            "final_equity": final,
            "net_return_pct": (final / start - 1) * 100,
            "peak_equity": 198.4,
            "trough_equity": 92.1,
        },
        "performance": {
            "gross_pnl": gross,
            "net_pnl": final - start,
            "realized_pnl": final - start,
            "unrealized_pnl_at_end": 0.0,
            "trade_count": 67,
            "winning_trade_count": 38,
            "losing_trade_count": 29,
            "win_rate": 0.567,
            "profit_factor": 1.42,
            "expectancy": 1.23,
            "max_drawdown_amount": 14.8,
            "max_drawdown_pct": -14.8,
            "long_trade_count": 34,
            "short_trade_count": 33,
            "liquidation_count": 0,
        },
        "costs": {
            "entry_fees": 4.2,
            "exit_fees": 4.3,
            "total_trading_fees": fees,
            "funding_paid": 5.1,
            "funding_received": 2.7,
            "net_funding": net_funding,
            "spread_cost": spread,
            "slippage_cost": slippage,
            "liquidation_cost": liq,
            "total_costs": fees - net_funding + spread + slippage + liq,
        },
        "execution": {
            "decision_timeframe": "1H",
            "execution_timeframe": "1m",
            "fee_model_version": "FIXTURE_FEE_V1",
            "funding_model_version": "FIXTURE_FUNDING_V1",
            "slippage_model_version": "FIXTURE_SLIP_V1",
            "liquidation_model_version": "FIXTURE_LIQ_V1",
            "execution_realism_level": "ONE_MINUTE_EXECUTION",
        },
        "equity_curve": _base_equity_curve(start),
        "trades": [{"trade_id": "T1"}],
        "liquidations": [],
        "parameters": {"git_commit": "TEST_FIXTURE_ONLY"},
        "liquidation_data_status": "ZERO_CONFIRMED",
    }


def fixture_running() -> dict[str, Any]:
    run = fixture_completed_realistic()
    run = deepcopy(run)
    run["run_id"] = "FIXTURE_RUNNING_V1"
    run["run_status"] = "RUNNING"
    run["capital"]["final_equity"] = None
    run["capital"]["net_return_pct"] = None
    run["performance"]["gross_pnl"] = None
    run["performance"]["net_pnl"] = None
    run["equity_curve"] = run["equity_curve"][:5]
    return run


def fixture_structural_only() -> dict[str, Any]:
    return {
        "schema_version": TRADING_RUN_RESULT_SCHEMA_VERSION,
        "run_id": "FIXTURE_STRUCTURAL_ORIGINAL_DMA_STOCH_V1",
        "run_status": "COMPLETED",
        "created_at": "2026-08-29T21:00:00+00:00",
        "strategy": {
            "strategy_id": "ORIGINAL_DMA_STOCH_RULE",
            "strategy_name": "Display-aligned DMA 3x3 + Stoch 14/3/3",
            "strategy_version": "frozen_v1",
            "model_name": None,
            "model_version": None,
            "prompt_version": None,
        },
        "market": {
            "exchange": "binance",
            "instrument": "ETHUSDT",
            "category": "spot_research",
            "start_time": "2019-05-12T00:00:00+00:00",
            "end_time": "2023-06-20T00:00:00+00:00",
        },
        "capital": {
            "start_equity": None,
            "final_equity": None,
            "net_return_pct": None,
            "peak_equity": None,
            "trough_equity": None,
        },
        "performance": {
            "gross_pnl": None,
            "net_pnl": None,
            "realized_pnl": None,
            "unrealized_pnl_at_end": None,
            "trade_count": None,
            "winning_trade_count": None,
            "losing_trade_count": None,
            "win_rate": None,
            "profit_factor": None,
            "expectancy": None,
            "max_drawdown_amount": None,
            "max_drawdown_pct": None,
            "long_trade_count": None,
            "short_trade_count": None,
            "liquidation_count": None,
        },
        "costs": {},
        "execution": {
            "decision_timeframe": "1H",
            "execution_timeframe": None,
            "execution_realism_level": "STRUCTURAL_ONLY",
        },
        "equity_curve": None,
        "research_metrics": {
            "precision": 0.4708,
            "recall": 0.3767,
            "false_positive_rate": 0.047,
            "remaining_wave_fraction": 0.646,
            "verdict": "COMPOSITE_NOT_BETTER_THAN_PRICE",
            "best_human_composite": {
                "dma": "3x3 display-aligned",
                "stoch": "14/3/3",
                "confirmation_window": 3,
                "signal_expiration": 5,
            },
        },
        "trades": [],
        "liquidations": [],
        "parameters": {
            "confirmation_window": 3,
            "signal_expiration": 5,
            "git_commit": "5924b9e",
        },
        "liquidation_data_status": "NOT_AVAILABLE",
    }


def fixture_failed() -> dict[str, Any]:
    run = deepcopy(fixture_completed_realistic())
    run["run_id"] = "FIXTURE_FAILED_V1"
    run["run_status"] = "FAILED"
    run["capital"]["final_equity"] = None
    return run


def fixture_reconciliation_fail() -> dict[str, Any]:
    run = fixture_completed_realistic()
    run = deepcopy(run)
    run["run_id"] = "FIXTURE_RECON_FAIL_V1"
    run["capital"]["final_equity"] = 999.0
    return run


def fixture_zero_liquidations() -> dict[str, Any]:
    run = deepcopy(fixture_completed_realistic())
    run["run_id"] = "FIXTURE_ZERO_LIQ_V1"
    run["performance"]["liquidation_count"] = 0
    run["liquidation_data_status"] = "ZERO_CONFIRMED"
    return run


def fixture_unknown_liquidations() -> dict[str, Any]:
    run = deepcopy(fixture_completed_realistic())
    run["run_id"] = "FIXTURE_UNKNOWN_LIQ_V1"
    run["performance"]["liquidation_count"] = None
    run["liquidation_data_status"] = "NOT_AVAILABLE"
    return run


ALL_FIXTURES = {
    "FIXTURE_COMPLETED_REALISTIC_V1": fixture_completed_realistic,
    "FIXTURE_RUNNING_V1": fixture_running,
    "FIXTURE_STRUCTURAL_ORIGINAL_DMA_STOCH_V1": fixture_structural_only,
    "FIXTURE_FAILED_V1": fixture_failed,
    "FIXTURE_RECON_FAIL_V1": fixture_reconciliation_fail,
    "FIXTURE_ZERO_LIQ_V1": fixture_zero_liquidations,
    "FIXTURE_UNKNOWN_LIQ_V1": fixture_unknown_liquidations,
}
