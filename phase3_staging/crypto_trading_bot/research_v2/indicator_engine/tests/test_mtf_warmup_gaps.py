"""Higher-TF closed-bar, warmup, gap, reproducibility tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from crypto_trading_bot.research_v2.indicator_engine.engine import compute_indicator, compute_series
from crypto_trading_bot.research_v2.indicator_engine.tests.fixtures import make_bars
from crypto_trading_bot.research_v2.reversal_events.anti_leakage import (
    filter_history_available_at,
    higher_tf_unfinished_bar_excluded,
)


def test_higher_tf_closed_bar_availability():
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    # 4H bars
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
                "volume": 1.0,
            }
        )
    # decision in the middle of bar index 5 (open<=T<close)
    decision = datetime.fromisoformat(htf[5]["open_time"]) + timedelta(hours=1)
    assert higher_tf_unfinished_bar_excluded(htf, decision)
    hist = filter_history_available_at(htf, decision, require_closed=True)
    assert all(datetime.fromisoformat(b["close_time"]) <= decision for b in hist)
    assert len(hist) == 5  # bars 0..4 closed
    sample = compute_indicator(
        htf,
        parameter_set_id="SMA_5_V1",
        source_timeframe="4H",
        decision_time=decision,
    )
    assert sample is not None
    assert sample.available_at <= decision


def test_warmup_null_not_zero():
    bars = make_bars([1.0, 2.0, 3.0], minutes=60)
    res = compute_series(bars, parameter_set_id="DMA_25X5_V1", source_timeframe="1H", use_cache=False)
    for s in res.samples:
        assert not s.valid
        assert s.values["dma"] is None
        assert s.invalid_reason == "warmup"


def test_gap_marks_invalid():
    bars = make_bars([float(i) for i in range(1, 15)], minutes=60)
    # insert gap by shifting later bars by +2h beyond expected
    for i in range(8, len(bars)):
        ot = datetime.fromisoformat(bars[i]["open_time"]) + timedelta(hours=5)
        ct = ot + timedelta(hours=1)
        bars[i]["open_time"] = ot.isoformat()
        bars[i]["close_time"] = ct.isoformat()
    res = compute_series(bars, parameter_set_id="DMA_3X3_V1", source_timeframe="1H", use_cache=False)
    # sample that needs bars crossing the gap should be invalid
    assert res.samples[9].valid is False
    assert res.samples[9].invalid_reason == "insufficient_contiguous_history"


def test_reproducibility():
    bars = make_bars([100 + (i % 9) * 0.3 for i in range(50)], minutes=60)
    a = compute_series(bars, parameter_set_id="RSI_14_V1", source_timeframe="1H", use_cache=False)
    b = compute_series(bars, parameter_set_id="RSI_14_V1", source_timeframe="1H", use_cache=False)
    assert [s.values for s in a.samples] == [s.values for s in b.samples]
    assert a.indicator_engine_version == "INDICATOR_ENGINE_V1"
