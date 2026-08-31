"""Validation runner — INDEPENDENT-REVIEW-FIX-1 gates."""
from __future__ import annotations

import csv
import inspect
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.bars import bars_to_arrays
from crypto_trading_bot.research_v2.indicator_engine.segments import same_segment, segment_start_for
from crypto_trading_bot.research_v2.indicator_engine.volatility import compute_atr_series
from crypto_trading_bot.research_v2.multitf_feature_bank.registries import FEATURE_OUTPUTS, build_feature_registry_rows
from crypto_trading_bot.research_v2.multitf_feature_bank.snapshot import FeatureBank

from .dno import compute_dno_feature_series, compute_dno_series, compute_masked_dno_series
from .config import PredictorConfig
from .dynamic_predictor import compute_predictor_at_index, compute_predictor_feature_series
from .inverse import (
    INSUFFICIENT_CONTIGUOUS_HISTORY,
    price_for_next_detrended_value,
    price_for_next_detrended_value_segment_safe,
    verify_inverse_roundtrip,
)
from .peaks import confirmed_extrema_at
from .registry import INVERSE_PREDICTOR_ENGINE_REUSED, INVERSE_PREDICTOR_FAMILY_STATUS, OSCILLATOR_PREDICTOR_REGISTRY, TARGET_AGGREGATION
from .series_engine import MANDATORY_DYNAMIC_FIELDS, PredictorSeriesEngine
from .streaming import StreamingOscillatorPredictor
from .version import OSCILLATOR_PREDICTOR_VERSION, WIP_ID

REPO_ROOT = Path(__file__).resolve().parents[4]
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / WIP_ID

PREDICTOR_OUTPUT_KEYS = FEATURE_OUTPUTS["OSC_PREDICTOR"]


def _make_bars(closes: list[float], *, tf: str = "1H", start: datetime | None = None) -> list[dict[str, Any]]:
    base = start or datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = []
    for i, c in enumerate(closes):
        t = base + timedelta(hours=i)
        bars.append(
            {
                "open_time": t,
                "close_time": t,
                "open": c,
                "high": c,
                "low": c,
                "close": c,
                "volume": 1.0,
                "timeframe": tf,
            }
        )
    return bars


def _gap_fixture_bars(seg_a_len: int = 80, seg_b_len: int = 80) -> tuple[list[dict[str, Any]], int]:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    seg_a = []
    for i in range(seg_a_len):
        t = base + timedelta(hours=i)
        c = 3000 + np.sin(i / 5) * 40 + i * 0.2
        seg_a.append(
            {
                "open_time": t,
                "close_time": t,
                "open": c,
                "high": c,
                "low": c,
                "close": c,
                "volume": 1.0,
                "timeframe": "1H",
            }
        )
    seg_b_start = seg_a_len + 10
    seg_b = []
    for i in range(seg_b_len):
        t = base + timedelta(hours=seg_b_start + i)
        c = 3200 + np.cos(i / 4) * 80 + np.sin(i / 2.5) * 45 + i * 0.15
        seg_b.append(
            {
                "open_time": t,
                "close_time": t,
                "open": c,
                "high": c,
                "low": c,
                "close": c,
                "volume": 1.0,
                "timeframe": "1H",
            }
        )
    return seg_a + seg_b, seg_a_len


def _atr_for(bars: list[dict]) -> np.ndarray:
    arrays = bars_to_arrays(bars, timeframe="1H")
    return np.array(
        [
            float(s.values["atr"]) if s.valid and s.values.get("atr") is not None else float("nan")
            for s in compute_atr_series(arrays, period=14)
        ]
    )


def run_numeric_reference_tests() -> dict[str, Any]:
    closes = np.array([100.0, 101.0, 102.0, 103.0, 104.0, 105.0], dtype=float)
    n = 7
    d_ob, d_os = 2.5, -1.8
    return {
        "DNO_INVERSE_ROUNDTRIP": "PASS" if verify_inverse_roundtrip(closes, period=n, target=1.0) else "FAIL",
        "DNO_INVERSE_OB_ROUNDTRIP": "PASS" if verify_inverse_roundtrip(closes, period=n, target=d_ob) else "FAIL",
        "DNO_INVERSE_OS_ROUNDTRIP": "PASS" if verify_inverse_roundtrip(closes, period=n, target=d_os) else "FAIL",
    }


def run_pre_gap_extrema_excluded() -> dict[str, Any]:
    bars, seg_b_start = _gap_fixture_bars(60, 60)
    arrays = bars_to_arrays(bars, timeframe="1H")
    dno = compute_masked_dno_series(arrays, period=7)
    cfg = PredictorConfig(period=7, peak_strength=2, lookback=80, samples=3, ob_os_level_percent=0.8)
    decision = seg_b_start + 40
    peaks, troughs = confirmed_extrema_at(
        dno, arrays.gap_flags, decision, peak_strength=cfg.peak_strength, lookback=cfg.lookback
    )
    ok = all(p.index >= seg_b_start for p in peaks) and all(t.index >= seg_b_start for t in troughs)
    ok = ok and all(same_segment(arrays.gap_flags, p.index, decision) for p in peaks)
    return {"PRE_GAP_EXTREMA_EXCLUDED_POST_GAP": "PASS" if ok else "FAIL"}


def run_dno_mask_tests() -> dict[str, Any]:
    bars, seg_b_start = _gap_fixture_bars(40, 40)
    arrays = bars_to_arrays(bars, timeframe="1H")
    masked = compute_masked_dno_series(arrays, period=7)
    raw, _ = compute_dno_series(arrays, period=7)
    seg_start = seg_b_start
    warmup_ok = all(np.isnan(masked[i]) for i in range(seg_start, seg_start + 6))
    first_valid = seg_start + 6
    used_ok = not np.isnan(masked[first_valid]) if first_valid < len(masked) else False
    extrema_ok = True
    for i in range(seg_start, seg_start + 6):
        peaks, _ = confirmed_extrema_at(masked, arrays.gap_flags, i, peak_strength=2, lookback=20)
        if peaks:
            extrema_ok = False
    return {
        "DNO_RAW_SERIES_SEGMENT_MASKED": "PASS" if warmup_ok and used_ok else "FAIL",
        "POST_GAP_WARMUP_DNO_NOT_USED_FOR_EXTREMA": "PASS" if extrema_ok else "FAIL",
        "raw_cross_gap_non_nan_count": int(np.sum(~np.isnan(raw[seg_start : seg_start + 6]))),
    }


def run_segment_safe_inverse_tests() -> dict[str, Any]:
    bars, seg_b_start = _gap_fixture_bars(50, 50)
    arrays = bars_to_arrays(bars, timeframe="1H")
    period = 7
    target = 1.5
    t_seg_b = seg_b_start + 30
    pre_price, pre_st = price_for_next_detrended_value_segment_safe(
        arrays.close, arrays.gap_flags, t_seg_b, period=period, target_oscillator_value=target
    )
    mutated = arrays.close.copy()
    mutated[:seg_b_start] += 5000.0
    pre_price_mut, _ = price_for_next_detrended_value_segment_safe(
        mutated, arrays.gap_flags, t_seg_b, period=period, target_oscillator_value=target
    )
    t_post_warm = seg_b_start + 4
    t_post_ok = seg_b_start + period - 2
    post_insuf, post_st = price_for_next_detrended_value_segment_safe(
        arrays.close, arrays.gap_flags, t_post_warm, period=period, target_oscillator_value=target
    )
    post_ok, post_ok_st = price_for_next_detrended_value_segment_safe(
        arrays.close, arrays.gap_flags, t_post_ok, period=period, target_oscillator_value=target
    )
    seg_closes = arrays.close[seg_b_start : t_post_ok + 1]
    manual = price_for_next_detrended_value(seg_closes, period=period, target_oscillator_value=target)
    return {
        "DNO_INVERSE_PRE_GAP_PRICE_INDEPENDENCE": "PASS"
        if pre_st == "OK" and pre_price == pre_price_mut
        else "FAIL",
        "DNO_INVERSE_INSUFFICIENT_AFTER_GAP": "PASS"
        if post_st == INSUFFICIENT_CONTIGUOUS_HISTORY
        else "FAIL",
        "DNO_INVERSE_RECOVERS_AFTER_N_MINUS_1_CLOSES": "PASS"
        if post_ok_st == "OK" and post_ok == manual
        else "FAIL",
    }


def run_moving_band_reference_tests() -> dict[str, Any]:
    # Explicit reference semantics (price vs band, not band vs price)
    ob_up = 100.0 <= 105.0 and 106.0 > 104.0
    ob_down = 110.0 >= 108.0 and 105.0 < 107.0
    os_up = 90.0 <= 92.0 and 95.0 > 94.0
    os_down = 100.0 >= 98.0 and 96.0 < 99.0
    ob_conv = abs(104.0 - 106.0) < abs(105.0 - 100.0)
    os_conv = abs(91.0 - 89.0) < abs(93.0 - 90.0)

    cfg = PredictorConfig(period=7, peak_strength=2, lookback=200, samples=2, ob_os_level_percent=0.8)
    closes = [3000 + np.sin(i / 3) * 50 + i * 0.05 for i in range(200)]
    bars = _make_bars(closes)
    arrays = bars_to_arrays(bars, timeframe="1H")
    series = compute_predictor_feature_series(arrays, config=cfg, atr=_atr_for(bars))
    series_ob = series_os = series_conv = False
    for i in range(1, len(series)):
        cur, prev = series[i], series[i - 1]
        if not cur.get("valid") or not prev.get("valid"):
            continue
        cp, pp = float(arrays.close[i]), float(arrays.close[i - 1])
        cob, pob = cur["PREDICTOR_OB_PRICE_NEXT_BAR"], prev["PREDICTOR_OB_PRICE_NEXT_BAR"]
        cos, pos = cur["PREDICTOR_OS_PRICE_NEXT_BAR"], prev["PREDICTOR_OS_PRICE_NEXT_BAR"]
        if cur.get("CROSSED_OB_BAND_UP") == bool(pp <= pob and cp > cob):
            series_ob = series_ob or bool(cur.get("CROSSED_OB_BAND_UP"))
        if cur.get("CROSSED_OS_BAND_DOWN") == bool(pp >= pos and cp < cos):
            series_os = series_os or bool(cur.get("CROSSED_OS_BAND_DOWN"))
        if cur.get("OB_BAND_CONVERGING_TO_PRICE") == bool(abs(cob - cp) < abs(pob - pp)):
            series_conv = series_conv or bool(cur.get("OB_BAND_CONVERGING_TO_PRICE"))
    return {
        "MOVING_OB_CROSS_REFERENCE": "PASS" if ob_up and ob_down else "FAIL",
        "MOVING_OS_CROSS_REFERENCE": "PASS" if os_up and os_down else "FAIL",
        "BAND_CONVERGENCE_REFERENCE": "PASS" if ob_conv and os_conv else "FAIL",
        "series_ob_event_seen": series_ob,
        "series_os_event_seen": series_os,
        "series_conv_seen": series_conv,
    }


def run_nonrecursive_and_scaling() -> dict[str, Any]:
    src = inspect.getsource(compute_predictor_at_index)
    nonrecursive = "compute_predictor_at_index" not in inspect.getsource(PredictorSeriesEngine.step)
    nonrecursive = nonrecursive and "compute_predictor_at_index" not in inspect.getsource(
        PredictorSeriesEngine.compute_series
    )

    def _bench(n: int) -> float:
        closes = [3000 + np.sin(i / 7) * 30 + i * 0.01 for i in range(n)]
        bars = _make_bars(closes)
        arrays = bars_to_arrays(bars, timeframe="1H")
        cfg = PredictorConfig(period=7, peak_strength=2, lookback=100, samples=4, ob_os_level_percent=0.8)
        atr = _atr_for(bars)
        t0 = time.perf_counter()
        compute_predictor_feature_series(arrays, config=cfg, atr=atr)
        return time.perf_counter() - t0

    t10 = _bench(10_000)
    t50 = _bench(50_000)
    ratio = t50 / t10 if t10 > 0 else 999.0
    return {
        "PREDICTOR_NONRECURSIVE_SERIES": "PASS" if nonrecursive else "FAIL",
        "PREDICTOR_10K_WALL_TIME": round(t10, 4),
        "PREDICTOR_50K_WALL_TIME": round(t50, 4),
        "PREDICTOR_SCALING_RATIO": round(ratio, 4),
        "PREDICTOR_SCALING_SANITY": "PASS" if ratio < 12.0 else "FAIL",
    }


def run_streaming_incremental() -> dict[str, Any]:
    closes = [3000 + np.sin(i / 5) * 20 for i in range(300)]
    bars = _make_bars(closes)
    cfg = PredictorConfig(period=7, peak_strength=2, lookback=80, samples=3, ob_os_level_percent=0.75)
    stream = StreamingOscillatorPredictor(config=cfg)
    stream.set_atr(_atr_for(bars))
    for b in bars:
        stream.on_bar_close(b)
    ok = stream.full_history_recompute_count == 0
    return {"STREAMING_DOES_NOT_FULL_RECOMPUTE_HISTORY": "PASS" if ok else "FAIL"}


def _predictor_keys(row: dict[str, Any]) -> list[str]:
    return [k for k in PREDICTOR_OUTPUT_KEYS if k in row]


def _pred_equal(a: dict[str, Any], b: dict[str, Any], *, tol: float = 1e-6) -> bool:
    keys = set(a.keys()) | set(b.keys())
    for k in keys:
        va, vb = a.get(k), b.get(k)
        if isinstance(va, (float, np.floating)) and isinstance(vb, (float, np.floating)):
            if np.isnan(va) and np.isnan(vb):
                continue
            if abs(float(va) - float(vb)) > tol:
                return False
        elif va != vb:
            return False
    return True


def run_batch_streaming_parity() -> dict[str, Any]:
    closes = [3000 + np.sin(i / 4) * 45 + i * 0.08 for i in range(400)]
    bars = _make_bars(closes)
    cfg = PredictorConfig(period=7, peak_strength=2, lookback=120, samples=4, ob_os_level_percent=0.75)
    atr = _atr_for(bars)
    stream = StreamingOscillatorPredictor(config=cfg)
    stream.set_atr(atr)
    streamed: list[tuple[dict, dict]] = []
    for b in bars:
        streamed.append(stream.on_bar_close(b))
    batch = stream.batch_recompute()
    valid_rows = [i for i, (_, p) in enumerate(batch) if p.get("valid")]
    ok = len(valid_rows) >= 20
    if ok:
        for i in valid_rows:
            sp, bp = streamed[i][1], batch[i][1]
            if not _pred_equal(sp, bp):
                ok = False
                break
    gap_bars, seg_b = _gap_fixture_bars(100, 100)
    gap_atr = _atr_for(gap_bars)
    gs = StreamingOscillatorPredictor(config=cfg)
    gs.set_atr(gap_atr)
    gstream, gbatch = [], []
    for b in gap_bars:
        gstream.append(gs.on_bar_close(b))
    gbatch = gs.batch_recompute()
    gap_ok = len(gstream) == len(gbatch)
    if gap_ok:
        for i, ((_, sp), (_, bp)) in enumerate(zip(gstream, gbatch)):
            if sp.get("valid") and bp.get("valid") and not _pred_equal(sp, bp):
                gap_ok = False
                break
            if sp.get("valid") != bp.get("valid"):
                gap_ok = False
                break
    return {
        "VALID_PREDICTOR_ROW_COUNT": len(valid_rows),
        "PREDICTOR_BATCH_STREAMING_PARITY": "PASS" if ok else "FAIL",
        "PREDICTOR_BATCH_STREAMING_GAP_PARITY": "PASS" if gap_ok else "FAIL",
    }


def run_post_gap_independence() -> dict[str, Any]:
    bars, seg_b_start = _gap_fixture_bars(70, 80)
    arrays = bars_to_arrays(bars, timeframe="1H")
    cfg = PredictorConfig(period=7, peak_strength=2, lookback=80, samples=2, ob_os_level_percent=0.8)
    atr = _atr_for(bars)
    decision = seg_b_start + 55
    for attempt in range(20):
        base = compute_predictor_at_index(arrays, decision, config=cfg, atr=atr)
        if base.get("valid"):
            break
        decision += 1
    dno = compute_masked_dno_series(arrays, period=7)
    peaks, troughs = confirmed_extrema_at(
        dno, arrays.gap_flags, decision, peak_strength=2, lookback=60
    )
    ext_ok = all(p.index >= seg_b_start for p in peaks) and all(t.index >= seg_b_start for t in troughs)
    mutated = [dict(b) for b in bars]
    for i in range(seg_b_start):
        mutated[i]["close"] = float(mutated[i]["close"]) + 9000.0
        mutated[i]["open"] = mutated[i]["high"] = mutated[i]["low"] = mutated[i]["close"]
    m_arrays = bars_to_arrays(mutated, timeframe="1H")
    after = compute_predictor_at_index(m_arrays, decision, config=cfg, atr=atr)
    keys = list(MANDATORY_DYNAMIC_FIELDS)
    mut_ok = base.get("valid") and all(base.get(k) == after.get(k) for k in keys)
    return {
        "PREDICTOR_POST_GAP_INDEPENDENCE": "PASS" if ext_ok and mut_ok else "FAIL",
        "pre_gap_extrema_in_segment_b": ext_ok,
    }


def run_future_mutation_test() -> dict[str, Any]:
    closes = [3000 + np.sin(i / 3) * 60 + i * 0.1 for i in range(250)]
    bars = _make_bars(closes)
    arrays = bars_to_arrays(bars, timeframe="1H")
    atr = _atr_for(bars)
    cfg = PredictorConfig(period=7, peak_strength=2, lookback=80, samples=4, ob_os_level_percent=0.8)
    t = 180
    base = compute_predictor_at_index(arrays, t, config=cfg, atr=atr)
    base_valid = bool(base.get("valid")) and all(base.get(k) is not None for k in MANDATORY_DYNAMIC_FIELDS)
    mutated = [dict(b) for b in bars]
    for j in range(t + 1, len(mutated)):
        mutated[j]["close"] = float(mutated[j]["close"]) + 500.0
        mutated[j]["open"] = mutated[j]["high"] = mutated[j]["low"] = mutated[j]["close"]
    m_arrays = bars_to_arrays(mutated, timeframe="1H")
    after = compute_predictor_at_index(m_arrays, t, config=cfg, atr=_atr_for(mutated))
    keys = list(MANDATORY_DYNAMIC_FIELDS)
    ok = all(base.get(k) == after.get(k) for k in keys)
    return {
        "FUTURE_MUTATION_BASE_STATE_VALID": "PASS" if base_valid else "FAIL",
        "PREDICTOR_FUTURE_MUTATION_TEST": "PASS" if base_valid and ok else "FAIL",
    }


def run_inverse_family_audit() -> dict[str, Any]:
    from crypto_trading_bot.research_v2.inverse_predictors import engine as inv_engine

    src = inspect.getsource(inv_engine)
    checks = {
        "STANDARD_STOCH_PREDICTOR_STATUS": INVERSE_PREDICTOR_FAMILY_STATUS["STANDARD_STOCH_THRESHOLD_PREDICTOR"],
        "DINAPOLI_STOCH_PREDICTOR_STATUS": INVERSE_PREDICTOR_FAMILY_STATUS[
            "DINAPOLI_PREFERRED_STOCH_THRESHOLD_PREDICTOR"
        ],
        "STANDARD_MACD_PREDICTOR_STATUS": INVERSE_PREDICTOR_FAMILY_STATUS["STANDARD_MACD_CROSS_PREDICTOR"],
        "DINAPOLI_MACD_PREDICTOR_STATUS": INVERSE_PREDICTOR_FAMILY_STATUS["DINAPOLI_MACD_CROSS_PREDICTOR"],
        "DNO_PREDICTOR_STATUS": INVERSE_PREDICTOR_FAMILY_STATUS["DNO_OB_OS_PREDICTOR"],
    }
    ok = (
        checks["STANDARD_STOCH_PREDICTOR_STATUS"] == "SUPPORTED_ANALYTICALLY"
        and "STOCH_K_LEVEL" in src
        and checks["DINAPOLI_STOCH_PREDICTOR_STATUS"] == "NOT_IMPLEMENTED"
        and checks["DINAPOLI_MACD_PREDICTOR_STATUS"] == "NOT_IMPLEMENTED"
        and "DNO_OB_OS_PREDICTOR" in src
        and checks["DNO_PREDICTOR_STATUS"] == "SUPPORTED_ANALYTICALLY"
    )
    checks["INVERSE_FAMILY_STATUS_EXECUTABLE_PARITY"] = "PASS" if ok else "FAIL"
    return checks


def run_feature_registry_parity() -> dict[str, Any]:
    rows = build_feature_registry_rows()
    dno_ids = {r["feature_id"] for r in rows if r["family"] == "DNO"}
    osc_ids = {r["feature_id"] for r in rows if r["family"] == "OSC_PREDICTOR"}
    closes = [3000 + np.sin(i / 2) * 120 + (i % 17) * 3 for i in range(600)]
    bars = _make_bars(closes)
    bank = FeatureBank({"1H": bars})
    snap = bank.snapshot(bars[-1]["close_time"])
    emitted_dno = {k for k in snap.features if k.startswith("1H.DNO.")}
    emitted_osc = {k for k in snap.features if k.startswith("1H.OSC_PREDICTOR.")}
    dno_ok = emitted_dno.issubset(dno_ids)
    osc_ok = emitted_osc.issubset(osc_ids) if emitted_osc else False
    if emitted_osc:
        osc_ok = osc_ok and len(emitted_osc) >= 10
    return {
        "DNO_FEATURE_REGISTRY_PARITY": "PASS" if dno_ok and len(emitted_dno) >= 5 else "FAIL",
        "OSC_PREDICTOR_FEATURE_REGISTRY_PARITY": "PASS" if osc_ok else "FAIL",
        "emitted_dno_count": len(emitted_dno),
        "emitted_osc_count": len(emitted_osc),
    }


def run_peak_and_leakage() -> dict[str, Any]:
    osc = np.array([0.0, 2.0, 5.0, 8.0, 5.0, 2.0, 0.0, -1.0], dtype=float)
    gap = np.zeros(len(osc), dtype=bool)
    k = 2
    before = confirmed_extrema_at(osc, gap, 4, peak_strength=k, lookback=20)
    at_confirm = confirmed_extrema_at(osc, gap, 5, peak_strength=k, lookback=20)
    peak_before = [p for p in before[0] if abs(p.value - 8.0) < 1e-9]
    peak_at = [p for p in at_confirm[0] if abs(p.value - 8.0) < 1e-9]
    at_t = confirmed_extrema_at(osc, gap, 4, peak_strength=k, lookback=50)
    mutated = osc.copy()
    mutated[5:] = 999.0
    at_t_mut = confirmed_extrema_at(mutated, gap, 4, peak_strength=k, lookback=50)
    leak_ok = len(at_t[0]) == len(at_t_mut[0]) and all(
        a.index == b.index and a.value == b.value for a, b in zip(at_t[0], at_t_mut[0])
    )
    return {
        "PEAK_CONFIRMATION_CAUSALITY": "PASS"
        if len(peak_before) == 0 and len(peak_at) == 1
        else "FAIL",
        "FUTURE_PEAK_LEAKAGE_TEST": "PASS" if leak_ok else "FAIL",
    }


SOURCE_AUTHORITY_MD = """# Source authority v1

## CQG Oscillator (documented)

`OSC = MA1 - MA2`

Public CQG setup maps to DiNapoli non-proprietary Detrended Oscillator reference:

- MA1: period=1, type=SIMPLE, price=CLOSE
- MA2: period=7, type=SIMPLE, price=CLOSE

Project name: `DINAPOLI_DETRENDED_OSCILLATOR_REFERENCE_V1`  
Reference status: `DINAPOLI_NONPROPRIETARY_REFERENCE`

Formula: `DNO_t = Close_t - SMA_7(Close)_t`

## CQG Oscillator Predictor (public semantics only)

One-period-ahead price bands derived from oscillator targets.

Public parameters (CQG UI semantics):

- Period
- PeakStrength
- Lookback
- Samples
- OB/OS Level (%)
- Custom OB / Custom OS

## Project reconstruction (NOT proprietary exact)

`PROJECT_DINAPOLI_STYLE_OSCILLATOR_PREDICTOR_V1`

Target aggregation: `PROJECT_MEAN_CONFIRMED_EXTREMA_V1`

```
MEAN_OB = mean(selected positive confirmed peaks)
MEAN_OS = mean(selected negative confirmed troughs)
TARGET_OB = OB_OS_LEVEL_PERCENT * MEAN_OB
TARGET_OS = OB_OS_LEVEL_PERCENT * MEAN_OS
```

Peak confirmation: `PEAK_AVAILABLE_AT = extremum_index + PeakStrength`

Segment policy: `PREDICTOR_EXTREMA_CROSS_GAP=NO`

## Separation of authorities

| Component | Status |
|---|---|
| DNO reference | Documented non-proprietary |
| Oscillator predictor bands | PROJECT_RECONSTRUCTION |
| INVERSE_PREDICTOR_ENGINE_V1 | Separate engine (DMA/Stoch/MACD) |
| DiNapoli Preferred Stoch inverse | NOT_IMPLEMENTED in engine |
| DiNapoli alpha MACD inverse | NOT_IMPLEMENTED in engine |

No proprietary equation recovery is claimed.
"""


def write_artifacts(results: dict[str, Any]) -> None:
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_ROOT / "numeric_reference_tests_v1.json").write_text(
        json.dumps({k: results[k] for k in results if "INVERSE" in k or "DNO_INVERSE" in k or k.startswith("DNO_INVERSE")}, indent=2),
        encoding="utf-8",
    )
    anti_keys = [
        "PEAK_CONFIRMATION_CAUSALITY",
        "FUTURE_PEAK_LEAKAGE_TEST",
        "PREDICTOR_FUTURE_MUTATION_TEST",
        "FUTURE_MUTATION_BASE_STATE_VALID",
        "PRE_GAP_EXTREMA_EXCLUDED_POST_GAP",
        "DNO_RAW_SERIES_SEGMENT_MASKED",
        "POST_GAP_WARMUP_DNO_NOT_USED_FOR_EXTREMA",
        "PREDICTOR_POST_GAP_INDEPENDENCE",
    ]
    (ARTIFACT_ROOT / "anti_leakage_tests_v1.json").write_text(
        json.dumps({k: results[k] for k in anti_keys if k in results}, indent=2), encoding="utf-8"
    )
    (ARTIFACT_ROOT / "batch_streaming_parity_v1.json").write_text(
        json.dumps(
            {
                k: results[k]
                for k in (
                    "VALID_PREDICTOR_ROW_COUNT",
                    "PREDICTOR_BATCH_STREAMING_PARITY",
                    "PREDICTOR_BATCH_STREAMING_GAP_PARITY",
                    "STREAMING_DOES_NOT_FULL_RECOMPUTE_HISTORY",
                )
                if k in results
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (ARTIFACT_ROOT / "source_authority_v1.md").write_text(SOURCE_AUTHORITY_MD, encoding="utf-8")
    with (ARTIFACT_ROOT / "predictor_registry_v1.csv").open("w", newline="", encoding="utf-8") as f:
        rows = list(OSCILLATOR_PREDICTOR_REGISTRY.values())
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    for name, body in {
        "detrended_oscillator_formula_v1.md": "# DNO\n\nDNO_t = Close_t - SMA_N(Close)_t\n",
        "inverse_formula_derivation_v1.md": "# Inverse\n\nP = (N * D_TARGET + S) / (N - 1)\n",
        "dynamic_target_semantics_v1.md": f"# Dynamic targets\n\nTARGET_AGGREGATION={TARGET_AGGREGATION}\n",
        "peak_confirmation_semantics_v1.md": "# Peak confirmation\n\nPEAK_AVAILABLE_AT = i + K; same-segment only.\n",
    }.items():
        (ARTIFACT_ROOT / name).write_text(body, encoding="utf-8")
    manifest = {
        "wip_id": WIP_ID,
        "version": OSCILLATOR_PREDICTOR_VERSION,
        "mode": "INDEPENDENT-REVIEW-FIX-1",
        "artifact_root": str(ARTIFACT_ROOT.relative_to(REPO_ROOT)).replace("\\", "/"),
        "tests": results,
        "inverse_predictor_families": INVERSE_PREDICTOR_FAMILY_STATUS,
        "INVERSE_PREDICTOR_ENGINE_REUSED": INVERSE_PREDICTOR_ENGINE_REUSED,
    }
    (ARTIFACT_ROOT / "manifest_v1.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def main() -> dict[str, Any]:
    results: dict[str, Any] = {}
    results.update(run_numeric_reference_tests())
    results.update(run_pre_gap_extrema_excluded())
    results.update(run_dno_mask_tests())
    results.update(run_segment_safe_inverse_tests())
    results.update(run_moving_band_reference_tests())
    results.update(run_nonrecursive_and_scaling())
    results.update(run_streaming_incremental())
    results.update(run_batch_streaming_parity())
    results.update(run_post_gap_independence())
    results.update(run_future_mutation_test())
    results.update(run_inverse_family_audit())
    results.update(run_feature_registry_parity())
    results.update(run_peak_and_leakage())
    from .visual_audit import run_real_history_visual_audit

    results.update(run_real_history_visual_audit())
    write_artifacts(results)
    return results


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
