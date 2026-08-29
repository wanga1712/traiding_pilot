"""Acceptance tests for PREDICTOR_CONFLUENCE_ENGINE_V1."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from crypto_trading_bot.research_v2.indicator_engine.tests.fixtures import make_bars
from crypto_trading_bot.research_v2.predictor_confluence.collect import assert_no_forbidden_bars
from crypto_trading_bot.research_v2.predictor_confluence.engine import compute_predictor_confluence
from crypto_trading_bot.research_v2.predictor_confluence.version import CONFLUENCE_ENGINE_VERSION, FORBIDDEN_INPUT_KEYS
from crypto_trading_bot.research_v2.reversal_events.anti_leakage import (
    filter_history_available_at,
    higher_tf_unfinished_bar_excluded,
)


def _bars(n=90, minutes=60):
    closes = [100 + np.sin(i / 6) * 2 + i * 0.04 for i in range(n)]
    return make_bars(closes, minutes=minutes)


def test_raw_and_family_normalized():
    bars = _bars()
    decision = bars[-2]["close_time"]
    snap = compute_predictor_confluence(
        {"1H": bars},
        decision_time=decision,
        timeframes=["1H"],
        confluence_parameter_set="CONF_PCT_025_ATR_050_V1",
    )
    assert snap["confluence_engine_version"] == CONFLUENCE_ENGINE_VERSION
    raw = snap["within_tf"]["RAW"]["1H"]
    fam = snap["within_tf"]["FAMILY_NORMALIZED"]["1H"]
    assert raw is not None and fam is not None
    assert raw["features"]["VALID_TRIGGER_COUNT"] >= fam["features"]["VALID_TRIGGER_COUNT"]
    assert "NEAREST_CLUSTER_SIZE" in raw["features"]
    assert "COUNT_WITHIN_0_25_PCT" in raw["features"]
    assert "TRIGGER_DISPERSION_PCT" in raw["features"]


def test_cross_tf_confluence():
    b1h = _bars(90, minutes=60)
    b15 = _bars(90, minutes=15)
    decision = b1h[-5]["close_time"]
    snap = compute_predictor_confluence(
        {"1H": b1h, "15m": b15},
        decision_time=decision,
        timeframes=["15m", "1H"],
    )
    cross = snap["cross_tf"]["RAW"]
    assert cross["CROSS_TF_VALID_TRIGGER_COUNT"] >= 0
    assert "CROSS_TF_NEAREST_CLUSTER_TF_DIVERSITY" in cross


def test_temporal_fields_present():
    bars = _bars(100)
    decision = bars[-2]["close_time"]
    snap = compute_predictor_confluence({"1H": bars}, decision_time=decision, timeframes=["1H"])
    feats = snap["within_tf"]["RAW"]["1H"]["features"]
    assert "APPROACHING_TRIGGER_COUNT" in feats
    assert "TRIGGER_DISPERSION_DELTA" in feats


def test_future_mutation():
    bars = _bars(80)
    idx = 60
    decision = bars[idx]["close_time"]
    base = compute_predictor_confluence({"1H": bars}, decision_time=decision, timeframes=["1H"])
    mut = copy.deepcopy(bars)
    for j in range(idx + 1, len(mut)):
        mut[j]["close"] = 1e9
        mut[j]["high"] = 1e9
    again = compute_predictor_confluence({"1H": mut}, decision_time=decision, timeframes=["1H"])
    assert (
        again["within_tf"]["RAW"]["1H"]["features"]["VALID_TRIGGER_COUNT"]
        == base["within_tf"]["RAW"]["1H"]["features"]["VALID_TRIGGER_COUNT"]
    )
    assert (
        again["within_tf"]["RAW"]["1H"]["features"]["NEAREST_TRIGGER_PRICE"]
        == base["within_tf"]["RAW"]["1H"]["features"]["NEAREST_TRIGGER_PRICE"]
    )


def test_true_c_outcome_leakage():
    bars = _bars(40)
    bad = copy.deepcopy(bars)
    for b in bad:
        b["true_pivot_price"] = 1.0
        b["R"] = 2.0
    with pytest.raises(ValueError):
        assert_no_forbidden_bars(bad)
    with pytest.raises(ValueError):
        compute_predictor_confluence({"1H": bad}, decision_time=bad[-1]["close_time"], timeframes=["1H"])
    assert "true_pivot_time" in FORBIDDEN_INPUT_KEYS
    assert "R" in FORBIDDEN_INPUT_KEYS


def test_unfinished_htf():
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    htf = []
    for i in range(50):
        ot = start + timedelta(hours=4 * i)
        ct = ot + timedelta(hours=4)
        htf.append(
            {
                "open_time": ot.isoformat(),
                "close_time": ct.isoformat(),
                "open": 100 + i * 0.5,
                "high": 101 + i * 0.5,
                "low": 99 + i * 0.5,
                "close": 100.2 + i * 0.5,
                "volume": 1.0,
            }
        )
    decision = datetime.fromisoformat(htf[30]["open_time"]) + timedelta(hours=1)
    assert higher_tf_unfinished_bar_excluded(htf, decision)
    hist = filter_history_available_at(htf, decision, require_closed=True)
    assert len(hist) == 30
    snap = compute_predictor_confluence({"4H": htf}, decision_time=decision, timeframes=["4H"])
    avail = datetime.fromisoformat(snap["within_tf"]["RAW"]["4H"]["available_at"])
    assert avail <= decision


def test_batch_streaming():
    bars = _bars(70)
    idx = 55
    decision = bars[idx]["close_time"]
    full = compute_predictor_confluence({"1H": bars}, decision_time=decision, timeframes=["1H"])
    prefix = compute_predictor_confluence({"1H": bars[: idx + 1]}, decision_time=decision, timeframes=["1H"])
    a = full["within_tf"]["RAW"]["1H"]["features"]
    b = prefix["within_tf"]["RAW"]["1H"]["features"]
    assert a["VALID_TRIGGER_COUNT"] == b["VALID_TRIGGER_COUNT"]
    assert a["NEAREST_TRIGGER_PRICE"] == b["NEAREST_TRIGGER_PRICE"]
    assert a.get("APPROACHING_TRIGGER_COUNT") == b.get("APPROACHING_TRIGGER_COUNT")
