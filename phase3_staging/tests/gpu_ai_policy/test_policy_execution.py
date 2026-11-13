from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import pytest

from crypto_trading_bot.research_v2.gpu_ai_policy.backtest import (
    PolicyAccount,
    _allowed_actions,
    _run_policy,
)
from crypto_trading_bot.research_v2.gpu_ai_policy.event_monitor import (
    EventConfig,
    EventMonitor,
)
from crypto_trading_bot.research_v2.gpu_ai_policy.event_backtest import (
    _load_minute_hour_features,
)
from crypto_trading_bot.research_v2.gpu_ai_policy.qwen_adapter import QwenDecision


def _time(hour: int) -> pd.Timestamp:
    return pd.Timestamp(f"2024-01-01T{hour:02d}:00:00Z")


def _assert_no_capital_creation(account: PolicyAccount, expected: float) -> None:
    assert account.equity(100.0) == pytest.approx(expected, abs=1e-5)
    assert account.futures.free_collateral >= -1e-9


def test_primary_long_hedge_short_reaches_hedged_and_hedge_closed() -> None:
    account = PolicyAccount(0.60, "HOLD")

    assert account.execute("OPEN_LONG", time=_time(0), mark=100.0, volume=50_000.0)[
        0
    ]["executed"]
    assert account.execute(
        "OPEN_HEDGE",
        time=_time(1),
        mark=94.0,
        volume=50_000.0,
    )[0]["executed"]
    assert account.position_state() == "HEDGED"
    assert account.futures.primary is not None
    assert account.futures.hedge is not None

    closed = account.execute(
        "CLOSE_HEDGE",
        time=_time(2),
        mark=88.0,
        volume=50_000.0,
    )
    assert closed[0]["executed"]
    assert account.position_state() == "PRIMARY_OPEN"
    assert account.futures.primary is not None
    assert account.futures.hedge is None
    assert account.hedge_filled_count == 1
    assert account.hedge_closed_count == 1
    assert account.futures.realized_hedge > 0

    assert account.execute(
        "EXIT",
        time=_time(3),
        mark=102.0,
        volume=50_000.0,
    )[0]["executed"]
    assert account.position_state() == "FLAT"
    assert account.primary_cycle_count == 1


def test_primary_short_hedge_long_is_mirror_reachable() -> None:
    account = PolicyAccount(0.60, "HOLD")

    assert account.execute("OPEN_SHORT", time=_time(0), mark=100.0, volume=50_000.0)[
        0
    ]["executed"]
    assert account.execute(
        "OPEN_HEDGE",
        time=_time(1),
        mark=106.0,
        volume=50_000.0,
    )[0]["executed"]
    assert account.position_state() == "HEDGED"
    assert account.futures.primary.side == -1
    assert account.futures.hedge.side == 1

    assert account.execute(
        "CLOSE_HEDGE",
        time=_time(2),
        mark=112.0,
        volume=50_000.0,
    )[0]["executed"]
    assert account.position_state() == "PRIMARY_OPEN"
    assert account.futures.realized_hedge > 0


def test_unhedged_control_removes_hedge_actions_without_changing_primary() -> None:
    account = PolicyAccount(0.60, "HOLD")
    assert account.execute("OPEN_LONG", time=_time(0), mark=100.0, volume=50_000.0)[
        0
    ]["executed"]
    primary = account.futures.primary

    hedged_actions = _allowed_actions(account, hedge_enabled=True)
    unhedged_actions = _allowed_actions(account, hedge_enabled=False)
    assert "OPEN_HEDGE" in hedged_actions
    assert "OPEN_HEDGE" not in unhedged_actions
    assert "CLOSE_HEDGE" not in unhedged_actions
    assert account.futures.primary is primary


def test_hedge_is_rejected_without_free_margin() -> None:
    account = PolicyAccount(0.60, "HOLD")
    assert account.execute("OPEN_LONG", time=_time(0), mark=100.0, volume=50_000.0)[
        0
    ]["executed"]
    account.futures.free_collateral = 0.0

    rejected = account.execute(
        "OPEN_HEDGE",
        time=_time(1),
        mark=95.0,
        volume=50_000.0,
    )
    assert not rejected[0]["executed"]
    assert rejected[0]["reason"] in {"FREE_MARGIN", "RISK_LIMIT", "MIN_NOTIONAL"}
    assert account.position_state() == "PRIMARY_OPEN"
    assert account.hedge_rejected_count == 1


def test_averaging_limit_is_per_primary_hypothesis() -> None:
    account = PolicyAccount(0.60, "HOLD")
    assert account.execute("OPEN_LONG", time=_time(0), mark=100.0, volume=50_000.0)[
        0
    ]["executed"]
    account.futures.primary.additions = 2

    rejected = account.execute(
        "AVERAGE_PRIMARY",
        time=_time(1),
        mark=95.0,
        volume=50_000.0,
    )
    assert not rejected[0]["executed"]
    assert rejected[0]["reason"] == "AVERAGING_LIMIT"


def test_partial_reduction_keeps_remaining_primary_position() -> None:
    account = PolicyAccount(0.60, "HOLD")
    assert account.execute("OPEN_LONG", time=_time(0), mark=100.0, volume=50_000.0)[
        0
    ]["executed"]
    quantity = account.futures.primary.quantity

    reduced = account.execute(
        "REDUCE_POSITION",
        time=_time(1),
        mark=102.0,
        volume=50_000.0,
    )
    assert reduced[0]["executed"]
    assert account.futures.primary is not None
    assert account.futures.primary.quantity == pytest.approx(quantity * 0.5)


def test_event_deduplication_and_emergency_qwen_bypass() -> None:
    monitor = EventMonitor(EventConfig())
    first = monitor._event(
        time=_time(0),
        event_type="PRIMARY_ADVERSE_1ATR",
        level=95.0,
        position_state="PRIMARY_OPEN",
        features={"close": 95.0},
        catboost={"long_probability": 0.4},
        risk={"free_margin_fraction": 0.2},
        signature_parts=("PRIMARY_OPEN", 1, 3.0),
        requires_qwen=True,
    )
    duplicate = monitor._event(
        time=_time(1),
        event_type="PRIMARY_ADVERSE_1ATR",
        level=95.0,
        position_state="PRIMARY_OPEN",
        features={"close": 95.0},
        catboost={"long_probability": 0.4},
        risk={"free_margin_fraction": 0.2},
        signature_parts=("PRIMARY_OPEN", 1, 3.0),
        requires_qwen=True,
    )
    assert first.status == "TRIGGERED"
    assert duplicate.status == "SUPPRESSED"
    assert duplicate.suppression_reason == "DEDUPLICATED"

    emergency = monitor._event(
        time=_time(2),
        event_type="RISK_DRAWDOWN_EMERGENCY",
        level=0.06,
        position_state="PRIMARY_OPEN",
        features={"close": 90.0},
        catboost={},
        risk={"futures_drawdown_fraction": 0.06},
        signature_parts=("PRIMARY_OPEN", 1, 0.06),
        requires_qwen=False,
    )
    assert EventMonitor.emergency([emergency]) == [emergency]
    assert EventMonitor.triggered_for_qwen([emergency]) == []


def test_liquidation_closes_position_and_records_order() -> None:
    account = PolicyAccount(0.60, "HOLD")
    assert account.execute("OPEN_LONG", time=_time(0), mark=100.0, volume=50_000.0)[
        0
    ]["executed"]
    liquidation_price = account.futures.primary.liquidation_price(0.004, 0.0005)

    roles = account.enforce_liquidation(
        _time(1),
        high=101.0,
        low=liquidation_price - 1.0,
        close=liquidation_price - 0.5,
    )
    assert roles == ["PRIMARY"]
    assert account.futures.primary is None
    assert account.position_state() == "FLAT"
    assert account.liquidation_count == 1
    assert account.order_trace[-1]["action"] == "LIQUIDATE"
    assert account.order_trace[-1]["reason"] == "LIQUIDATED"


def test_fee_funding_and_slippage_are_conserved() -> None:
    account = PolicyAccount(0.60, "HOLD")
    assert account.execute("OPEN_LONG", time=_time(0), mark=100.0, volume=50_000.0)[
        0
    ]["executed"]
    account.apply_funding(100.0, 0.0001)
    assert account.execute(
        "EXIT",
        time=_time(1),
        mark=100.0,
        volume=50_000.0,
    )[0]["executed"]

    total_costs = (
        account.futures.entry_fees
        + account.futures.exit_fees
        + account.futures.funding_costs
        + account.futures.slippage_costs
    )
    assert total_costs > 0
    _assert_no_capital_creation(account, 100.0 - total_costs)


def test_spot_swing_uses_spot_price_not_futures_execution_price() -> None:
    account = PolicyAccount(0.60, "SWING")
    account.spot.cash = 50.0
    account.futures.free_collateral = 50.0
    account._spot_swing(
        _time(0),
        futures_mark=200.0,
        spot_mark=50.0,
        direction=1,
    )
    assert account.spot.eth > 0.99
    assert account.spot.eth < 1.01
    assert account.spot.equity(50.0) == pytest.approx(50.0, abs=0.05)


def test_decision_executes_only_at_next_available_bar_open() -> None:
    frame = pd.DataFrame(
        {
            "row_id": [0, 1, 2, 3],
            "open_time": pd.to_datetime(
                [
                    "2024-01-01T00:00:00Z",
                    "2024-01-01T01:00:00Z",
                    "2024-01-01T02:00:00Z",
                    "2024-01-01T03:00:00Z",
                ],
                utc=True,
            ),
            "decision_at": pd.to_datetime(
                [
                    "2024-01-01T01:00:00Z",
                    "2024-01-01T02:00:00Z",
                    "2024-01-01T03:00:00Z",
                    "2024-01-01T04:00:00Z",
                ],
                utc=True,
            ),
            "open": [100.0, 101.0, 102.0, 100.0],
            "high": [101.0, 102.0, 102.1, 100.1],
            "low": [99.9, 100.9, 99.8, 99.9],
            "close": [101.0, 102.0, 100.0, 99.0],
            "volume": [50_000.0] * 4,
            "sma20": [100.5, 101.0, 100.8, 99.5],
            "sma50": [100.0, 100.5, 101.0, 100.0],
        }
    )
    result = _run_policy(
        name="SMA_BASELINE",
        split_name="TEST",
        frame=frame,
        spot_fraction=0.60,
        spot_mode="HOLD",
        funding_by_time={},
        entry_probabilities=None,
        risk_predictions=None,
        management_general=None,
        management_model=None,
        management_feature_names=None,
        management_state_columns=None,
    )

    assert not result.decisions.empty
    decision_times = pd.to_datetime(result.decisions["decision_time"], utc=True)
    execution_times = pd.to_datetime(result.decisions["execution_time"], utc=True)
    assert (execution_times >= decision_times).all()
    first = result.decisions.iloc[0]
    assert first["decision_price"] == pytest.approx(101.0)
    assert first["execution_price"] == pytest.approx(101.0)


def test_qwen_receives_atr_and_state_specific_action_contract() -> None:
    class CaptureQwen:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def decide(self, **kwargs) -> QwenDecision:
            self.calls.append(kwargs)
            return QwenDecision(
                action="HOLD",
                direction="NONE",
                confidence=0.9,
                reason="Hold.",
                risk_assessment="Within limits.",
                valid=True,
                fallback_used=False,
                validation_error=None,
                latency_seconds=1.0,
                request_hash="test",
                model_id="test",
                model_digest="test",
            )

    frame = pd.DataFrame(
        {
            "row_id": [0, 1, 2],
            "open_time": pd.to_datetime(
                [
                    "2024-01-01T00:00:00Z",
                    "2024-01-01T01:00:00Z",
                    "2024-01-01T02:00:00Z",
                ],
                utc=True,
            ),
            "decision_at": pd.to_datetime(
                [
                    "2024-01-01T01:00:00Z",
                    "2024-01-01T02:00:00Z",
                    "2024-01-01T03:00:00Z",
                ],
                utc=True,
            ),
            "open": [100.0, 101.0, 102.0],
            "high": [101.0, 102.0, 103.0],
            "low": [99.0, 100.0, 101.0],
            "close": [101.0, 102.0, 103.0],
            "volume": [50_000.0] * 3,
            "sma20": [100.5, 101.0, 100.0],
            "sma50": [100.0, 100.5, 101.5],
            "1H.ATR_14_V1.atr": [1.5, 1.6, 1.7],
            "1H.ATR_14_V1.atr_norm": [0.015, 0.016, 0.017],
        }
    )
    qwen = CaptureQwen()
    _run_policy(
        name="SMA_BASELINE",
        split_name="TEST",
        frame=frame,
        spot_fraction=0.60,
        spot_mode="HOLD",
        funding_by_time={},
        entry_probabilities=None,
        risk_predictions=None,
        management_general=None,
        management_model=None,
        management_feature_names=None,
        management_state_columns=None,
        qwen_adapter=qwen,
        event_monitor=EventMonitor(EventConfig()),
    )

    assert qwen.calls
    assert qwen.calls[0]["market_features"]["1H.ATR_14_V1.atr"] == pytest.approx(1.6)
    assert (
        qwen.calls[0]["market_features"]["1H.ATR_14_V1.atr_norm"]
        == pytest.approx(0.016)
    )
    assert qwen.calls[0]["portfolio_state"]["position_state"] == "PRIMARY_OPEN"
    assert "OPEN_HEDGE" in qwen.calls[0]["allowed_actions"]
    assert "CLOSE_HEDGE" not in qwen.calls[0]["allowed_actions"]
    assert qwen.calls[0]["market_events"]
    assert "catboost" not in qwen.calls[0]["market_events"][0]
    assert "risk" not in qwen.calls[0]["market_events"][0]


def test_minute_aggregation_uses_futures_open_and_mark_extrema() -> None:
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
        path = Path(temporary) / "minute.parquet"
        pd.DataFrame(
            {
                "open_time": pd.to_datetime(
                    [
                        "2024-01-01T00:00:00Z",
                        "2024-01-01T00:01:00Z",
                        "2024-01-01T01:00:00Z",
                    ],
                    utc=True,
                ),
                "open": [90.0, 90.5, 95.0],
                "high": [91.0, 92.0, 96.0],
                "low": [89.0, 90.0, 94.0],
                "close": [90.5, 91.5, 95.5],
                "futures_open": [101.0, 102.0, 110.0],
                "futures_high": [103.0, 104.0, 111.0],
                "futures_low": [99.0, 100.0, 109.0],
                "futures_close": [102.0, 103.0, 110.5],
                "mark_open": [100.5, 101.5, 109.5],
                "mark_high": [102.5, 103.5, 110.5],
                "mark_low": [98.5, 99.5, 108.5],
                "mark_close": [101.5, 102.5, 110.0],
            }
        ).to_parquet(path, index=False)

        hourly = _load_minute_hour_features(path)
        assert hourly.loc[0, "spot_open"] == pytest.approx(90.0)
        assert hourly.loc[0, "spot_close"] == pytest.approx(91.5)
        assert hourly.loc[0, "futures_open"] == pytest.approx(101.0)
        assert hourly.loc[0, "minute_high"] == pytest.approx(103.5)
        assert hourly.loc[0, "minute_low"] == pytest.approx(98.5)
        assert hourly.loc[0, "minute_close"] == pytest.approx(102.5)
