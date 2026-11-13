from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from crypto_trading_bot.research_v2.gpu_ai_policy.hedge_attribution import (
    _attribution,
    _hedge_cycles,
    _parse_dict,
    _position_pnl,
    _training_labels,
)


def test_position_pnl_uses_side_quantity_and_entry() -> None:
    state = {
        "primary": {
            "side": -1,
            "quantity": 2.0,
            "average_entry": 100.0,
            "liquidation_distance_pct": 0.1,
        }
    }
    assert _position_pnl(state, "primary", 90.0) == pytest.approx(20.0)
    assert _parse_dict("{'state': 'HEDGED'}") == {"state": "HEDGED"}


def test_hedge_cycle_record_links_primary_state_and_net_pnl() -> None:
    times = pd.to_datetime(
        [
            "2024-01-01T00:00:00Z",
            "2024-01-01T01:00:00Z",
            "2024-01-01T02:00:00Z",
            "2024-01-01T03:00:00Z",
        ],
        utc=True,
    )
    trades = pd.DataFrame(
        [
            {
                "role": "PRIMARY",
                "side": "LONG",
                "entry_time": times[0],
                "exit_time": times[3],
                "average_entry": 100.0,
                "exit_fill": 98.0,
                "quantity": 10.0,
                "margin": 100.0,
                "gross_pnl": -20.0,
                "net_pnl": -21.0,
                "entry_fees": 0.5,
                "exit_fee": 0.5,
                "funding_cost": 0.0,
                "reason": "AI_EXIT",
                "isolated_deficit": 0.0,
            },
            {
                "role": "HEDGE",
                "side": "SHORT",
                "entry_time": times[1],
                "exit_time": times[2],
                "average_entry": 99.0,
                "exit_fill": 98.0,
                "quantity": 5.0,
                "margin": 50.0,
                "gross_pnl": 5.0,
                "net_pnl": 4.5,
                "entry_fees": 0.2,
                "exit_fee": 0.2,
                "funding_cost": 0.1,
                "reason": "AI_EXIT_HEDGE",
                "isolated_deficit": 0.0,
            },
        ]
    )
    before_open = {
        "gross_notional": 1000.0,
        "net_notional": 1000.0,
        "primary": {
            "side": 1,
            "quantity": 10.0,
            "average_entry": 100.0,
            "unrealized_pnl": -10.0,
            "liquidation_distance_pct": 0.1,
        },
        "hedge": None,
    }
    after_open = {
        **before_open,
        "gross_notional": 1495.0,
        "net_notional": 505.0,
        "hedge": {"side": -1, "quantity": 5.0, "liquidation_distance_pct": 0.2},
    }
    before_close = {
        **after_open,
        "primary": {**before_open["primary"], "unrealized_pnl": -20.0},
    }
    actions = pd.DataFrame(
        [
            {
                "execution_time": times[1],
                "execution_price": 99.0,
                "state_before_execution": str(before_open),
                "state_after_execution": str(after_open),
                "catboost_action": "OPEN_HEDGE",
                "catboost_probabilities": str(
                    {"OPEN_HEDGE": 0.6, "HOLD": 0.4}
                ),
                "selection_source": "POLICY",
            },
            {
                "execution_time": times[2],
                "execution_price": 98.0,
                "state_before_execution": str(before_close),
                "state_after_execution": str(after_open),
                "catboost_action": "CLOSE_HEDGE",
                "catboost_probabilities": "{}",
                "selection_source": "POLICY",
            },
        ]
    )
    run = {
        "prefix": "RUN1_60",
        "trades": trades,
        "orders": pd.DataFrame(),
        "actions": actions,
        "equity": pd.DataFrame(),
    }
    frame, summary = _hedge_cycles(run, pd.DataFrame())
    assert summary["count"] == 1
    record = frame.iloc[0]
    assert record["primary_pnl_at_hedge_open"] == pytest.approx(-10.0)
    assert record["primary_pnl_at_hedge_close"] == pytest.approx(-20.0)
    assert record["hedge_net_pnl"] == pytest.approx(4.5)
    assert record["primary_plus_hedge_cycle_net_pnl"] == pytest.approx(-16.5)


def test_isolated_deficit_reconciles_accounting() -> None:
    trades = pd.DataFrame(
        [
            {
                "role": "PRIMARY",
                "gross_pnl": -11.0,
                "net_pnl": -12.0,
                "entry_fees": 0.4,
                "exit_fee": 0.6,
                "funding_cost": 0.0,
                "isolated_deficit": 1.0,
                "reason": "LIQUIDATED",
            },
            {
                "role": "HEDGE",
                "gross_pnl": 0.0,
                "net_pnl": 0.0,
                "entry_fees": 0.0,
                "exit_fee": 0.0,
                "funding_cost": 0.0,
                "isolated_deficit": 0.0,
                "reason": "RUN_END",
            },
        ]
    )
    orders = pd.DataFrame(
        [
            {
                "role": "PRIMARY",
                "executed": 1,
                "time": pd.Timestamp("2024-01-01T00:00:00Z"),
                "fee": 1.0,
                "notional": 10.0,
                "quantity": 1.0,
            },
            {
                "role": "SPOT",
                "executed": 1,
                "time": pd.Timestamp("2024-01-01T00:00:00Z"),
                "fee": 0.01,
                "notional": 60.0,
                "quantity": 1.2,
            },
        ]
    )
    prices = pd.DataFrame(
        {"futures_open": [10.0], "spot_open": [50.0]},
        index=pd.DatetimeIndex(["2024-01-01T00:00:00Z"]),
    )
    equity = pd.DataFrame(
        [{"spot_equity": 60.0, "futures_equity": 29.0, "equity": 89.0}]
    )
    result = _attribution(
        {
            "prefix": "RUN1_60",
            "trades": trades,
            "orders": orders,
            "equity": equity,
        },
        prices,
    )
    assert abs(result["accounting_error"]) < 1e-9


def test_training_label_counts_are_reproducible() -> None:
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
        path = Path(temporary) / "samples.parquet"
        pd.DataFrame(
            {
                "best_action": ["HOLD", "OPEN_HEDGE", "HOLD"],
                "split": ["TRAIN", "TRAIN", "SELECTION"],
            }
        ).to_parquet(path, index=False)
        result = _training_labels(path)
        assert result["best_action_counts"] == {"HOLD": 2, "OPEN_HEDGE": 1}
        assert json.dumps(result)
