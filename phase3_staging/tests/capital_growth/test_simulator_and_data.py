from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from crypto_trading_bot.research_v2.capital_growth.config import (
    PortfolioConfig,
    RiskConfig,
    StrategyConfig,
    portfolio_matrix,
)
from crypto_trading_bot.research_v2.capital_growth.data import data_preflight
from crypto_trading_bot.research_v2.capital_growth.simulator import simulate_portfolio
from crypto_trading_bot.research_v2.capital_growth.strategy import build_decision_frame, execution_events


def _market_frame(hours: int = 1200, freq: str = "h") -> pd.DataFrame:
    times = pd.date_range("2020-01-01", periods=hours, freq=freq, tz="UTC")
    x = np.arange(hours, dtype=float)
    close = np.where(x < hours * 0.55, 100.0 + x * 0.15, 100.0 + hours * 0.55 * 0.15 - (x - hours * 0.55) * 0.25)
    open_ = close + np.where(np.arange(hours) % 2 == 0, 0.05, -0.05)
    high = np.maximum(open_, close) + 0.3
    low = np.minimum(open_, close) - 0.3
    return pd.DataFrame(
        {
            "open_time": times,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": 100.0,
            "futures_open": open_,
            "futures_high": high,
            "futures_low": low,
            "futures_close": close,
            "mark_open": open_,
            "mark_high": high,
            "mark_low": low,
            "mark_close": close,
        }
    )


def test_decisions_are_available_only_after_source_close() -> None:
    frame = _market_frame(600)
    decisions = build_decision_frame(frame)
    events = execution_events(decisions, frame["open_time"])
    assert events
    frame_by_index = frame.reset_index(drop=True)
    for index, signal in events[:20]:
        assert frame_by_index.loc[index, "open_time"] > signal["decision_at"]


def test_simulator_runs_cycle_and_records_events() -> None:
    frame = _market_frame(1600)
    funding = pd.DataFrame(
        {
            "funding_time": pd.date_range("2020-01-01", periods=220, freq="8h", tz="UTC"),
            "funding_rate": 0.00005,
        }
    )
    config = PortfolioConfig(
        name="TEST",
        spot_fraction=0.40,
        spot_mode="SWING",
        hedge_enabled=True,
        averaging_enabled=True,
        strategy=StrategyConfig(min_hold_hours=24, hedge_atr_mult=1.0, averaging_atr_levels=(2.0, 4.0)),
    )
    decisions = build_decision_frame(frame)
    events = execution_events(decisions, frame["open_time"])
    result = simulate_portfolio(frame, funding, events, config)
    assert result.metrics["final_equity"] > 0
    assert result.metrics["primary_trade_count"] >= 1
    assert not result.events.empty
    assert {"time", "event", "state"}.issubset(result.events.columns)


def test_predeclared_portfolio_matrix_has_twelve_runnable_configs() -> None:
    frame = _market_frame(1000)
    funding = pd.DataFrame(
        {
            "funding_time": pd.date_range("2020-01-01", periods=140, freq="8h", tz="UTC"),
            "funding_rate": 0.0,
        }
    )
    decisions = build_decision_frame(frame)
    events = execution_events(decisions, frame["open_time"])
    matrix = portfolio_matrix()
    assert len(matrix) == 12
    finals = [
        simulate_portfolio(frame, funding, events, config).metrics["final_equity"]
        for config in matrix
    ]
    assert all(np.isfinite(finals))
    assert all(value > 0 for value in finals)


def test_aggressive_synthetic_rule_opens_and_closes_hedge() -> None:
    frame = _market_frame(6)
    prices = [100.0, 100.0, 99.0, 99.0, 99.0, 99.0]
    for column in (
        "open",
        "high",
        "low",
        "close",
        "futures_open",
        "futures_high",
        "futures_low",
        "futures_close",
        "mark_open",
        "mark_high",
        "mark_low",
        "mark_close",
    ):
        frame[column] = prices
    funding = pd.DataFrame(
        {
            "funding_time": pd.date_range("2020-01-01", periods=1, freq="8h", tz="UTC"),
            "funding_rate": 0.0,
        }
    )
    config = PortfolioConfig(
        name="HEDGE_TRIGGER_TEST",
        spot_fraction=0.0,
        spot_mode="SWING",
        hedge_enabled=True,
        averaging_enabled=False,
        strategy=StrategyConfig(
            min_hold_hours=10000,
            hedge_atr_mult=0.01,
            averaging_atr_levels=(100.0,),
        ),
        risk=RiskConfig(max_loss_fraction_total_equity=1.0),
        rebalance_after_cycle=False,
    )
    events = [
        (
            0,
            {
                "decision_at": frame.loc[0, "open_time"],
                "direction": 1,
                "atr": 1.0,
                "fast": 100.0,
                "slow": 99.0,
                "close": 100.0,
                "volume": 100_000.0,
            },
        ),
        (
            1,
            {
                "decision_at": frame.loc[1, "open_time"],
                "direction": -1,
                "atr": 1.0,
                "fast": 100.0,
                "slow": 100.0,
                "close": 99.0,
                "volume": 100_000.0,
            },
        ),
        (
            2,
            {
                "decision_at": frame.loc[2, "open_time"],
                "direction": 1,
                "atr": 1.0,
                "fast": 99.0,
                "slow": 99.0,
                "close": 99.0,
                "volume": 100_000.0,
            },
        ),
    ]
    result = simulate_portfolio(frame, funding, events, config)
    assert (result.events["event"] == "HEDGE_OPENED").any()
    assert (result.events["event"] == "HEDGE_CLOSED").any()
    assert result.metrics["hedge_trade_count"] >= 1


def test_aggressive_synthetic_rule_performs_averaging() -> None:
    frame = _market_frame(1200)
    pulls = (frame["open_time"] >= pd.Timestamp("2020-01-10T00:00:00Z")) & (
        frame["open_time"] < pd.Timestamp("2020-01-11T00:00:00Z")
    )
    for col in ("open", "high", "low", "close", "futures_open", "futures_high", "futures_low", "futures_close", "mark_open", "mark_high", "mark_low", "mark_close"):
        frame.loc[pulls, col] = frame.loc[pulls, col] - 8.0
    funding = pd.DataFrame(
        {
            "funding_time": pd.date_range("2020-01-01", periods=150, freq="8h", tz="UTC"),
            "funding_rate": 0.0,
        }
    )
    config = PortfolioConfig(
        name="AVERAGE_TRIGGER_TEST",
        spot_fraction=0.0,
        spot_mode="SWING",
        hedge_enabled=False,
        averaging_enabled=True,
        strategy=StrategyConfig(
            min_hold_hours=10000,
            hedge_atr_mult=100.0,
            averaging_atr_levels=(0.01, 0.02),
        ),
        rebalance_after_cycle=False,
    )
    decisions = build_decision_frame(frame)
    events = execution_events(decisions, frame["open_time"])
    result = simulate_portfolio(frame, funding, events, config)
    assert (result.events["event"] == "PRIMARY_AVERAGED").any()
    assert result.metrics["averaging_count"] >= 1


def test_data_preflight_blocks_missing_funding() -> None:
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    end = datetime(2020, 1, 2, tzinfo=timezone.utc)
    times = pd.date_range(start, end, inclusive="left", freq="min", tz="UTC")
    market = pd.DataFrame({"open_time": times})
    funding = pd.DataFrame({"funding_time": pd.to_datetime([], utc=True), "funding_rate": []})
    report = data_preflight(
        spot=market,
        futures=market,
        mark=market,
        funding=funding,
        merged=market,
        start=start,
        end=end,
    )
    assert report["status"] == "BLOCKED"
    assert any("funding" in blocker for blocker in report["blockers"])
