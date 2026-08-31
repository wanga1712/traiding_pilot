"""Tests for MULTITF_INDICATOR_FEATURE_BANK_V1."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from crypto_trading_bot.research_v2.indicator_engine.math_core import ema, sma, wma
from crypto_trading_bot.research_v2.indicator_engine.tests.fixtures import make_bars, make_ohlc_bars
from crypto_trading_bot.research_v2.multitf_feature_bank.displacement import (
    build_display_aligned_series,
    display_aligned_at_index,
)
from crypto_trading_bot.research_v2.multitf_feature_bank.geometry import ABCGeometry, compute_geometry_features
from crypto_trading_bot.research_v2.multitf_feature_bank.ma_features import compute_dma_feature_series
from crypto_trading_bot.research_v2.multitf_feature_bank.registries import DMA_REGISTRY, MACD_REGISTRY, STOCHASTIC_REGISTRY
from crypto_trading_bot.research_v2.multitf_feature_bank.snapshot import FeatureBank
from crypto_trading_bot.research_v2.multitf_feature_bank.streaming import StreamingFeatureBank
from crypto_trading_bot.research_v2.indicator_engine.bars import bars_to_arrays
from crypto_trading_bot.research_v2.indicator_engine.types import IndicatorSample


def _samples_from_values(vals: list[float], shift: int = 0) -> list[IndicatorSample]:
    t0 = datetime(2022, 1, 1, tzinfo=timezone.utc)
    out = []
    for i, v in enumerate(vals):
        ct = t0 + timedelta(hours=i)
        ot = ct - timedelta(minutes=30)
        out.append(
            IndicatorSample(
                calculated_at=ct,
                available_at=ct,
                displayed_at=ot + timedelta(hours=shift) if shift else ct,
                values={"ma": v},
                valid=True,
            )
        )
    return out


@pytest.mark.parametrize("shift", [0, 1, 3, 5])
def test_displacement_alignment_synthetic(shift: int):
    vals = [float(i) for i in range(20)]
    samples = _samples_from_values(vals, shift=0)
    t = 10
    expected = vals[t - shift] if t >= shift else None
    got, _, _ = display_aligned_at_index(samples, t, shift, value_key="ma")
    assert got == expected


def test_displacement_does_not_change_available_at():
    bars = make_bars([100 + i for i in range(30)], minutes=60)
    arrays = bars_to_arrays(bars, timeframe="1H")
    series = compute_dma_feature_series(arrays, ma_type="SMA", period=3, display_shift=3)
    idx = 10
    assert series[idx].available_at == arrays.close_time[idx]
    assert series[idx].available_at != series[idx].displayed_at or series[idx].displayed_at is None


def test_geometry_bullish_abc():
    g = ABCGeometry(100, 200, 150)
    assert abs(g.cop() - 211.8) < 1e-9
    assert abs(g.op() - 250.0) < 1e-9
    assert abs(g.xop() - 311.8) < 1e-9


def test_geometry_bearish_abc():
    g = ABCGeometry(200, 100, 150)
    assert abs(g.cop() - 88.2) < 1e-9
    assert abs(g.op() - 50.0) < 1e-9
    assert abs(g.xop() - (-11.8)) < 1e-9


def test_ma_reference_sma_ema_wma():
    x = np.array([1.0, 2, 3, 4, 5, 6, 7, 8], dtype=float)
    assert abs(float(sma(x, 3)[2]) - 2.0) < 1e-12
    assert abs(float(ema(x, 3)[2]) - 2.0) < 1e-12
    assert abs(float(wma(x, 3)[2]) - 2.333333333) < 1e-6


def test_future_price_mutation_unchanged():
    bars = make_bars([100 + np.sin(i / 4) * 2 + i * 0.05 for i in range(50)], minutes=60)
    arrays = bars_to_arrays(bars, timeframe="1H")
    base = compute_dma_feature_series(arrays, ma_type="SMA", period=3, display_shift=3)
    idx = 20
    mutated = copy.deepcopy(bars)
    for j in range(idx + 1, len(mutated)):
        mutated[j]["close"] = 9999.0
    arrays2 = bars_to_arrays(mutated, timeframe="1H")
    mut = compute_dma_feature_series(arrays2, ma_type="SMA", period=3, display_shift=3)
    assert base[idx].values["ma"] == mut[idx].values["ma"]


def test_batch_streaming_parity():
    bars = make_bars([100 + i * 0.1 for i in range(40)], minutes=60)
    bank = FeatureBank({"1H": bars})
    t = datetime.fromisoformat(bars[-1]["close_time"].replace("Z", "+00:00"))
    batch = bank.snapshot(t)
    stream = StreamingFeatureBank(FeatureBank({"1H": []}))
    snap = None
    for b in bars:
        snap = stream.on_bar_closed("1H", b)
    assert snap is not None
    overlap = set(batch.features) & set(snap.features)
    for k in list(overlap)[:5]:
        assert batch.features[k] == snap.features[k]


def test_registry_counts():
    assert len(DMA_REGISTRY) >= 14 * 3  # curated * 3 MA types
    assert len(STOCHASTIC_REGISTRY) == 4 * 4
    assert len(MACD_REGISTRY) == 3 * 4
