from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from crypto_trading_bot.research_v2.independent_oos.evaluation import (
    assign_frozen_blocks,
    binary_metrics,
    classify,
    time_block_bootstrap,
)


class EvaluationTests(unittest.TestCase):
    def test_metric_deltas_use_frozen_prior(self) -> None:
        y = np.array([0, 0, 1, 1], dtype=np.int8)
        p = np.array([0.1, 0.2, 0.8, 0.9])
        result = binary_metrics(y, p, 0.6)
        self.assertLess(result.delta_logloss, 0)
        self.assertLess(result.delta_brier, 0)
        self.assertAlmostEqual(result.positive_rate, 0.5)

    def test_predeclared_classification(self) -> None:
        self.assertEqual(classify(-0.01, -0.001, [-0.1, 0.1, -0.1]), "OOS_SUPPORTED")
        self.assertEqual(classify(-0.01, -0.001, [0.1, 0.1, -0.1]), "OOS_WEAK")
        self.assertEqual(classify(0.0, -0.001, [-0.1, -0.1, -0.1]), "OOS_NOT_SUPPORTED")

    def test_frozen_blocks_are_exhaustive(self) -> None:
        ts = pd.Series(pd.date_range("2024-01-01", periods=6, freq="15min", tz="UTC"))
        blocks = [
            {"start": ts.iloc[0].isoformat(), "end": ts.iloc[1].isoformat()},
            {"start": ts.iloc[2].isoformat(), "end": ts.iloc[3].isoformat()},
            {"start": ts.iloc[4].isoformat(), "end": ts.iloc[5].isoformat()},
        ]
        self.assertEqual(assign_frozen_blocks(ts, blocks).tolist(), [1, 1, 2, 2, 3, 3])

    def test_bootstrap_is_seed_deterministic(self) -> None:
        ts = pd.Series(pd.date_range("2024-01-01", periods=800, freq="15min", tz="UTC"))
        y = np.arange(800) % 2
        p = np.where(y, 0.55, 0.45)
        a = time_block_bootstrap(ts, y, p, 0.5, repetitions=25, seed=20260925)
        b = time_block_bootstrap(ts, y, p, 0.5, repetitions=25, seed=20260925)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
