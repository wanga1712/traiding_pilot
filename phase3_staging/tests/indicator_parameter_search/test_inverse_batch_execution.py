"""Batch inverse execution performance and parity tests."""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

from crypto_trading_bot.research_v2.indicator_engine.tests.fixtures import make_bars
from crypto_trading_bot.research_v2.indicator_parameter_search.candidate_registry import load_frozen_registry
from crypto_trading_bot.research_v2.indicator_parameter_search.candidate_routing import (
    INVERSE_PARAMETER_SET_ROUTES,
    discovery_fixture_bars_by_tf,
    run_v2_integrity_gates,
)
from crypto_trading_bot.research_v2.indicator_parameter_search.config import split_bounds
from crypto_trading_bot.research_v2.indicator_parameter_search.signals_bank import (
    _generate_inverse_signals,
    _generate_inverse_signals_slow,
    row_parameters,
)
from crypto_trading_bot.research_v2.inverse_predictors.batch_thresholds import (
    AUTHORIZED_INVERSE_PARAMETER_SETS,
    batch_threshold_at,
    clear_threshold_cache,
    compute_inverse_threshold_series,
    slow_reference_threshold_at,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FROZEN_CSV_V2 = REPO_ROOT / "artifacts" / "MULTITF-INDICATOR-PARAMETER-SEARCH-1" / "candidate_registry_snapshot_v2.csv"


def _bars(n: int = 500, *, minutes: int = 60):
    closes = [100 + np.sin(i / 7) * 5 + i * 0.02 for i in range(n)]
    return make_bars(closes, minutes=minutes)


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_threshold_cache()
    yield
    clear_threshold_cache()


def test_batch_reference_parity_all_routes():
    bars = _bars(800)
    mismatches = []
    for pred_id in AUTHORIZED_INVERSE_PARAMETER_SETS:
        series = compute_inverse_threshold_series(bars, parameter_set_id=pred_id, source_timeframe="1H")
        sample = list(range(200, len(bars) - 2, 17))
        for i in sample:
            slow = slow_reference_threshold_at(bars, index=i, parameter_set_id=pred_id, source_timeframe="1H")
            batch = batch_threshold_at(series, i)
            if slow is None and batch is None:
                continue
            if slow is None or batch is None:
                mismatches.append((pred_id, i, slow, batch))
                continue
            if abs(slow - batch) > 1e-9:
                mismatches.append((pred_id, i, slow, batch))
    assert mismatches == [], mismatches[:5]


def test_batch_signal_parity():
    registry = load_frozen_registry(FROZEN_CSV_V2)
    bars = discovery_fixture_bars_by_tf()["1H"]
    disc_start, disc_end = split_bounds("DISCOVERY")
    inv = [r for r in registry if r["family"] == "INVERSE_PREDICTOR" and r["decision_tf"] == "1H"][:6]
    cache: dict = {}
    for row in inv:
        slow = _generate_inverse_signals_slow(
            bars,
            row,
            scan_start_iso=disc_start.isoformat(),
            scan_end_iso=disc_end.isoformat(),
            stride=5,
        )
        fast = _generate_inverse_signals(
            bars,
            row,
            scan_start_iso=disc_start.isoformat(),
            scan_end_iso=disc_end.isoformat(),
            stride=5,
            threshold_cache=cache,
        )
        assert slow == fast, row["candidate_id"]


def test_batch_scaling_near_linear():
    times = {}
    for n in (5000, 10000, 20000):
        bars = _bars(n)
        t0 = time.perf_counter()
        compute_inverse_threshold_series(bars, parameter_set_id="PRED_DMA_3X3_CROSS_UP_V1", source_timeframe="1H")
        times[n] = time.perf_counter() - t0
    ratio = times[20000] / times[5000]
    assert ratio < 6.0, f"scaling ratio {ratio} suggests worse than near-linear"


def test_no_prefix_predict_in_production_path():
    from crypto_trading_bot.research_v2.indicator_parameter_search.candidate_routing import (
        run_inverse_production_path_audit,
    )

    gates = run_inverse_production_path_audit()
    assert gates["FULL_HISTORY_PREFIX_PREDICT_LOOP"] == "REMOVED"
    assert gates["FULL_DISCOVERY_PER_BAR_PREDICT_CALLS"] == 0
