from __future__ import annotations

import pandas as pd
import pytest

from crypto_trading_bot.research_v2.capital_growth.accounting import FuturesAccount, SpotAccount
from crypto_trading_bot.research_v2.capital_growth.config import ExecutionConfig, RiskConfig
from crypto_trading_bot.research_v2.capital_growth.risk import maximum_margin_for_limit, risk_report


def test_primary_and_hedge_realized_pnl_are_separate() -> None:
    futures = FuturesAccount(free_collateral=100.0)
    primary = futures.open_position(
        "PRIMARY",
        side=1,
        time=pd.Timestamp("2024-01-01T00:00:00Z"),
        price=100.0,
        margin=10.0,
        slippage=0.0,
        fee_rate=0.0,
        leverage=10.0,
    )
    hedge = futures.open_position(
        "HEDGE",
        side=-1,
        time=pd.Timestamp("2024-01-01T01:00:00Z"),
        price=95.0,
        margin=10.0,
        slippage=0.0,
        fee_rate=0.0,
        leverage=10.0,
    )
    assert primary.quantity == pytest.approx(1.0)
    assert hedge.quantity == pytest.approx(100.0 / 95.0)
    futures.close_position(
        "HEDGE",
        time=pd.Timestamp("2024-01-01T02:00:00Z"),
        price=90.0,
        slippage=0.0,
        fee_rate=0.0,
        reason="TEST",
    )
    futures.close_position(
        "PRIMARY",
        time=pd.Timestamp("2024-01-01T03:00:00Z"),
        price=90.0,
        slippage=0.0,
        fee_rate=0.0,
        reason="TEST",
    )
    assert futures.realized_primary == pytest.approx(-10.0)
    assert futures.realized_hedge > 0
    assert futures.free_collateral == pytest.approx(100.0 - 10.0 + futures.realized_hedge)


def test_risk_engine_reduces_ten_x_position_to_five_percent_limit() -> None:
    futures = FuturesAccount(free_collateral=40.0)
    spot = SpotAccount(cash=60.0)
    margin, report = maximum_margin_for_limit(
        futures,
        spot,
        price=100.0,
        side=1,
        desired_margin=16.0,
        execution=ExecutionConfig(),
        risk=RiskConfig(),
    )
    assert 0.0 < margin < 16.0
    assert report["passes"]
    assert report["worst_loss_fraction"] <= 0.05 + 1e-12


def test_hedge_can_reduce_directional_risk() -> None:
    futures = FuturesAccount(free_collateral=80.0)
    spot = SpotAccount(cash=20.0)
    futures.open_position(
        "PRIMARY",
        side=1,
        time=pd.Timestamp("2024-01-01T00:00:00Z"),
        price=100.0,
        margin=2.0,
        slippage=0.0,
        fee_rate=0.0,
        leverage=10.0,
    )
    without = risk_report(futures, spot, price=100.0, execution=ExecutionConfig(), risk=RiskConfig())
    first, _ = maximum_margin_for_limit(
        futures,
        spot,
        price=100.0,
        side=-1,
        desired_margin=2.0,
        execution=ExecutionConfig(),
        risk=RiskConfig(),
    )
    with_hedge = risk_report(
        futures,
        spot,
        price=100.0,
        proposed_side=-1,
        proposed_margin=first,
        execution=ExecutionConfig(),
        risk=RiskConfig(),
    )
    assert with_hedge["worst_loss_usdt"] <= without["worst_loss_usdt"] + 1e-9


def test_liquidation_prices_are_inside_ten_x_band() -> None:
    futures = FuturesAccount(free_collateral=20.0)
    position = futures.open_position(
        "PRIMARY",
        side=1,
        time=pd.Timestamp("2024-01-01T00:00:00Z"),
        price=100.0,
        margin=2.0,
        slippage=0.0,
        fee_rate=0.0,
        leverage=10.0,
    )
    assert 89.0 < position.liquidation_price(0.004, 0.0005) < 91.0


def test_position_never_spends_entry_fee_buffer() -> None:
    futures = FuturesAccount(free_collateral=10.0)
    maximum = 10.0 / ((1.0 + 10.0 * 0.0005) * (1.0 + 1e-12))
    futures.open_position(
        "PRIMARY",
        side=1,
        time=pd.Timestamp("2024-01-01T00:00:00Z"),
        price=100.0,
        margin=maximum,
        slippage=0.0,
        fee_rate=0.0005,
        leverage=10.0,
    )
    assert futures.free_collateral >= 0
