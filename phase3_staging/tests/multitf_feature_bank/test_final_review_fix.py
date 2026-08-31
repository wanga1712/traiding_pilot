"""Final review fix — DiNapoli references, gap-safe displacement, warmup parity, numeric refs."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.bars import bars_to_arrays
from crypto_trading_bot.research_v2.indicator_engine.dinapoli_macd import (
    FAST_ALPHA,
    SIGNAL_ALPHA,
    SLOW_ALPHA,
    compute_dinapoli_macd_arrays,
)
from crypto_trading_bot.research_v2.indicator_engine.dinapoli_stochastic import (
    D_PERIOD,
    K_PERIOD,
    SLOWING,
    compute_dinapoli_stoch_arrays,
)
from crypto_trading_bot.research_v2.indicator_engine.math_core import ema, sma
from crypto_trading_bot.research_v2.indicator_engine.stochastic import _stoch_raw
from crypto_trading_bot.research_v2.indicator_engine.tests.fixtures import make_bars, make_ohlc_bars
from crypto_trading_bot.research_v2.multitf_feature_bank.geometry import compute_geometry_features
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
from crypto_trading_bot.research_v2.multitf_feature_bank.warmup import registry_warmup_bars

FLOAT_TOL = 1e-9


def _bars_with_gap(closes: list[float], gap_at: int, *, gap_hours: int = 72) -> list[dict]:
    bars = make_bars(closes, minutes=60)
    if gap_at >= len(bars) - 1:
        return bars
    anchor = datetime.fromisoformat(bars[gap_at]["close_time"].replace("Z", "+00:00"))
    for i in range(gap_at + 1, len(bars)):
        ot = anchor + timedelta(hours=gap_hours + (i - gap_at - 1))
        ct = ot + timedelta(hours=1)
        bars[i]["open_time"] = ot.isoformat()
        bars[i]["close_time"] = ct.isoformat()
    return bars


def _first_mature_index(prim_series, outputs: list[str], *, display_shift: int) -> int | None:
    _ = display_shift
    for i, s in enumerate(prim_series):
        if not s.valid:
            continue
        p = s.signal_primitives
        if not all(k in p for k in outputs):
            continue
        complete = True
        for k in outputs:
            v = p.get(k)
            if isinstance(v, bool):
                continue
            if v is None:
                complete = False
                break
        if complete:
            return i
    return None


def test_dinapoli_macd_reference_present():
    assert "DINAPOLI_MACD_REFERENCE_V1" in MACD_REGISTRY
    meta = MACD_REGISTRY["DINAPOLI_MACD_REFERENCE_V1"]
    assert meta["reference_status"] == "DINAPOLI_REFERENCE_IMPLEMENTATION"
    assert meta["fast_alpha"] == FAST_ALPHA
    assert meta["slow_alpha"] == SLOW_ALPHA
    assert meta["signal_alpha"] == SIGNAL_ALPHA


def test_dinapoli_stoch_reference_present():
    assert "DINAPOLI_PREFERRED_STOCHASTIC_REFERENCE_V1" in STOCHASTIC_REGISTRY
    meta = STOCHASTIC_REGISTRY["DINAPOLI_PREFERRED_STOCHASTIC_REFERENCE_V1"]
    assert meta["reference_status"] == "DINAPOLI_REFERENCE_IMPLEMENTATION"
    assert meta["k_period"] == K_PERIOD
    assert meta["slowing"] == SLOWING
    assert meta["d_period"] == D_PERIOD
    assert meta["smoothing"] == "MODIFIED_RECURSIVE"


def test_project_displaced_preserved():
    displaced_stoch = [k for k in STOCHASTIC_REGISTRY if "DISPLACED_STOCH" in k]
    displaced_macd = [k for k in MACD_REGISTRY if "DISPLACED_MACD" in k]
    assert len(displaced_stoch) == 12
    assert len(displaced_macd) == 9
    assert STOCHASTIC_REGISTRY[displaced_stoch[0]]["implementation_name"] == "PROJECT_DISPLACED_STOCHASTIC"
    assert MACD_REGISTRY[displaced_macd[0]]["implementation_name"] == "PROJECT_DISPLACED_MACD"


def test_reference_ab_semantics():
    geo = compute_geometry_features(
        a_price=100, b_price=200, c_price=150, current_price=160, atr=10.0
    )
    assert geo["REFERENCE_AB_LENGTH"] == 100.0
    assert abs(geo["CURRENT_VS_REFERENCE_AB_RATIO"] - 0.1) < FLOAT_TOL
    assert abs(geo["CURRENT_VS_REFERENCE_AB_RATIO"] - abs(geo["R_CURRENT"])) < FLOAT_TOL
    assert "CURRENT_VS_PREV_LEG_RATIO" not in geo


def test_dma_shifted_source_gap_invalidation():
    closes = [100.0 + i * 0.5 for i in range(50)]
    bars = _bars_with_gap(closes, gap_at=12)
    arrays = bars_to_arrays(bars, timeframe="1H")
    series = compute_dma_feature_series(arrays, ma_type="SMA", period=3, display_shift=3, atr=None)
    found = False
    for i, s in enumerate(series):
        if not s.valid:
            continue
        prim = s.signal_primitives
        if prim.get("MA_VALUE") is not None and prim.get("DISPLAY_ALIGNED_MA_VALUE") is None:
            found = True
            break
    assert found, "expected display-aligned None when shifted source invalid"


def test_stoch_shifted_source_gap_invalidation():
    closes = [50.0 + np.sin(i / 3) * 10 + i * 0.2 for i in range(60)]
    bars = _bars_with_gap(closes, gap_at=15)
    arrays = bars_to_arrays(bars, timeframe="1H")
    series = compute_stoch_feature_series(arrays, k_period=5, k_smooth=3, d_period=3, display_shift=3)
    found = any(
        s.valid
        and s.signal_primitives.get("K") is not None
        and s.signal_primitives.get("DISPLAY_ALIGNED_K") is None
        for s in series
    )
    assert found


def test_macd_shifted_source_gap_invalidation():
    closes = [100.0 + np.sin(i / 4) * 3 + i * 0.1 for i in range(80)]
    bars = _bars_with_gap(closes, gap_at=20)
    arrays = bars_to_arrays(bars, timeframe="1H")
    series = compute_macd_feature_series(arrays, fast=5, slow=13, signal=4, display_shift=3)
    found = any(
        s.valid
        and s.signal_primitives.get("MACD") is not None
        and s.signal_primitives.get("DISPLAY_ALIGNED_MACD") is None
        for s in series
    )
    assert found


def _expected_standard_stoch_raw_k(high, low, close, k_period, i):
    hh = float(np.max(high[i - k_period + 1 : i + 1]))
    ll = float(np.min(low[i - k_period + 1 : i + 1]))
    if hh == ll:
        return 50.0
    return (float(close[i]) - ll) / (hh - ll) * 100.0


def test_standard_stoch_numeric_reference():
    rows = [(float(c - 0.5), float(c + 1), float(c - 1), float(c)) for c in [10, 12, 11, 13, 14, 12, 15, 16, 14, 17, 18, 16]]
    bars = make_ohlc_bars(rows, minutes=60)
    arrays = bars_to_arrays(bars, timeframe="1H")
    series = compute_stoch_feature_series(arrays, k_period=5, k_smooth=3, d_period=3, display_shift=0)
    idx = 10
    raw = _stoch_raw(arrays.high, arrays.low, arrays.close, 5)
    k_sma = sma(raw, 3)
    d_sma = sma(k_sma, 3)
    assert series[idx].valid
    assert abs(series[idx].signal_primitives["RAW_K"] - _expected_standard_stoch_raw_k(arrays.high, arrays.low, arrays.close, 5, idx)) < FLOAT_TOL
    assert abs(series[idx].signal_primitives["K"] - float(k_sma[idx])) < FLOAT_TOL
    assert abs(series[idx].signal_primitives["D"] - float(d_sma[idx])) < FLOAT_TOL


def test_standard_macd_numeric_reference():
    closes = [100, 101, 102, 101, 103, 104, 103, 105, 106, 105, 107, 108, 107, 109, 110, 109, 111, 112, 111, 113, 114, 113, 115, 116, 115, 117, 118, 117, 119, 120]
    bars = make_bars(closes, minutes=60)
    arrays = bars_to_arrays(bars, timeframe="1H")
    series = compute_macd_feature_series(arrays, fast=5, slow=13, signal=4, display_shift=0)
    fast_e = ema(arrays.close, 5)
    slow_e = ema(arrays.close, 13)
    macd_line = fast_e - slow_e
    idx = 20
    assert series[idx].valid
    assert abs(series[idx].signal_primitives["MACD"] - float(macd_line[idx])) < FLOAT_TOL


def _reference_dinapoli_macd(close: np.ndarray) -> tuple[float, float, float]:
    fa = FAST_ALPHA
    sa = SLOW_ALPHA
    sig_a = SIGNAL_ALPHA
    fast = np.zeros(len(close))
    slow = np.zeros(len(close))
    fast[0] = close[0]
    slow[0] = close[0]
    for i in range(1, len(close)):
        fast[i] = fa * close[i] + (1 - fa) * fast[i - 1]
        slow[i] = sa * close[i] + (1 - sa) * slow[i - 1]
    macd = fast - slow
    signal = np.zeros(len(close))
    signal[0] = macd[0]
    for i in range(1, len(close)):
        signal[i] = sig_a * macd[i] + (1 - sig_a) * signal[i - 1]
    hist = macd - signal
    return float(macd[-1]), float(signal[-1]), float(hist[-1])


def test_dinapoli_macd_numeric_reference():
    closes = [100 + i * 0.3 + np.sin(i / 5) for i in range(40)]
    bars = make_bars(closes, minutes=60)
    arrays = bars_to_arrays(bars, timeframe="1H")
    series = compute_macd_feature_series(arrays, formula_version="DINAPOLI_MACD_REFERENCE_V1", display_shift=0)
    idx = 25
    em, es, eh = _reference_dinapoli_macd(arrays.close[: idx + 1])
    assert series[idx].valid
    assert abs(series[idx].signal_primitives["MACD"] - em) < 1e-6
    assert abs(series[idx].signal_primitives["SIGNAL"] - es) < 1e-6
    assert abs(series[idx].signal_primitives["HIST"] - eh) < 1e-6


def _reference_dinapoli_stoch(high, low, close, idx):
    fk_arr = _stoch_raw(high, low, close, K_PERIOD)
    k = np.full(len(close), np.nan)
    d = np.full(len(close), np.nan)
    fastk_first = K_PERIOD - 1
    k_seed = fastk_first + SLOWING - 1
    d_seed = k_seed + D_PERIOD - 1
    k[k_seed] = float(np.mean(fk_arr[fastk_first : k_seed + 1]))
    for i in range(k_seed + 1, idx + 1):
        k[i] = k[i - 1] + (fk_arr[i] - k[i - 1]) / SLOWING
    d[d_seed] = float(np.mean(k[k_seed : d_seed + 1]))
    for i in range(d_seed + 1, idx + 1):
        d[i] = d[i - 1] + (k[i] - d[i - 1]) / D_PERIOD
    return float(k[idx]), float(d[idx])


def test_dinapoli_stoch_numeric_reference():
    rows = [(float(c - 0.5), float(c + 1), float(c - 1), float(c)) for c in [10, 11, 12, 11, 13, 14, 13, 15, 16, 15, 17, 18, 17, 19, 20]]
    bars = make_ohlc_bars(rows, minutes=60)
    arrays = bars_to_arrays(bars, timeframe="1H")
    series = compute_stoch_feature_series(
        arrays,
        k_period=K_PERIOD,
        slowing=SLOWING,
        d_period=D_PERIOD,
        formula_version="DINAPOLI_PREFERRED_STOCH_REFERENCE_V1",
    )
    idx = 12
    ek, ed = _reference_dinapoli_stoch(arrays.high, arrays.low, arrays.close, idx)
    assert series[idx].valid
    assert abs(series[idx].signal_primitives["K"] - ek) < FLOAT_TOL
    assert abs(series[idx].signal_primitives["D"] - ed) < FLOAT_TOL


def test_warmup_metadata_matches_runtime():
    bars = make_bars([100 + np.sin(i / 7) * 5 + i * 0.12 for i in range(250)], minutes=60)
    arrays = bars_to_arrays(bars, timeframe="1H")
    from crypto_trading_bot.research_v2.indicator_engine.volatility import compute_atr_series

    atr_s = compute_atr_series(arrays, period=14)
    atr = np.array([s.values["atr"] if s.valid else float("nan") for s in atr_s], dtype=float)
    for ps_id, meta in DMA_REGISTRY.items():
        expected = registry_warmup_bars(meta) - 1
        s = compute_dma_feature_series(
            arrays,
            ma_type=meta["ma_type"],
            period=int(meta["period"]),
            display_shift=int(meta["display_shift"]),
            atr=atr,
        )
        got = _first_mature_index(s, FEATURE_OUTPUTS["DMA"], display_shift=int(meta["display_shift"]))
        assert got is not None, ps_id
        assert got == expected, f"DMA warmup mismatch {ps_id}: got {got} expected {expected}"
    for ps_id, meta in STOCHASTIC_REGISTRY.items():
        expected = registry_warmup_bars(meta) - 1
        fv = meta.get("formula_version", "STOCH_CANONICAL_V1")
        s = compute_stoch_feature_series(
            arrays,
            k_period=int(meta["k_period"]),
            k_smooth=int(meta.get("k_smooth", 3)),
            d_period=int(meta["d_period"]),
            display_shift=int(meta["display_shift"]),
            formula_version=fv,
            slowing=int(meta["slowing"]) if "slowing" in meta else None,
        )
        got = _first_mature_index(s, FEATURE_OUTPUTS["STOCHASTIC"], display_shift=int(meta["display_shift"]))
        assert got is not None, ps_id
        assert got == expected, f"Stoch warmup mismatch {ps_id}: got {got} expected {expected}"
    for ps_id, meta in MACD_REGISTRY.items():
        expected = registry_warmup_bars(meta) - 1
        fv = meta.get("formula_version", "MACD_CANONICAL_V1")
        if fv == "DINAPOLI_MACD_REFERENCE_V1":
            s = compute_macd_feature_series(arrays, display_shift=int(meta["display_shift"]), formula_version=fv)
        else:
            s = compute_macd_feature_series(
                arrays,
                fast=int(meta["fast"]),
                slow=int(meta["slow"]),
                signal=int(meta["signal"]),
                display_shift=int(meta["display_shift"]),
                formula_version=fv,
            )
        got = _first_mature_index(s, FEATURE_OUTPUTS["MACD"], display_shift=int(meta["display_shift"]))
        assert got is not None, ps_id
        assert got == expected, f"MACD warmup mismatch {ps_id}: got {got} expected {expected}"


def test_all_parameter_set_output_parity():
    bars = make_bars([100 + np.sin(i / 6) * 4 + i * 0.15 for i in range(250)], minutes=60)
    t0 = datetime.fromisoformat(bars[0]["open_time"].replace("Z", "+00:00"))
    pivots = [
        PivotRecord("P0", 100, t0 + timedelta(hours=24), timeframe="1H"),
        PivotRecord("P1", 120, t0 + timedelta(hours=48), timeframe="1H"),
        PivotRecord("P2", 110, t0 + timedelta(hours=72), timeframe="1H"),
        PivotRecord("P3", 115, t0 + timedelta(hours=96), timeframe="1H"),
        PivotRecord("P4", 125, t0 + timedelta(hours=120), timeframe="1H"),
    ]
    bank = FeatureBank({"1H": bars}, pivots_by_tf={"1H": pivots})
    t = datetime.fromisoformat(bars[200]["close_time"].replace("Z", "+00:00"))
    snap = bank.snapshot(t)
    for ps_id in DMA_REGISTRY:
        for feat in FEATURE_OUTPUTS["DMA"]:
            assert f"1H.{ps_id}.{feat}" in snap.features, f"missing DMA {ps_id}.{feat}"
    for ps_id in STOCHASTIC_REGISTRY:
        for feat in FEATURE_OUTPUTS["STOCHASTIC"]:
            assert f"1H.{ps_id}.{feat}" in snap.features, f"missing STOCH {ps_id}.{feat}"
    for ps_id in MACD_REGISTRY:
        for feat in FEATURE_OUTPUTS["MACD"]:
            assert f"1H.{ps_id}.{feat}" in snap.features, f"missing MACD {ps_id}.{feat}"


if __name__ == "__main__":
    test_dinapoli_macd_reference_present()
    test_dinapoli_stoch_reference_present()
    test_project_displaced_preserved()
    test_reference_ab_semantics()
    test_dma_shifted_source_gap_invalidation()
    test_stoch_shifted_source_gap_invalidation()
    test_macd_shifted_source_gap_invalidation()
    test_standard_stoch_numeric_reference()
    test_standard_macd_numeric_reference()
    test_dinapoli_macd_numeric_reference()
    test_dinapoli_stoch_numeric_reference()
    test_warmup_metadata_matches_runtime()
    test_all_parameter_set_output_parity()
    print("ALL FINAL REVIEW FIX TESTS PASS")
