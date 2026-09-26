from __future__ import annotations

import unittest

import pandas as pd

from crypto_trading_bot.research_v2.provisional_execution.evaluation import (
    classify_execution,
    simulate_strategy,
)


def fixtures(prices: list[float], probabilities: list[float]):
    start = pd.Timestamp("2024-01-01T00:00:00Z")
    bars = pd.DataFrame({
        "open_time": pd.date_range(start, periods=len(prices), freq="min", tz="UTC"),
        "open": prices,
    })
    decisions = pd.date_range(start - pd.Timedelta(microseconds=1), periods=len(probabilities), freq="15min", tz="UTC")
    predictions = pd.DataFrame({"row_id": range(len(probabilities)), "decision_at": decisions, "p_up": probabilities})
    blocks = [{"start": decisions[0].isoformat(), "end": decisions[-1].isoformat()}] * 3
    return predictions, bars, blocks


class SimulatorTests(unittest.TestCase):
    def test_exact_next_minute_entry_and_fixed_exit(self) -> None:
        predictions, bars, blocks = fixtures([100.0] * 30 + [102.0] + [102.0] * 50, [0.9])
        result = simulate_strategy(
            predictions, bars, horizon_minutes=30, short_threshold=0.1, long_threshold=0.8,
            fee_per_side=0.0, slippage_per_side=0.0, starting_equity=100.0,
            oos_start=predictions.decision_at.iloc[0], oos_end=predictions.decision_at.iloc[-1],
            frozen_blocks=blocks, funding_stress_per_crossing=0.0001,
            sensitivity_costs_bps=[0, 13],
        )
        trade = result.trades.iloc[0]
        self.assertEqual(trade.entry_time, pd.Timestamp("2024-01-01T00:00:00Z"))
        self.assertEqual(trade.exit_time, pd.Timestamp("2024-01-01T00:30:00Z"))
        self.assertAlmostEqual(result.metrics["ending_equity_usdt"], 102.0)

    def test_one_position_ignores_intermediate_signal(self) -> None:
        predictions, bars, blocks = fixtures([100.0] * 100, [0.9, 0.9, 0.9, 0.9])
        result = simulate_strategy(
            predictions, bars, horizon_minutes=30, short_threshold=0.1, long_threshold=0.8,
            fee_per_side=0.0, slippage_per_side=0.0, starting_equity=100.0,
            oos_start=predictions.decision_at.iloc[0], oos_end=predictions.decision_at.iloc[-1],
            frozen_blocks=blocks, funding_stress_per_crossing=0.0, sensitivity_costs_bps=[0],
        )
        self.assertEqual(len(result.trades), 2)
        self.assertEqual(result.metrics["ignored_signals_while_position_open"], 2)

    def test_missing_exact_exit_is_skipped(self) -> None:
        predictions, bars, blocks = fixtures([100.0] * 80, [0.9, 0.9])
        bars = bars[bars.open_time != pd.Timestamp("2024-01-01T00:30:00Z")]
        result = simulate_strategy(
            predictions, bars, horizon_minutes=30, short_threshold=0.1, long_threshold=0.8,
            fee_per_side=0.0, slippage_per_side=0.0, starting_equity=100.0,
            oos_start=predictions.decision_at.iloc[0], oos_end=predictions.decision_at.iloc[-1],
            frozen_blocks=blocks, funding_stress_per_crossing=0.0, sensitivity_costs_bps=[0],
        )
        self.assertEqual(result.metrics["skipped_missing_exit_bar"], 1)

    def test_ruin_stops_new_positions(self) -> None:
        prices = [100.0] * 100
        prices[30] = 0.0
        predictions, bars, blocks = fixtures(prices, [0.9, 0.9, 0.9])
        result = simulate_strategy(
            predictions, bars, horizon_minutes=30, short_threshold=0.1, long_threshold=0.8,
            fee_per_side=0.0, slippage_per_side=0.0, starting_equity=100.0,
            oos_start=predictions.decision_at.iloc[0], oos_end=predictions.decision_at.iloc[-1],
            frozen_blocks=blocks, funding_stress_per_crossing=0.0, sensitivity_costs_bps=[0],
        )
        self.assertEqual(result.metrics["account_ruined"], "YES")
        self.assertEqual(result.metrics["trades_before_ruin"], 0)
        self.assertEqual(len(result.trades), 1)

    def test_predeclared_execution_classification(self) -> None:
        self.assertEqual(classify_execution(-1, -2, 0.8, [-1, -1, -1], 98), "EXECUTION_NOT_SUPPORTED")
        self.assertEqual(classify_execution(2, -1, 0.8, [1, -1, -1], 99), "EXECUTION_WEAK")
        self.assertEqual(classify_execution(4, 2, 1.2, [1, 1, -1], 102), "EXECUTION_SUPPORTED")


if __name__ == "__main__":
    unittest.main()
