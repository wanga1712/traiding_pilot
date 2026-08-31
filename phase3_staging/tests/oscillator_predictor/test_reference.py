"""Tests for OSCILLATOR-PREDICTOR-REFERENCE-1."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from crypto_trading_bot.research_v2.oscillator_predictor.dno import DNO_DEFAULT_PERIOD, compute_dno_feature_series
from crypto_trading_bot.research_v2.oscillator_predictor.dynamic_predictor import PredictorConfig, compute_predictor_at_index
from crypto_trading_bot.research_v2.oscillator_predictor.inverse import price_for_next_detrended_value, verify_inverse_roundtrip
from crypto_trading_bot.research_v2.oscillator_predictor.peaks import confirmed_extrema_at
from crypto_trading_bot.research_v2.oscillator_predictor.run_validate import (
    run_batch_streaming_parity,
    run_future_leakage_test,
    run_future_mutation_test,
    run_gap_independence_tests,
    run_numeric_reference_tests,
    run_peak_confirmation_test,
)
from crypto_trading_bot.research_v2.oscillator_predictor.streaming import StreamingOscillatorPredictor
from crypto_trading_bot.research_v2.indicator_engine.bars import bars_to_arrays


def _bars(closes: list[float]) -> list[dict]:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    out = []
    for i, c in enumerate(closes):
        t = base + timedelta(hours=i)
        out.append(
            {
                "open_time": t,
                "close_time": t,
                "open": c,
                "high": c,
                "low": c,
                "close": c,
                "volume": 1.0,
                "timeframe": "1H",
            }
        )
    return out


def test_dno_inverse_roundtrip() -> None:
    closes = np.array([100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
    assert verify_inverse_roundtrip(closes, period=7, target=2.5)
    assert run_numeric_reference_tests()["DNO_INVERSE_OB_ROUNDTRIP"] == "PASS"
    assert run_numeric_reference_tests()["DNO_INVERSE_OS_ROUNDTRIP"] == "PASS"


def test_peak_confirmation() -> None:
    assert run_peak_confirmation_test()["PEAK_CONFIRMATION_CAUSALITY"] == "PASS"


def test_anti_leakage() -> None:
    assert run_future_leakage_test()["FUTURE_PEAK_LEAKAGE_TEST"] == "PASS"
    assert run_future_mutation_test()["PREDICTOR_FUTURE_MUTATION_TEST"] == "PASS"


def test_gap_independence() -> None:
    r = run_gap_independence_tests()
    assert r["DNO_POST_GAP_INDEPENDENCE"] == "PASS"
    assert r["PREDICTOR_POST_GAP_INDEPENDENCE"] == "PASS"


def test_batch_streaming_parity() -> None:
    assert run_batch_streaming_parity()["PREDICTOR_BATCH_STREAMING_PARITY"] == "PASS"


def test_manual_inverse_formula() -> None:
    closes = np.array([100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
    n = 7
    d = 2.5
    s = float(np.sum(closes))
    expected = (n * d + s) / (n - 1)
    got = price_for_next_detrended_value(closes, period=n, target_oscillator_value=d)
    assert abs(got - expected) < 1e-9


if __name__ == "__main__":
    test_dno_inverse_roundtrip()
    test_peak_confirmation()
    test_anti_leakage()
    test_gap_independence()
    test_batch_streaming_parity()
    test_manual_inverse_formula()
    print("ALL TESTS PASS")
