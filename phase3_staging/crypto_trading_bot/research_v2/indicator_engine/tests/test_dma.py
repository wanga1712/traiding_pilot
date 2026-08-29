"""DMA numeric + displacement anti-leakage tests."""
from __future__ import annotations

import copy

from crypto_trading_bot.research_v2.indicator_engine.engine import compute_series
from crypto_trading_bot.research_v2.indicator_engine.tests.fixtures import make_bars


def test_dma_3x3_numeric_and_semantics():
    # closes 1..10 → at index 2 (value 3): SMA(1,2,3)=2
    bars = make_bars([float(i) for i in range(1, 11)], minutes=60)
    res = compute_series(bars, parameter_set_id="DMA_3X3_V1", source_timeframe="1H", use_cache=False)
    s = res.samples[2]
    assert s.valid
    assert abs(s.values["dma"] - 2.0) < 1e-12
    assert s.calculated_at.isoformat() == bars[2]["close_time"]
    assert s.available_at == s.calculated_at
    # DISPLAYED_AT = open of bar index 2+3=5
    assert s.displayed_at.isoformat() == bars[5]["open_time"]
    assert s.displayed_at != s.available_at


def test_dma_7x5_and_25x5_warmup_and_shift():
    bars = make_bars([float(i) for i in range(1, 40)], minutes=60)
    r7 = compute_series(bars, parameter_set_id="DMA_7X5_V1", source_timeframe="1H", use_cache=False)
    assert not r7.samples[5].valid  # warmup
    s7 = r7.samples[6]
    assert s7.valid
    expected = sum(range(1, 8)) / 7.0
    assert abs(s7.values["dma"] - expected) < 1e-12
    assert s7.displayed_at.isoformat() == bars[6 + 5]["open_time"]

    r25 = compute_series(bars, parameter_set_id="DMA_25X5_V1", source_timeframe="1H", use_cache=False)
    assert not r25.samples[23].valid
    s25 = r25.samples[24]
    assert s25.valid
    expected25 = sum(range(1, 26)) / 25.0
    assert abs(s25.values["dma"] - expected25) < 1e-12
    assert s25.displayed_at.isoformat() == bars[24 + 5]["open_time"]


def test_dma_anti_leakage_future_mutation():
    bars = make_bars([float(i) for i in range(1, 20)], minutes=60)
    res = compute_series(bars, parameter_set_id="DMA_3X3_V1", source_timeframe="1H", use_cache=False)
    baseline = res.samples[2]
    mutated = copy.deepcopy(bars)
    # mutate bars after available_at (index > 2)
    for j in range(3, len(mutated)):
        mutated[j]["close"] = 999999.0
        mutated[j]["high"] = 999999.0
    res2 = compute_series(mutated, parameter_set_id="DMA_3X3_V1", source_timeframe="1H", use_cache=False)
    s2 = res2.samples[2]
    assert s2.values["dma"] == baseline.values["dma"]
    assert s2.available_at == baseline.available_at
    # displayed_at still references later open_time coordinate only
    assert s2.displayed_at == baseline.displayed_at
