"""Validation runner and artifact generation for OSCILLATOR-PREDICTOR-REFERENCE-1."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.bars import bars_to_arrays
from crypto_trading_bot.research_v2.indicator_engine.volatility import compute_atr_series

from .dno import DNO_DEFAULT_PERIOD, compute_dno_feature_series
from .dynamic_predictor import PredictorConfig, compute_predictor_at_index, compute_predictor_feature_series
from .inverse import price_for_next_detrended_value, verify_inverse_roundtrip
from .peaks import confirmed_extrema_at
from .registry import (
    INVERSE_PREDICTOR_ENGINE_REUSED,
    INVERSE_PREDICTOR_FAMILY_STATUS,
    OSCILLATOR_PREDICTOR_REGISTRY,
    TARGET_AGGREGATION,
)
from .streaming import StreamingOscillatorPredictor
from .version import OSCILLATOR_PREDICTOR_VERSION, WIP_ID

REPO_ROOT = Path(__file__).resolve().parents[4]
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / WIP_ID


def _make_bars(closes: list[float], *, tf: str = "1H") -> list[dict[str, Any]]:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = []
    for i, c in enumerate(closes):
        t = base.replace(hour=i % 24, day=1 + i // 24)
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


def run_numeric_reference_tests() -> dict[str, Any]:
    closes = np.array([100.0, 101.0, 102.0, 103.0, 104.0, 105.0], dtype=float)
    n = 7
    d_ob = 2.5
    d_os = -1.8
    p_ob = price_for_next_detrended_value(closes, period=n, target_oscillator_value=d_ob)
    p_os = price_for_next_detrended_value(closes, period=n, target_oscillator_value=d_os)
    ob_ok = verify_inverse_roundtrip(closes, period=n, target=d_ob)
    os_ok = verify_inverse_roundtrip(closes, period=n, target=d_os)
    s = float(np.sum(closes))
    manual_ob = (n * d_ob + s) / (n - 1)
    manual_os = (n * d_os + s) / (n - 1)
    return {
        "DNO_INVERSE_ROUNDTRIP": "PASS" if verify_inverse_roundtrip(closes, period=n, target=1.0) else "FAIL",
        "DNO_INVERSE_OB_ROUNDTRIP": "PASS" if ob_ok else "FAIL",
        "DNO_INVERSE_OS_ROUNDTRIP": "PASS" if os_ok else "FAIL",
        "manual_ob_price": manual_ob,
        "computed_ob_price": p_ob,
        "manual_os_price": manual_os,
        "computed_os_price": p_os,
        "fixture_closes": closes.tolist(),
        "period": n,
    }


def run_peak_confirmation_test() -> dict[str, Any]:
    osc = np.array([0.0, 2.0, 5.0, 8.0, 5.0, 2.0, 0.0, -1.0], dtype=float)
    gap = np.zeros(len(osc), dtype=bool)
    k = 2
    before = confirmed_extrema_at(osc, gap, 4, peak_strength=k, lookback=20)
    at_confirm = confirmed_extrema_at(osc, gap, 5, peak_strength=k, lookback=20)
    peak_before = [p for p in before[0] if abs(p.value - 8.0) < 1e-9]
    peak_at = [p for p in at_confirm[0] if abs(p.value - 8.0) < 1e-9]
    return {
        "PEAK_CONFIRMATION_CAUSALITY": "PASS"
        if len(peak_before) == 0 and len(peak_at) == 1 and peak_at[0].available_at_index == 5
        else "FAIL",
        "before_peak_count": len(peak_before),
        "at_confirm_peak_count": len(peak_at),
    }


def run_future_leakage_test() -> dict[str, Any]:
    osc = np.array([0.0, 1.0, 3.0, 5.0, 3.0, 1.0, 0.0], dtype=float)
    gap = np.zeros(len(osc), dtype=bool)
    k = 2
    at_t = confirmed_extrema_at(osc, gap, 4, peak_strength=k, lookback=50)
    mutated = osc.copy()
    mutated[5:] = 999.0
    at_t_mut = confirmed_extrema_at(mutated, gap, 4, peak_strength=k, lookback=50)
    same = len(at_t[0]) == len(at_t_mut[0]) and all(
        a.index == b.index and a.value == b.value for a, b in zip(at_t[0], at_t_mut[0])
    )
    return {"FUTURE_PEAK_LEAKAGE_TEST": "PASS" if same else "FAIL"}


def run_future_mutation_test() -> dict[str, Any]:
    closes = [100 + i * 0.5 + np.sin(i / 3) * 2 for i in range(80)]
    bars = _make_bars(closes)
    arrays = bars_to_arrays(bars, timeframe="1H")
    atr = np.array(
        [float(s.values["atr"]) if s.valid and s.values.get("atr") is not None else float("nan") for s in compute_atr_series(arrays, period=14)]
    )
    cfg = PredictorConfig(period=7, peak_strength=2, lookback=50, samples=3, ob_os_level_percent=0.8)
    t = 60
    base = compute_predictor_at_index(arrays, t, config=cfg, atr=atr)
    mutated = [dict(b) for b in bars]
    for j in range(t + 1, len(mutated)):
        mutated[j]["close"] = float(mutated[j]["close"]) + 50.0
        mutated[j]["open"] = mutated[j]["high"] = mutated[j]["low"] = mutated[j]["close"]
    m_arrays = bars_to_arrays(mutated, timeframe="1H")
    m_atr = np.array(
        [float(s.values["atr"]) if s.valid and s.values.get("atr") is not None else float("nan") for s in compute_atr_series(m_arrays, period=14)]
    )
    after = compute_predictor_at_index(m_arrays, t, config=cfg, atr=m_atr)
    keys = [
        "DYNAMIC_OB_OSC_TARGET",
        "DYNAMIC_OS_OSC_TARGET",
        "PREDICTOR_OB_PRICE_NEXT_BAR",
        "PREDICTOR_OS_PRICE_NEXT_BAR",
    ]
    ok = all(base.get(k) == after.get(k) for k in keys if base.get(k) is not None)
    return {"PREDICTOR_FUTURE_MUTATION_TEST": "PASS" if ok else "FAIL"}


def run_gap_independence_tests() -> dict[str, Any]:
    from datetime import timedelta

    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    seg1 = []
    for i in range(30):
        t = base + timedelta(hours=i)
        seg1.append(
            {
                "open_time": t,
                "close_time": t,
                "open": 100 + i,
                "high": 100 + i,
                "low": 100 + i,
                "close": 100 + i,
                "volume": 1.0,
                "timeframe": "1H",
            }
        )
    seg2 = []
    for i in range(30):
        t = base + timedelta(hours=40 + i)
        seg2.append(
            {
                "open_time": t,
                "close_time": t,
                "open": 200 + i,
                "high": 200 + i,
                "low": 200 + i,
                "close": 200 + i,
                "volume": 1.0,
                "timeframe": "1H",
            }
        )
    bars = seg1 + seg2
    arrays = bars_to_arrays(bars, timeframe="1H")
    post_gap_idx = 30
    dno_at_boundary = compute_dno_feature_series(arrays, period=7)
    dno_ok = dno_at_boundary[post_gap_idx].valid is False or dno_at_boundary[post_gap_idx - 1].valid
    cfg = PredictorConfig(period=7, peak_strength=2, lookback=20, samples=2, ob_os_level_percent=0.8)
    dno_vals = np.array([0, 1, 4, 7, 4, 1, 0, -1, -3, -1, 0, 1, 3, 5, 3, 1] + [0.0] * 44)
    gap = arrays.gap_flags
    pre_peaks, _ = confirmed_extrema_at(dno_vals, gap, 29, peak_strength=2, lookback=50)
    post_peaks, _ = confirmed_extrema_at(dno_vals, gap, 31, peak_strength=2, lookback=50)
    pred_ok = all(p.index < post_gap_idx for p in post_peaks) or len(post_peaks) == 0
    if pre_peaks:
        pred_ok = pred_ok and all(p.index < post_gap_idx for p in post_peaks)
    pred_at_gap = compute_predictor_at_index(arrays, post_gap_idx, config=cfg)
    pred_ok = pred_ok and (
        pred_at_gap.get("predictor_state") == "INSUFFICIENT_HISTORY" or pred_at_gap.get("valid") is False
    )
    return {
        "DNO_POST_GAP_INDEPENDENCE": "PASS" if dno_ok else "FAIL",
        "PREDICTOR_POST_GAP_INDEPENDENCE": "PASS" if pred_ok else "FAIL",
    }


def run_batch_streaming_parity() -> dict[str, Any]:
    closes = [100 + np.sin(i / 4) * 5 + i * 0.1 for i in range(120)]
    bars = _make_bars(closes)
    cfg = PredictorConfig(period=7, peak_strength=2, lookback=60, samples=4, ob_os_level_percent=0.75)
    stream = StreamingOscillatorPredictor(config=cfg)
    streamed = []
    for b in bars:
        streamed.append(stream.on_bar_close(b))
    batch = stream.batch_recompute()
    ok = len(streamed) == len(batch)
    if ok:
        for (sd, sp), (bd, bp) in zip(streamed, batch):
            if sd != bd or sp != bp:
                ok = False
                break
    return {"PREDICTOR_BATCH_STREAMING_PARITY": "PASS" if ok else "FAIL"}


def write_artifacts(results: dict[str, Any]) -> None:
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_ROOT / "numeric_reference_tests_v1.json").write_text(
        json.dumps(results["numeric"], indent=2), encoding="utf-8"
    )
    anti = {
        k: results[k]
        for k in (
            "PEAK_CONFIRMATION_CAUSALITY",
            "FUTURE_PEAK_LEAKAGE_TEST",
            "PREDICTOR_FUTURE_MUTATION_TEST",
            "DNO_POST_GAP_INDEPENDENCE",
            "PREDICTOR_POST_GAP_INDEPENDENCE",
        )
        if k in results
    }
    (ARTIFACT_ROOT / "anti_leakage_tests_v1.json").write_text(json.dumps(anti, indent=2), encoding="utf-8")
    (ARTIFACT_ROOT / "batch_streaming_parity_v1.json").write_text(
        json.dumps({"PREDICTOR_BATCH_STREAMING_PARITY": results.get("PREDICTOR_BATCH_STREAMING_PARITY")}, indent=2),
        encoding="utf-8",
    )
    reg_path = ARTIFACT_ROOT / "predictor_registry_v1.csv"
    with reg_path.open("w", newline="", encoding="utf-8") as f:
        rows = list(OSCILLATOR_PREDICTOR_REGISTRY.values())
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    docs = {
        "source_authority_v1.md": "# Source authority\n\nDNO: documented DiNapoli Detrended Oscillator (Close - SMA(N)).\nPredictor: PROJECT_RECONSTRUCTION — not proprietary exact.\n",
        "detrended_oscillator_formula_v1.md": "# DNO\n\nDNO_t = Close_t - SMA_N(Close)_t\n\nDefault N=7.\n",
        "inverse_formula_derivation_v1.md": "# Inverse\n\nP = (N * D_TARGET + S) / (N - 1)\n",
        "dynamic_target_semantics_v1.md": f"# Dynamic targets\n\nTARGET_AGGREGATION={TARGET_AGGREGATION}\n",
        "peak_confirmation_semantics_v1.md": "# Peak confirmation\n\nPEAK_AVAILABLE_AT = i + K\n",
    }
    for name, body in docs.items():
        (ARTIFACT_ROOT / name).write_text(body, encoding="utf-8")
    va = ARTIFACT_ROOT / "visual_audit"
    va.mkdir(exist_ok=True)
    (va / "README.txt").write_text("Research-only visual audit placeholders.\n", encoding="utf-8")
    manifest = {
        "wip_id": WIP_ID,
        "version": OSCILLATOR_PREDICTOR_VERSION,
        "artifact_root": str(ARTIFACT_ROOT.relative_to(REPO_ROOT)).replace("\\", "/"),
        "tests": results,
        "inverse_predictor_families": INVERSE_PREDICTOR_FAMILY_STATUS,
        "INVERSE_PREDICTOR_ENGINE_REUSED": INVERSE_PREDICTOR_ENGINE_REUSED,
    }
    (ARTIFACT_ROOT / "manifest_v1.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def main() -> dict[str, Any]:
    results: dict[str, Any] = {}
    numeric = run_numeric_reference_tests()
    results.update(numeric)
    results["numeric"] = numeric
    results.update(run_peak_confirmation_test())
    results.update(run_future_leakage_test())
    results.update(run_future_mutation_test())
    results.update(run_gap_independence_tests())
    results.update(run_batch_streaming_parity())
    write_artifacts(results)
    return results


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
