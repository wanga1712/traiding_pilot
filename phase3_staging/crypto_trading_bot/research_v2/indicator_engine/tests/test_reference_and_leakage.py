"""Stochastic / MACD / RSI / ATR / Bollinger reference + anti-leakage."""
from __future__ import annotations

import copy

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.engine import compute_series
from crypto_trading_bot.research_v2.indicator_engine.math_core import ema, rma, sma, true_range
from crypto_trading_bot.research_v2.indicator_engine.tests.fixtures import make_bars, make_ohlc_bars
from crypto_trading_bot.research_v2.indicator_engine.bars import bars_to_arrays


def test_stochastic_correctness_manual():
    # Construct simple range so raw stoch is known
    rows = []
    for i in range(20):
        c = 10.0 + i
        rows.append((c - 1, c + 1, c - 2, c))
    bars = make_ohlc_bars(rows, minutes=60)
    res = compute_series(bars, parameter_set_id="STOCH_14_3_3_V1", source_timeframe="1H", use_cache=False)
    # First potentially valid after warmup k+ks+d-3 = 14+3+3-3=17 → index 17
    s = res.samples[17]
    assert s.valid
    assert 0 <= s.values["k"] <= 100
    assert 0 <= s.values["d"] <= 100


def test_displaced_stochastic_anti_leakage():
    bars = make_bars([10 + 0.5 * np.sin(i / 3) + i * 0.01 for i in range(60)], minutes=60)
    res = compute_series(
        bars, parameter_set_id="DISPLACED_STOCH_14_3_3_SHIFT3_V1", source_timeframe="1H", use_cache=False
    )
    idx = next(i for i, s in enumerate(res.samples) if s.valid)
    baseline = res.samples[idx]
    mutated = copy.deepcopy(bars)
    for j in range(idx + 1, len(mutated)):
        mutated[j]["close"] = 1e9
        mutated[j]["high"] = 1e9
    res2 = compute_series(
        mutated, parameter_set_id="DISPLACED_STOCH_14_3_3_SHIFT3_V1", source_timeframe="1H", use_cache=False
    )
    assert res2.samples[idx].values == baseline.values
    assert res2.samples[idx].available_at == baseline.available_at
    assert baseline.displayed_at is not None
    assert baseline.displayed_at != baseline.available_at


def test_macd_correctness_vs_manual_ema():
    closes = [float(100 + i + (i % 5)) for i in range(80)]
    bars = make_bars(closes, minutes=60)
    arrays = bars_to_arrays(bars, timeframe="1H")
    fast = ema(arrays.close, 12)
    slow = ema(arrays.close, 26)
    macd_line = fast - slow
    res = compute_series(bars, parameter_set_id="MACD_12_26_9_V1", source_timeframe="1H", use_cache=False)
    # compare at last index where both valid
    i = 40
    assert res.samples[i].valid
    assert abs(res.samples[i].values["macd"] - float(macd_line[i])) < 1e-9


def test_displaced_macd_anti_leakage():
    bars = make_bars([100 + np.sin(i / 5) * 3 + i * 0.1 for i in range(80)], minutes=60)
    res = compute_series(
        bars, parameter_set_id="DISPLACED_MACD_12_26_9_SHIFT3_V1", source_timeframe="1H", use_cache=False
    )
    idx = next(i for i, s in enumerate(res.samples) if s.valid)
    baseline = res.samples[idx]
    mutated = copy.deepcopy(bars)
    for j in range(idx + 1, len(mutated)):
        mutated[j]["close"] *= 10
    res2 = compute_series(
        mutated, parameter_set_id="DISPLACED_MACD_12_26_9_SHIFT3_V1", source_timeframe="1H", use_cache=False
    )
    assert abs(res2.samples[idx].values["macd"] - baseline.values["macd"]) < 1e-12
    assert res2.samples[idx].available_at == baseline.available_at


def test_rsi_warmup_and_bounds():
    bars = make_bars([100 + i for i in range(40)], minutes=60)
    res = compute_series(bars, parameter_set_id="RSI_14_V1", source_timeframe="1H", use_cache=False)
    assert not res.samples[13].valid
    assert res.samples[14].valid
    # strictly rising → RSI near 100
    assert res.samples[-1].values["rsi"] > 70


def test_atr_vs_manual_wilder():
    rows = [(10, 12, 9, 11), (11, 13, 10, 12), (12, 14, 11, 13), (13, 15, 12, 14), (14, 16, 13, 15)]
    # extend
    for i in range(20):
        c = 15 + i
        rows.append((c - 1, c + 1, c - 2, c))
    bars = make_ohlc_bars(rows, minutes=60)
    arrays = bars_to_arrays(bars, timeframe="1H")
    tr = true_range(arrays.high, arrays.low, arrays.close)
    atr_m = rma(tr, 14)
    res = compute_series(bars, parameter_set_id="ATR_14_V1", source_timeframe="1H", use_cache=False)
    i = 20
    assert res.samples[i].valid
    assert abs(res.samples[i].values["atr"] - float(atr_m[i])) < 1e-12


def test_bollinger_mid_is_sma():
    closes = [float(50 + (i % 7) - 3) for i in range(40)]
    bars = make_bars(closes, minutes=60)
    arrays = bars_to_arrays(bars, timeframe="1H")
    mid = sma(arrays.close, 20)
    res = compute_series(bars, parameter_set_id="BOLLINGER_20_2_V1", source_timeframe="1H", use_cache=False)
    i = 25
    assert res.samples[i].valid
    assert abs(res.samples[i].values["mid"] - float(mid[i])) < 1e-12
    assert res.samples[i].values["upper"] > res.samples[i].values["mid"]
    assert res.samples[i].values["lower"] < res.samples[i].values["mid"]
