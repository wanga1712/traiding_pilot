from __future__ import annotations

import unittest

import pandas as pd

from crypto_trading_bot.research_v2.policy_research.evaluation import direction_at, should_exit, simulate_policy


def candidate(**changes):
    base = {
        "candidate_id": "TEST", "entry_source": "30M_ONLY",
        "confidence_quantile": 0.95, "long_threshold_30m": 0.8,
        "short_threshold_30m": 0.2, "long_threshold_60m": 0.8,
        "short_threshold_60m": 0.2, "entry_persistence_decisions": 1,
        "cooldown_minutes": 0, "exit_family": "CONFIDENCE_LOSS",
        "minimum_hold_minutes": 15, "maximum_hold_minutes": 60,
    }
    base.update(changes)
    return base


def data(probabilities, prices=None):
    start = pd.Timestamp("2024-01-01T00:14:59.999999Z")
    decisions = pd.DataFrame({
        "row_id": range(len(probabilities)),
        "decision_at": pd.date_range(start, periods=len(probabilities), freq="15min", tz="UTC"),
        "p30": probabilities, "p60": probabilities,
    })
    index = pd.date_range("2024-01-01T00:00:00Z", periods=240, freq="min", tz="UTC")
    values = prices if prices is not None else [100.0 + i * 0.01 for i in range(len(index))]
    return decisions, pd.Series(values, index=index)


class PolicyEvaluationTests(unittest.TestCase):
    def test_both_agree_requires_same_direction(self):
        c = candidate(entry_source="BOTH_AGREE")
        self.assertEqual(direction_at(0.9, 0.9, c), 1)
        self.assertEqual(direction_at(0.9, 0.1, c), 0)
        self.assertEqual(direction_at(0.1, 0.1, c), -1)

    def test_persistence_and_causal_next_minute_fill(self):
        decisions, opens = data([0.9, 0.9, 0.4, 0.4, 0.4])
        result = simulate_policy(decisions, opens, candidate(entry_persistence_decisions=2), fee_per_side=0, slippage_per_side=0)
        self.assertEqual(len(result.trades), 1)
        self.assertEqual(result.trades.iloc[0].entry_time, pd.Timestamp("2024-01-01T00:30:00Z"))
        self.assertEqual(result.trades.iloc[0].exit_time, pd.Timestamp("2024-01-01T01:00:00Z"))

    def test_minimum_hold_defers_confidence_loss(self):
        decisions, opens = data([0.9, 0.4, 0.4, 0.4, 0.4])
        result = simulate_policy(decisions, opens, candidate(minimum_hold_minutes=30), fee_per_side=0, slippage_per_side=0)
        self.assertEqual(result.trades.iloc[0].exit_time, pd.Timestamp("2024-01-01T01:00:00Z"))

    def test_safety_cap_uses_exact_canonical_minute(self):
        decisions, opens = data([0.9] * 8)
        result = simulate_policy(decisions, opens, candidate(maximum_hold_minutes=60), fee_per_side=0, slippage_per_side=0)
        self.assertEqual(result.trades.iloc[0].entry_time, pd.Timestamp("2024-01-01T00:15:00Z"))
        self.assertEqual(result.trades.iloc[0].exit_time, pd.Timestamp("2024-01-01T01:15:00Z"))

    def test_reverse_threshold_semantics(self):
        c = candidate(entry_source="BOTH_AGREE", exit_family="REVERSE_THRESHOLD")
        self.assertFalse(should_exit(1, 0.1, 0.9, c))
        self.assertTrue(should_exit(1, 0.1, 0.1, c))

    def test_missing_bar_is_skipped_and_never_gap_filled(self):
        decisions, opens = data([0.9, 0.4, 0.4])
        opens = opens.drop(pd.Timestamp("2024-01-01T00:15:00Z"))
        result = simulate_policy(decisions, opens, candidate(), fee_per_side=0, slippage_per_side=0)
        self.assertEqual(result.metrics["missing_required_bar_count"], 1)
        self.assertEqual(result.metrics["invalid_gap_fill_count"], 0)
        self.assertEqual(result.metrics["trade_count"], 0)


if __name__ == "__main__":
    unittest.main()
