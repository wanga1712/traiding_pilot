from __future__ import annotations

import pandas as pd
import pytest

from crypto_trading_bot.research_v2.capital_growth.accounting import (
    FuturesAccount,
    SpotAccount,
    TransferLedger,
)
from crypto_trading_bot.research_v2.capital_growth.config import (
    ExecutionConfig,
    PortfolioConfig,
    RiskConfig,
    StrategyConfig,
)
from crypto_trading_bot.research_v2.capital_growth.risk import risk_report
from crypto_trading_bot.research_v2.capital_growth.simulator import simulate_portfolio


def _flat_frame(rows: int, *, price: float = 100.0, volume: float = 100_000.0) -> pd.DataFrame:
    times = pd.date_range("2024-01-01", periods=rows, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "open_time": times,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": volume,
            "futures_open": price,
            "futures_high": price,
            "futures_low": price,
            "futures_close": price,
            "mark_open": price,
            "mark_high": price,
            "mark_low": price,
            "mark_close": price,
        }
    )


def _signal(
    direction: int = 1,
    *,
    price: float = 100.0,
    volume: float = 100_000.0,
) -> dict:
    return {
        "decision_at": pd.Timestamp("2024-01-01T00:00:00Z"),
        "direction": direction,
        "atr": 1.0,
        "fast": price,
        "slow": price,
        "close": price,
        "volume": volume,
    }


def _no_funding() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "funding_time": pd.to_datetime([], utc=True),
            "funding_rate": pd.Series(dtype=float),
        }
    )


def test_spot_futures_transfer_ledger_is_capital_conserving() -> None:
    spot = SpotAccount(cash=60.0)
    futures = FuturesAccount(free_collateral=40.0)
    ledger = TransferLedger()
    before = spot.cash + futures.free_collateral

    moved = ledger.transfer_spot_to_futures(
        spot,
        futures,
        time=pd.Timestamp("2024-01-01", tz="UTC"),
        amount=15.0,
        purpose="TEST",
    )
    returned = ledger.transfer_futures_to_spot(
        spot,
        futures,
        time=pd.Timestamp("2024-01-01T01:00:00Z"),
        amount=5.0,
        purpose="TEST",
    )

    assert moved == pytest.approx(15.0)
    assert returned == pytest.approx(5.0)
    assert spot.cash == pytest.approx(50.0)
    assert futures.free_collateral == pytest.approx(50.0)
    assert spot.cash + futures.free_collateral == pytest.approx(before)
    assert ledger.spot_to_futures == pytest.approx(15.0)
    assert ledger.futures_to_spot == pytest.approx(5.0)


def test_closed_hedge_profit_is_counted_once_when_reinvested() -> None:
    futures = FuturesAccount(free_collateral=100.0)
    futures.open_position(
        "PRIMARY",
        side=1,
        time=pd.Timestamp("2024-01-01", tz="UTC"),
        price=100.0,
        margin=10.0,
        slippage=0.0,
        fee_rate=0.0,
        leverage=10.0,
    )
    futures.open_position(
        "HEDGE",
        side=-1,
        time=pd.Timestamp("2024-01-01T01:00:00Z"),
        price=95.0,
        margin=10.0,
        slippage=0.0,
        fee_rate=0.0,
        leverage=10.0,
    )
    equity_before_close = futures.equity(90.0)
    futures.close_position(
        "HEDGE",
        time=pd.Timestamp("2024-01-01T02:00:00Z"),
        price=90.0,
        slippage=0.0,
        fee_rate=0.0,
        reason="TEST",
    )
    assert futures.equity(90.0) == pytest.approx(equity_before_close)

    equity_before_average = futures.equity(90.0)
    futures.average_primary(
        time=pd.Timestamp("2024-01-01T03:00:00Z"),
        price=90.0,
        margin=5.0,
        slippage=0.0,
        fee_rate=0.0,
        leverage=10.0,
    )
    assert futures.equity(90.0) == pytest.approx(equity_before_average)


def test_partial_fill_respects_notional_cap_and_minimum() -> None:
    futures = FuturesAccount(free_collateral=100.0)
    position = futures.open_position(
        "PRIMARY",
        side=1,
        time=pd.Timestamp("2024-01-01", tz="UTC"),
        price=100.0,
        margin=20.0,
        slippage=0.0,
        fee_rate=0.0,
        leverage=10.0,
        max_notional=50.0,
        min_notional=5.0,
    )
    assert position.margin == pytest.approx(5.0)
    assert position.metadata["requested_notional"] == pytest.approx(200.0)
    assert position.metadata["filled_notional"] == pytest.approx(50.0)
    assert position.metadata["unfilled_notional"] == pytest.approx(150.0)

    with pytest.raises(ValueError, match="below minimum"):
        FuturesAccount(free_collateral=100.0).open_position(
            "PRIMARY",
            side=1,
            time=pd.Timestamp("2024-01-01", tz="UTC"),
            price=100.0,
            margin=20.0,
            slippage=0.0,
            fee_rate=0.0,
            leverage=10.0,
            max_notional=4.0,
            min_notional=5.0,
        )


def test_risk_report_includes_spot_but_limits_only_the_trading_thesis() -> None:
    spot = SpotAccount(cash=0.0, eth=1.0)
    futures = FuturesAccount(free_collateral=100.0)
    report = risk_report(
        futures,
        spot,
        price=100.0,
        execution=ExecutionConfig(),
        risk=RiskConfig(),
    )
    assert report["worst_total_portfolio_loss_usdt"] > report["worst_loss_usdt"]
    assert report["spot_exposure_usdt"] == pytest.approx(100.0)
    assert report["passes"]


def test_mark_price_extreme_causes_liquidation() -> None:
    frame = _flat_frame(6)
    frame.loc[2, ["mark_low", "mark_close"]] = [89.0, 90.0]
    config = PortfolioConfig(
        name="LIQUIDATION",
        spot_fraction=0.0,
        spot_mode="SWING",
        hedge_enabled=False,
        averaging_enabled=False,
        strategy=StrategyConfig(primary_risk_headroom_fraction=1.0),
        execution=ExecutionConfig(),
        risk=RiskConfig(max_loss_fraction_total_equity=1.0),
        rebalance_after_cycle=False,
    )
    result = simulate_portfolio(frame, _no_funding(), [(0, _signal())], config)
    assert result.metrics["liquidation_count"] >= 1
    assert (result.events["event"] == "PRIMARY_LIQUIDATED").any()


def test_continuous_risk_monitor_exits_before_liquidation() -> None:
    frame = _flat_frame(8)
    for column in ("open", "high", "low", "close", "futures_open", "futures_high", "futures_low", "futures_close"):
        frame.loc[4:, column] = 78.0
    frame.loc[4:, "mark_high"] = 80.0
    frame.loc[4:, "mark_low"] = 78.0
    frame.loc[4:, "mark_close"] = 78.0
    config = PortfolioConfig(
        name="CONTINUOUS_RISK",
        spot_fraction=0.0,
        spot_mode="SWING",
        hedge_enabled=False,
        averaging_enabled=False,
        strategy=StrategyConfig(primary_risk_headroom_fraction=1.0),
        execution=ExecutionConfig(),
        risk=RiskConfig(max_loss_fraction_total_equity=0.05),
        rebalance_after_cycle=False,
    )
    result = simulate_portfolio(frame, _no_funding(), [(0, _signal())], config)
    assert (result.events["event"] == "CONTINUOUS_RISK_LIMIT_BREACH").any()
    assert result.metrics["risk_exit_count"] >= 1
    assert result.metrics["state"] == "RISK_EXIT"


def test_order_capacity_blocks_too_small_entry() -> None:
    frame = _flat_frame(6, volume=1.0)
    config = PortfolioConfig(
        name="SMALL_ORDER",
        spot_fraction=0.0,
        spot_mode="SWING",
        hedge_enabled=False,
        averaging_enabled=False,
        strategy=StrategyConfig(primary_risk_headroom_fraction=1.0),
        execution=ExecutionConfig(),
        risk=RiskConfig(max_loss_fraction_total_equity=1.0),
        rebalance_after_cycle=False,
    )
    result = simulate_portfolio(frame, _no_funding(), [(0, _signal(volume=1.0))], config)
    assert result.metrics["primary_trade_count"] == 0
    assert (result.events["event"] == "PRIMARY_SKIPPED").any()


def test_post_cycle_rebalance_records_spot_futures_transfer_without_capital_gain() -> None:
    frame = _flat_frame(8)
    frame.loc[2:, ["open", "high", "low", "close", "futures_open", "futures_high", "futures_low", "futures_close", "mark_open", "mark_high", "mark_low", "mark_close"]] = 101.0
    config = PortfolioConfig(
        name="REBALANCE",
        spot_fraction=0.60,
        spot_mode="HOLD",
        hedge_enabled=False,
        averaging_enabled=False,
        strategy=StrategyConfig(
            primary_risk_headroom_fraction=1.0,
            min_hold_hours=0,
        ),
        execution=ExecutionConfig(),
        risk=RiskConfig(max_loss_fraction_total_equity=1.0),
        rebalance_after_cycle=True,
    )
    decisions = [
        (0, _signal(direction=1)),
        (
            1,
            {
                **_signal(direction=-1, price=101.0),
                "decision_at": frame.loc[1, "open_time"],
            },
        ),
    ]
    result = simulate_portfolio(frame, _no_funding(), decisions, config)
    assert (result.events["event"] == "REBALANCED").any()
    assert result.metrics["transfer_count"] >= 1
    assert result.metrics["final_equity"] <= result.metrics["max_equity"] + 1e-9
