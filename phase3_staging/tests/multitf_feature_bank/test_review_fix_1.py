"""Independent review fix-1 regression tests."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.bars import bars_to_arrays
from crypto_trading_bot.research_v2.indicator_engine.tests.fixtures import make_bars
from crypto_trading_bot.research_v2.multitf_feature_bank.aligned_features import provenance_at
from crypto_trading_bot.research_v2.multitf_feature_bank.geometry import ABCGeometry, compute_geometry_features
from crypto_trading_bot.research_v2.multitf_feature_bank.geometry_stage import stage_from_normalized_r
from crypto_trading_bot.research_v2.multitf_feature_bank.ma_features import compute_dma_feature_series
from crypto_trading_bot.research_v2.multitf_feature_bank.macd_features import compute_macd_feature_series
from crypto_trading_bot.research_v2.multitf_feature_bank.pivots import PivotRecord
from crypto_trading_bot.research_v2.multitf_feature_bank.registries import (
    DMA_REGISTRY,
    FEATURE_OUTPUTS,
    MACD_REGISTRY,
    STOCHASTIC_REGISTRY,
)
from crypto_trading_bot.research_v2.multitf_feature_bank.snapshot import FeatureBank
from crypto_trading_bot.research_v2.multitf_feature_bank.stoch_features import compute_stoch_feature_series
from crypto_trading_bot.research_v2.multitf_feature_bank.streaming import StreamingFeatureBank

FLOAT_TOL = 1e-9


def test_bearish_geometry_stage_normalized_r():
    g = ABCGeometry(200, 100, 150)
    cases = [
        (0.0, "PRE_COP"),
        (0.617, "PRE_COP"),
        (0.618, "COP_TO_OP"),
        (0.999, "COP_TO_OP"),
        (1.0, "OP_TO_XOP"),
        (1.617, "OP_TO_XOP"),
        (1.618, "POST_XOP"),
        (2.0, "POST_XOP"),
    ]
    for r, expected in cases:
        price = g.c_price + g.ab_length * r
        assert stage_from_normalized_r(r) == expected
        assert compute_geometry_features(
            a_price=200, b_price=100, c_price=150, current_price=price
        )["GEOMETRY_STAGE"] == expected


def test_bullish_geometry_stage_same_thresholds():
    g = ABCGeometry(100, 200, 150)
    for r, expected in [(0.0, "PRE_COP"), (0.618, "COP_TO_OP"), (1.0, "OP_TO_XOP"), (1.618, "POST_XOP")]:
        price = g.c_price + g.ab_length * r
        assert compute_geometry_features(a_price=100, b_price=200, c_price=150, current_price=price)["GEOMETRY_STAGE"] == expected


def test_macd_histogram_contract():
    bars = make_bars([100 + np.sin(i / 4) * 5 + i * 0.2 for i in range(120)], minutes=60)
    arrays = bars_to_arrays(bars, timeframe="1H")
    series = compute_macd_feature_series(arrays, fast=12, slow=26, signal=9, display_shift=0)
    idx = 80
    prim = series[idx].signal_primitives
    assert series[idx].values.get("histogram") is not None
    assert prim.get("HIST") == series[idx].values["histogram"]
    assert prim.get("MACD_MINUS_SIGNAL") is not None
    assert prim.get("SIGNAL_SLOPE") is not None


def test_displacement_provenance():
    bars = make_bars([100 + i for i in range(40)], minutes=60)
    arrays = bars_to_arrays(bars, timeframe="1H")
    series = compute_dma_feature_series(arrays, ma_type="SMA", period=3, display_shift=3, atr=None)
    idx = 20
    prov = provenance_at(series, idx, 3)
    src_i = idx - 3
    assert prov["DECISION_TIME"] == series[idx].available_at.isoformat()
    assert prov["SOURCE_TIME"] == series[src_i].calculated_at.isoformat()
    assert prov["CALCULATED_AT"] == series[src_i].calculated_at.isoformat()
    assert prov["AVAILABLE_AT"] == series[src_i].available_at.isoformat()
    assert prov["CALCULATED_AT"] != prov["DECISION_TIME"] or src_i == idx


def test_registry_output_parity():
    bars = make_bars([100 + np.sin(i / 6) * 4 + i * 0.15 for i in range(200)], minutes=60)
    dma_id = "DMA_SMA_P3_SHIFT3_V1"
    stoch_id = "DISPLACED_STOCH_K14_KS3_D3_SHIFT3_V1"
    macd_id = "DISPLACED_MACD_12_26_9_SHIFT3_V1"
    t0 = datetime.fromisoformat(bars[0]["open_time"].replace("Z", "+00:00"))
    pivots = [
        PivotRecord("P0", 100, t0 + timedelta(hours=24), timeframe="1H"),
        PivotRecord("P1", 120, t0 + timedelta(hours=48), timeframe="1H"),
        PivotRecord("P2", 110, t0 + timedelta(hours=72), timeframe="1H"),
        PivotRecord("P3", 115, t0 + timedelta(hours=96), timeframe="1H"),
    ]
    bank = FeatureBank({"1H": bars}, pivots_by_tf={"1H": pivots})
    t = datetime.fromisoformat(bars[150]["close_time"].replace("Z", "+00:00"))
    snap = bank.snapshot(t)
    for ps_id, family in ((dma_id, "DMA"), (stoch_id, "STOCHASTIC"), (macd_id, "MACD")):
        for feat in FEATURE_OUTPUTS[family]:
            key = f"1H.{ps_id}.{feat}"
            assert key in snap.features, f"missing {key}"
    for feat in FEATURE_OUTPUTS["GEOMETRY"]:
        assert f"1H.GEOMETRY_ABC.{feat}" in snap.features


def test_geometry_atr_and_leg_ratio():
    geo = compute_geometry_features(
        a_price=100,
        b_price=200,
        c_price=150,
        current_price=160,
        atr=10.0,
    )
    assert geo["AB_LENGTH_ATR"] == 10.0
    assert geo["DIST_TO_COP_ATR"] is not None
    assert geo["REFERENCE_AB_LENGTH"] == 100.0
    assert abs(geo["CURRENT_VS_REFERENCE_AB_RATIO"] - 0.1) < FLOAT_TOL


def test_full_batch_streaming_parity():
    bars = make_bars([100 + np.sin(i / 5) * 3 + i * 0.1 for i in range(80)], minutes=60)
    bank = FeatureBank({"1H": bars})
    stream = StreamingFeatureBank(FeatureBank({"1H": []}))
    checkpoints = [30, 50, 70, 79]
    for i, b in enumerate(bars):
        stream_snap = stream.on_bar_closed("1H", b)
        if i in checkpoints:
            t = datetime.fromisoformat(b["close_time"].replace("Z", "+00:00"))
            batch_snap = bank.snapshot(t)
            assert set(batch_snap.features.keys()) == set(stream_snap.features.keys())
            for k, bv in batch_snap.features.items():
                sv = stream_snap.features[k]
                if isinstance(bv, float) and isinstance(sv, float):
                    assert abs(bv - sv) <= FLOAT_TOL, k
                else:
                    assert bv == sv, k


def _first_true_bar(series, key: str) -> int | None:
    for i, s in enumerate(series):
        if s.valid and s.signal_primitives.get(key):
            return i
    return None


def test_dma_shifted_signal_timing():
    # Synthetic dip/recovery: source-aligned cross at bar 23, display-aligned at bar 25.
    closes = (
        [100.0] * 20
        + [
            99.44049,
            96.686332,
            93.785497,
            95.665119,
            98.141652,
            98.781467,
            100.158446,
            100.420196,
            103.030631,
            104.925752,
            101.942183,
            104.086609,
            101.288122,
            102.666055,
            100.719989,
            102.899062,
            103.147829,
            101.946101,
            101.482224,
            98.652142,
            96.397842,
            97.421588,
            98.304725,
            98.997036,
            98.299101,
            101.282361,
            104.167373,
            105.280625,
            106.183381,
            107.314061,
            106.64759,
            104.458169,
            105.787099,
            105.939225,
            104.800676,
            104.715688,
            107.052615,
            109.656876,
            108.803647,
        ]
    )
    bars = make_bars(closes, minutes=60)
    arrays = bars_to_arrays(bars, timeframe="1H")
    series = compute_dma_feature_series(arrays, ma_type="SMA", period=3, display_shift=3, atr=None)
    src_bar = _first_true_bar(series, "PRICE_CROSS_UP_MA")
    da_bar = _first_true_bar(series, "DISPLAY_ALIGNED_PRICE_CROSS_UP_MA")
    assert src_bar is not None and da_bar is not None, "expected both cross types"
    assert src_bar != da_bar, f"crosses on same bar {src_bar}"
    assert src_bar == 23 and da_bar == 25
    found_split = any(
        s.valid
        and s.signal_primitives.get("DISPLAY_ALIGNED_PRICE_CROSS_UP_MA")
        != s.signal_primitives.get("PRICE_CROSS_UP_MA")
        for s in series
    )
    assert found_split


def test_stoch_shifted_signal_timing():
    for spike_at in range(20, 50):
        closes = [55.0] * spike_at + [5.0, 95.0, 95.0, 95.0] + [60.0] * 40
        bars = make_bars(closes, minutes=60)
        arrays = bars_to_arrays(bars, timeframe="1H")
        series = compute_stoch_feature_series(arrays, k_period=5, k_smooth=3, d_period=3, display_shift=3)
        src_bar = _first_true_bar(series, "K_CROSS_UP_D")
        da_bar = _first_true_bar(series, "DISPLAY_ALIGNED_K_CROSS_UP_D")
        if src_bar is not None and da_bar is not None and src_bar != da_bar:
            return
    raise AssertionError("source and display-aligned Stoch crosses did not occur on distinct bars")


def test_macd_shifted_signal_timing():
    for spike_at in range(40, 70):
        closes = [100 + np.sin(i / 8) * 0.5 for i in range(spike_at)] + [100 + i * 0.3 for i in range(20)] + [130.0] * 30
        bars = make_bars(closes, minutes=60)
        arrays = bars_to_arrays(bars, timeframe="1H")
        series = compute_macd_feature_series(arrays, fast=5, slow=13, signal=4, display_shift=3)
        src_bar = _first_true_bar(series, "MACD_CROSS_UP_SIGNAL")
        da_bar = _first_true_bar(series, "DISPLAY_ALIGNED_MACD_CROSS_UP_SIGNAL")
        if src_bar is not None and da_bar is not None and src_bar != da_bar:
            return
    raise AssertionError("source and display-aligned MACD crosses did not occur on distinct bars")


if __name__ == "__main__":
    test_bearish_geometry_stage_normalized_r()
    test_bullish_geometry_stage_same_thresholds()
    test_macd_histogram_contract()
    test_displacement_provenance()
    test_registry_output_parity()
    test_geometry_atr_and_leg_ratio()
    test_full_batch_streaming_parity()
    test_dma_shifted_signal_timing()
    test_stoch_shifted_signal_timing()
    test_macd_shifted_signal_timing()
    print("ALL REVIEW-FIX-1 TESTS PASS")
