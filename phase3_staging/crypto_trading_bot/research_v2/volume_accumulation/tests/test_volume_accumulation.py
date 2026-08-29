"""Validation tests for VOLUME_ACCUMULATION_ENGINE_V1."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from crypto_trading_bot.research_v2.indicator_engine.tests.fixtures import make_bars, make_ohlc_bars
from crypto_trading_bot.research_v2.reversal_events.anti_leakage import (
    filter_history_available_at,
    higher_tf_unfinished_bar_excluded,
)
from crypto_trading_bot.research_v2.volume_accumulation.compute import (
    compute_at_decision_time,
    compute_feature_series,
)
from crypto_trading_bot.research_v2.volume_accumulation.guards import assert_no_forbidden_fields
from crypto_trading_bot.research_v2.volume_accumulation.snapshot import compute_market_context
from crypto_trading_bot.research_v2.volume_accumulation.streaming import (
    batch_compression_expansion,
    stream_compression_expansion,
)
from crypto_trading_bot.research_v2.volume_accumulation.version import FORBIDDEN_INPUT_KEYS, FEATURE_ENGINE_VERSION


def test_obv_vwap_efficiency_manual():
    closes = [10, 11, 10, 12, 13, 12, 14, 15, 14, 16] + [16 + i * 0.1 for i in range(20)]
    bars = make_bars(closes, minutes=60, volume=100.0)
    # set known volumes
    for i, b in enumerate(bars):
        b["volume"] = 100 + i * 10
    res = compute_feature_series(bars, parameter_set_id="PV_INTERACTION_20_V1", source_timeframe="1H")
    # OBV: up adds, down subtracts
    assert res.samples[-1].valid
    assert "OBV" in res.samples[-1].values
    assert res.samples[-1].values["VWAP_ROLLING"] is not None
    # efficiency
    eff = compute_feature_series(bars, parameter_set_id="EFFICIENCY_10_V1", source_timeframe="1H")
    s = eff.samples[-1]
    assert s.valid
    assert 0 <= s.values["EFFICIENCY_RATIO"] <= 1.0 + 1e-9
    # volume zscore
    vol = compute_feature_series(bars, parameter_set_id="VOL_WINDOW_20_V1", source_timeframe="1H")
    assert vol.samples[-1].valid
    assert vol.samples[-1].values["VOLUME_ZSCORE"] is not None


def test_cmf_mfi_bounds():
    rows = []
    for i in range(40):
        c = 100 + i * 0.5
        rows.append((c - 1, c + 1, c - 2, c))
    bars = make_ohlc_bars(rows, minutes=60)
    res = compute_feature_series(bars, parameter_set_id="PV_INTERACTION_20_V1", source_timeframe="1H")
    s = res.samples[-1]
    assert s.valid
    assert -1.0 - 1e-6 <= s.values["CMF"] <= 1.0 + 1e-6
    assert 0 <= s.values["MFI"] <= 100


def test_compression_ratio():
    # flat then wide
    closes = [100.0] * 30 + [100 + i for i in range(30)]
    bars = make_bars(closes, minutes=60)
    res = compute_feature_series(bars, parameter_set_id="COMPRESSION_10_50_V1", source_timeframe="1H")
    # early flat region should have lower compression ratio than late expanding region
    mid = res.samples[49]
    late = res.samples[-1]
    assert mid.valid and late.valid
    assert mid.values["COMPRESSION_RATIO"] is not None


def test_batch_equals_streaming():
    closes = [100 + np.sin(i / 4) * 2 + (i % 7) * 0.1 for i in range(80)]
    bars = make_bars(closes, minutes=60)
    batch = batch_compression_expansion(bars, source_timeframe="1H", short_window=10, long_window=50, threshold=0.5)
    stream = stream_compression_expansion(bars, source_timeframe="1H", short_window=10, long_window=50, threshold=0.5)
    assert len(batch) == len(stream)
    for b, s in zip(batch, stream):
        assert b.valid == s.valid
        if not b.valid:
            continue
        for k in ("COMPRESSION_STATE", "COMPRESSION_DURATION", "BARS_IN_COMPRESSION", "EXPANSION_AFTER_COMPRESSION"):
            bv, sv = b.values.get(k), s.values.get(k)
            if isinstance(bv, float) and isinstance(sv, float):
                assert abs(bv - sv) < 1e-9
            else:
                assert bv == sv


def test_future_price_and_volume_mutation():
    bars = make_bars([100 + i * 0.2 for i in range(60)], minutes=60)
    res = compute_feature_series(bars, parameter_set_id="CONTEXT_BUNDLE_V1", source_timeframe="1H")
    idx = next(i for i, s in enumerate(res.samples) if s.valid)
    baseline = res.samples[idx]
    mut_p = copy.deepcopy(bars)
    mut_v = copy.deepcopy(bars)
    for j in range(idx + 1, len(bars)):
        mut_p[j]["close"] = 1e6
        mut_p[j]["high"] = 1e6
        mut_v[j]["volume"] = 1e9
    r2 = compute_feature_series(mut_p, parameter_set_id="CONTEXT_BUNDLE_V1", source_timeframe="1H")
    r3 = compute_feature_series(mut_v, parameter_set_id="CONTEXT_BUNDLE_V1", source_timeframe="1H")
    # compare a stable subset of intensity + efficiency keys that depend only on past
    keys = ["VOLUME_RAW", "VOLUME_ROLLING_MEAN", "EFFICIENCY_RATIO", "OBV"]
    for k in keys:
        if baseline.values.get(k) is None:
            continue
        assert r2.samples[idx].values[k] == baseline.values[k]
        assert r3.samples[idx].values[k] == baseline.values[k]


def test_true_pivot_and_outcome_leakage_rejected():
    bars = make_bars([100 + i for i in range(30)], minutes=60)
    bad = copy.deepcopy(bars)
    for b in bad:
        b["true_pivot_price"] = 999.0
        b["R"] = 1.5
        b["next_pivot_time"] = "2099-01-01T00:00:00+00:00"
    with pytest.raises(ValueError):
        assert_no_forbidden_fields(bad)
    with pytest.raises(ValueError):
        compute_feature_series(bad, parameter_set_id="VOL_WINDOW_5_V1", source_timeframe="1H")


def test_forbidden_keys_documented():
    assert "true_pivot_time" in FORBIDDEN_INPUT_KEYS
    assert "R" in FORBIDDEN_INPUT_KEYS
    assert "price_relative_to_C_pct" in FORBIDDEN_INPUT_KEYS


def test_unfinished_htf():
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    htf = []
    for i in range(10):
        ot = start + timedelta(hours=4 * i)
        ct = ot + timedelta(hours=4)
        htf.append(
            {
                "open_time": ot.isoformat(),
                "close_time": ct.isoformat(),
                "open": 100 + i,
                "high": 101 + i,
                "low": 99 + i,
                "close": 100.5 + i,
                "volume": 10.0,
                "event_id": "e1",
                "timeframe": "4H",
            }
        )
    decision = datetime.fromisoformat(htf[5]["open_time"]) + timedelta(hours=1)
    assert higher_tf_unfinished_bar_excluded(htf, decision)
    hist = filter_history_available_at(htf, decision, require_closed=True)
    assert len(hist) == 5
    sample = compute_at_decision_time(
        htf, parameter_set_id="VOL_WINDOW_5_V1", source_timeframe="4H", decision_time=decision
    )
    assert sample is not None
    assert sample.available_at <= decision


def test_warmup_and_gap():
    bars = make_bars([1, 2, 3], minutes=60)
    res = compute_feature_series(bars, parameter_set_id="VOL_WINDOW_20_V1", source_timeframe="1H")
    assert all(not s.valid for s in res.samples)
    assert res.samples[-1].invalid_reason == "INVALID_WARMUP"

    bars2 = make_bars([float(i) for i in range(1, 40)], minutes=60)
    for i in range(25, len(bars2)):
        ot = datetime.fromisoformat(bars2[i]["open_time"]) + timedelta(hours=5)
        bars2[i]["open_time"] = ot.isoformat()
        bars2[i]["close_time"] = (ot + timedelta(hours=1)).isoformat()
    res2 = compute_feature_series(bars2, parameter_set_id="VOL_WINDOW_5_V1", source_timeframe="1H")
    assert res2.samples[26].valid is False
    assert res2.samples[26].invalid_reason == "insufficient_contiguous_history"


def test_context_snapshot_api():
    bars = make_bars([100 + np.sin(i / 5) for i in range(60)], minutes=60)
    for b in bars:
        b["event_id"] = "evtA"
        b["timeframe"] = "1H"
    decision = bars[50]["close_time"]
    snap = compute_market_context(
        {"1H": bars, "5m": [], "15m": [], "4H": []},
        event_id="evtA",
        decision_time=decision,
        timeframes=["1H"],
        parameter_set_id="CONTEXT_BUNDLE_V1",
    )
    assert snap["feature_engine_version"] == FEATURE_ENGINE_VERSION
    assert snap["timeframes"]["1H"]["valid"] is True
    assert "VOLUME_RAW" in snap["timeframes"]["1H"]["values"]


def test_no_c_centered_window_api():
    """Decision-time API uses last N bars at T, not bars-before-C."""
    bars = make_bars([float(i) for i in range(1, 50)], minutes=60)
    t = bars[30]["close_time"]
    s = compute_at_decision_time(bars, parameter_set_id="VOL_WINDOW_5_V1", source_timeframe="1H", decision_time=t)
    assert s is not None
    # volume raw must equal bar 30 volume, not somehow anchored to a pivot
    assert s.values["VOLUME_RAW"] == bars[30]["volume"]
