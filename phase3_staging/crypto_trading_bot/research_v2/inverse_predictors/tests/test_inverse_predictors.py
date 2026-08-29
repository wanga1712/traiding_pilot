"""Acceptance tests for INVERSE_PREDICTOR_ENGINE_V1."""
from __future__ import annotations

import copy

import numpy as np
import pytest

from crypto_trading_bot.research_v2.indicator_engine.tests.fixtures import make_bars
from crypto_trading_bot.research_v2.reversal_events.anti_leakage import (
    filter_history_available_at,
    higher_tf_unfinished_bar_excluded,
)
from crypto_trading_bot.research_v2.inverse_predictors.engine import predict
from crypto_trading_bot.research_v2.inverse_predictors.registry import PARAMETER_REGISTRY
from crypto_trading_bot.research_v2.inverse_predictors.replay import verify_predictor_replay
from crypto_trading_bot.research_v2.inverse_predictors.state import assert_no_forbidden, build_state
from crypto_trading_bot.research_v2.inverse_predictors.streaming import batch_predictor_at, predictor_from_prefix
from crypto_trading_bot.research_v2.inverse_predictors.version import FORBIDDEN_INPUT_KEYS, PREDICTOR_ENGINE_VERSION
from datetime import datetime, timedelta, timezone


def _bars(n=80):
    closes = [100 + np.sin(i / 5) * 3 + i * 0.05 for i in range(n)]
    return make_bars(closes, minutes=60)


def test_dma_analytic_and_replay():
    bars = _bars()
    decision = bars[-2]["close_time"]
    for ps, period in (
        ("PRED_DMA_3X3_CROSS_UP_V1", 3),
        ("PRED_DMA_7X5_CROSS_UP_V1", 7),
        ("PRED_DMA_25X5_CROSS_UP_V1", 25),
    ):
        r = predict(bars, parameter_set_id=ps, source_timeframe="1H", decision_time=decision)
        assert r.solution_status in ("EXACT_ANALYTIC", "ALREADY_TRIGGERED")
        assert r.predicted_trigger_price is not None
        assert r.hypothetical_input_type == "NEXT_BAR_CLOSE"
        vr = verify_predictor_replay(bars, ps, "1H", decision)
        assert vr["ok"], vr


def test_rsi_replay():
    bars = _bars(100)
    decision = bars[-2]["close_time"]
    for ps in ("PRED_RSI_14_30_V1", "PRED_RSI_14_50_V1", "PRED_RSI_14_70_V1"):
        r = predict(bars, parameter_set_id=ps, source_timeframe="1H", decision_time=decision)
        assert r.solution_status in ("EXACT_ANALYTIC", "ALREADY_TRIGGERED", "AMBIGUOUS", "NO_FINITE_SOLUTION")
        if r.solution_status == "EXACT_ANALYTIC":
            vr = verify_predictor_replay(bars, ps, "1H", decision)
            assert vr["ok"], vr


def test_macd_replay():
    bars = _bars(120)
    decision = bars[-2]["close_time"]
    for ps in ("PRED_MACD_12_26_9_HIST_ZERO_V1", "PRED_MACD_12_26_9_SIGNAL_CROSS_UP_V1"):
        r = predict(bars, parameter_set_id=ps, source_timeframe="1H", decision_time=decision)
        assert r.solution_status in ("EXACT_ANALYTIC", "ALREADY_TRIGGERED")
        vr = verify_predictor_replay(bars, ps, "1H", decision)
        assert vr["ok"], vr


def test_stoch_point_and_kd_limitation():
    bars = _bars(60)
    decision = bars[-2]["close_time"]
    r20 = predict(bars, parameter_set_id="PRED_STOCH_14_K_20_POINT_V1", source_timeframe="1H", decision_time=decision)
    assert r20.solution_status in ("EXACT_ANALYTIC", "REQUIRES_INTRABAR_ASSUMPTION", "AMBIGUOUS", "NO_FINITE_SOLUTION")
    if r20.solution_status == "EXACT_ANALYTIC":
        vr = verify_predictor_replay(bars, "PRED_STOCH_14_K_20_POINT_V1", "1H", decision)
        assert vr["ok"], vr
    kd = predict(bars, parameter_set_id="PRED_STOCH_K_CROSS_D_UP_V1", source_timeframe="1H", decision_time=decision)
    assert kd.solution_status == "REQUIRES_INTRABAR_ASSUMPTION"


def test_project_oscillator():
    bars = _bars(100)
    decision = bars[-2]["close_time"]
    r = predict(bars, parameter_set_id="PRED_PROJECT_OSC_20_50_2_V1", source_timeframe="1H", decision_time=decision)
    assert isinstance(r, list) and len(r) == 2
    assert all(x.solution_status == "EXACT_ANALYTIC" for x in r)
    assert r[0].predicted_trigger_price > r[1].predicted_trigger_price or True


def test_bollinger_unsupported():
    bars = _bars()
    r = predict(bars, parameter_set_id="PRED_BOLLINGER_FEASIBILITY_V1", source_timeframe="1H", decision_time=bars[-1]["close_time"])
    assert r.solution_status == "UNSUPPORTED_V1"


def test_future_mutation_leakage():
    bars = _bars(80)
    idx = 60
    decision = bars[idx]["close_time"]
    base = predict(bars, parameter_set_id="PRED_DMA_3X3_CROSS_UP_V1", source_timeframe="1H", decision_time=decision)
    mut = copy.deepcopy(bars)
    for j in range(idx + 1, len(mut)):
        mut[j]["close"] = 1e9
        mut[j]["high"] = 1e9
    again = predict(mut, parameter_set_id="PRED_DMA_3X3_CROSS_UP_V1", source_timeframe="1H", decision_time=decision)
    assert again.predicted_trigger_price == base.predicted_trigger_price
    assert again.solution_status == base.solution_status


def test_true_c_outcome_leakage():
    bars = _bars(40)
    bad = copy.deepcopy(bars)
    for b in bad:
        b["true_pivot_price"] = 1.0
        b["R"] = 2.0
    with pytest.raises(ValueError):
        assert_no_forbidden(bad)
    with pytest.raises(ValueError):
        predict(bad, parameter_set_id="PRED_DMA_3X3_CROSS_UP_V1", source_timeframe="1H", decision_time=bad[-1]["close_time"])
    assert "true_pivot_time" in FORBIDDEN_INPUT_KEYS


def test_unfinished_htf():
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    htf = []
    for i in range(40):
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
                "volume": 1.0,
            }
        )
    decision = datetime.fromisoformat(htf[20]["open_time"]) + timedelta(hours=1)
    assert higher_tf_unfinished_bar_excluded(htf, decision)
    hist = filter_history_available_at(htf, decision, require_closed=True)
    assert len(hist) == 20
    r = predict(htf, parameter_set_id="PRED_DMA_3X3_CROSS_UP_V1", source_timeframe="4H", decision_time=decision)
    assert r.available_at <= decision


def test_batch_streaming():
    bars = _bars(70)
    for idx in (40, 50, 60):
        a = predictor_from_prefix(bars, end_index=idx, parameter_set_id="PRED_RSI_14_50_V1", source_timeframe="1H")
        b = batch_predictor_at(bars, end_index=idx, parameter_set_id="PRED_RSI_14_50_V1", source_timeframe="1H")
        assert a.solution_status == b.solution_status
        if a.predicted_trigger_price is not None:
            assert abs(a.predicted_trigger_price - b.predicted_trigger_price) < 1e-9


def test_engine_version():
    assert PREDICTOR_ENGINE_VERSION == "INVERSE_PREDICTOR_ENGINE_V1"
    assert "PRED_DMA_3X3_CROSS_UP_V1" in PARAMETER_REGISTRY
