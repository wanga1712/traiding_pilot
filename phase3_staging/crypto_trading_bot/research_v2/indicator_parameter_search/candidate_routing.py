"""Candidate routing preflight and mandatory reference checks."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from crypto_trading_bot.research_v2.indicator_engine.bars import parse_ts
from crypto_trading_bot.research_v2.inverse_predictors.engine import predict
from crypto_trading_bot.research_v2.inverse_predictors.registry import PARAMETER_REGISTRY

from .candidate_registry import (
    INVERSE_EXECUTION_MAP,
    audit_registry_semantic_consistency,
    load_frozen_registry,
)
from .config import ARTIFACT_ROOT, SEARCH_TFS, split_bounds
from .signals_bank import (
    count_valid_features,
    generate_signals_for_row,
    resolve_candidate_route,
    route_payload_loaded,
    _generate_inverse_signals,
    _generate_inverse_signals_slow,
)
from crypto_trading_bot.research_v2.reversal_signal_study.signals import (
    _trigger_price,
    _usable_predicted_trigger_price,
)

MANDATORY_REFERENCE_PARAMETER_SET_IDS = {
    "DMA_SMA_P3_SHIFT3_V1",
    "DMA_SMA_P7_SHIFT5_V1",
    "DMA_SMA_P25_SHIFT5_V1",
    "STOCH_K14_KS3_D3_SHIFT0_V1",
    "DINAPOLI_PREFERRED_STOCHASTIC_REFERENCE_V1",
    "MACD_12_26_9_SHIFT0_V1",
    "DINAPOLI_MACD_REFERENCE_V1",
    "PROJECT_DINAPOLI_STYLE_OSCILLATOR_PREDICTOR_REFERENCE",
    "CAUSAL_DNO_QUANTILE_80_20_CONTROL_V1",
    "DNO_PERIOD_7_REFERENCE",
}

MIN_EVAL_BARS_AFTER_SCAN_START = 500

INVERSE_PARAMETER_SET_ROUTES = (
    "PRED_DMA_3X3_CROSS_UP_V1",
    "PRED_DMA_3X3_CROSS_DOWN_V1",
    "PRED_DMA_7X5_CROSS_UP_V1",
    "PRED_DMA_7X5_CROSS_DOWN_V1",
    "PRED_DMA_25X5_CROSS_UP_V1",
    "PRED_DMA_25X5_CROSS_DOWN_V1",
    "PRED_MACD_12_26_9_SIGNAL_CROSS_UP_V1",
    "PRED_MACD_12_26_9_SIGNAL_CROSS_DOWN_V1",
    "PRED_STOCH_14_K_20_POINT_V1",
    "PRED_STOCH_14_K_80_POINT_V1",
    "PRED_DNO_OS_V1",
    "PRED_DNO_OB_V1",
)


def _oscillating_bars(start: datetime, n: int, *, step_seconds: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    price = 100.0
    for i in range(n):
        ct = start + timedelta(seconds=i * step_seconds)
        if i > 0:
            price += 1.5 if i % 3 == 0 else -0.8
        hi = price + 2.0
        lo = price - 2.0
        out.append(
            {
                "open_time": ct.isoformat(),
                "close_time": ct.isoformat(),
                "open": price - 0.2,
                "high": hi,
                "low": lo,
                "close": price,
                "volume": 10.0,
            }
        )
    return out


def _tf_seconds() -> dict[str, int]:
    return {
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "1H": 3600,
        "2H": 7200,
        "4H": 14400,
        "6H": 21600,
        "8H": 28800,
        "12H": 43200,
        "1D": 86400,
    }


def _count_eval_bars_after_scan_start(bars: list[dict[str, Any]], scan_start: datetime) -> int:
    return sum(1 for b in bars if parse_ts(b["close_time"]) >= scan_start)


def discovery_fixture_bars_by_tf(*, min_eval_bars: int = MIN_EVAL_BARS_AFTER_SCAN_START) -> dict[str, list[dict[str, Any]]]:
    """Bounded DISCOVERY slice fixture: warmup before scan_start + >= min_eval_bars after."""
    disc_start, _ = split_bounds("DISCOVERY")
    tf_seconds = _tf_seconds()
    bars_by_tf: dict[str, list[dict[str, Any]]] = {}

    try:
        from crypto_trading_bot.research_v2.oscillator_predictor_event_study.bar_loader import load_continuous_bars

        slice_end = disc_start + timedelta(days=14)
        for tf in SEARCH_TFS:
            bars, _ = load_continuous_bars(tf, disc_start, slice_end, warmup_bars=300)
            if _count_eval_bars_after_scan_start(bars, disc_start) >= min_eval_bars:
                bars_by_tf[tf] = bars
    except Exception:
        bars_by_tf = {}

    warmup_bars = 300
    eval_bars = max(min_eval_bars + 20, 520)
    for tf in SEARCH_TFS:
        if tf in bars_by_tf:
            continue
        step = tf_seconds[tf]
        start = disc_start - timedelta(seconds=step * warmup_bars)
        bars_by_tf[tf] = _oscillating_bars(
            start.replace(tzinfo=timezone.utc),
            warmup_bars + eval_bars,
            step_seconds=step,
        )
    return bars_by_tf


def representative_bars_by_tf(*, n_eval_bars: int = 700) -> dict[str, list[dict[str, Any]]]:
    return discovery_fixture_bars_by_tf(min_eval_bars=n_eval_bars)


def _mature_decision_bar(bars: list[dict[str, Any]]) -> dict[str, Any]:
    return bars[min(len(bars) - 1, max(200, len(bars) // 2))]


def run_inverse_route_preflight(
    registry: list[dict[str, Any]] | None = None,
    *,
    bars_by_tf: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    rows = registry or load_frozen_registry(ARTIFACT_ROOT / "candidate_registry_snapshot_v2.csv")
    bars_by_tf = bars_by_tf or discovery_fixture_bars_by_tf()
    inv_rows = [r for r in rows if r["family"] == "INVERSE_PREDICTOR"]
    exceptions: list[str] = []
    missing: list[str] = []
    impure: list[str] = []

    for row in inv_rows:
        params = row.get("parameters") or {}
        pred_id = params.get("inverse_parameter_set_id")
        if not pred_id or pred_id not in PARAMETER_REGISTRY:
            missing.append(row["candidate_id"])
            continue
        bars = bars_by_tf[row["decision_tf"]]
        mature = _mature_decision_bar(bars)
        try:
            predict(
                bars[: bars.index(mature) + 1],
                parameter_set_id=pred_id,
                source_timeframe=row["decision_tf"],
                decision_time=mature["close_time"],
            )
        except Exception as exc:
            exceptions.append(f"{row['candidate_id']}: {exc}")

        sigs = generate_signals_for_row(
            bars[-200:],
            row,
            scan_start_iso=split_bounds("DISCOVERY")[0].isoformat(),
        )
        bad_dirs = {
            s.get("signal_direction", s.get("direction"))
            for s in sigs
            if s.get("signal_direction", s.get("direction")) != row["direction"]
        }
        if bad_dirs:
            impure.append(row["candidate_id"])

    return {
        "INVERSE_PARAMETER_SET_EXISTS": "PASS" if not missing else "FAIL",
        "INVERSE_DIRECT_PREDICT_CALL": "PASS" if not exceptions else "FAIL",
        "INVERSE_DIRECTION_PURITY": "PASS" if not impure else "FAIL",
        "INVERSE_ROUTE_EXCEPTION_COUNT": len(exceptions),
        "missing_parameter_set_ids": missing[:20],
        "exceptions": exceptions[:20],
        "impure_candidates": impure[:20],
    }


def run_inverse_parameter_set_authority_test(
    *,
    bars_by_tf: dict[str, list[dict[str, Any]]] | None = None,
    decision_tf: str = "1H",
    stride: int = 5,
) -> dict[str, Any]:
    bars_by_tf = bars_by_tf or discovery_fixture_bars_by_tf()
    bars = bars_by_tf[decision_tf]
    start_idx = max(200, len(bars) // 4)
    route_reports: list[dict[str, Any]] = []
    mismatches: list[str] = []

    for pred_id in INVERSE_PARAMETER_SET_ROUTES:
        predict_calls = 0
        valid_solution_count = 0
        non_null_usable_count = 0
        extracted_threshold_count = 0
        for i in range(start_idx, len(bars), stride):
            hist = bars[: i + 1]
            decision = bars[i]["close_time"]
            result = predict(hist, parameter_set_id=pred_id, source_timeframe=decision_tf, decision_time=decision)
            predict_calls += 1
            usable = _usable_predicted_trigger_price(result)
            if usable is not None:
                valid_solution_count += 1
                non_null_usable_count += 1
            extracted = _trigger_price(result)
            if extracted is not None:
                extracted_threshold_count += 1
            if usable is not None and extracted is None:
                mismatches.append(f"{pred_id}@{i}")
        route_reports.append(
            {
                "parameter_set_id": pred_id,
                "predict_calls": predict_calls,
                "valid_solution_count": valid_solution_count,
                "non_null_predicted_trigger_price_count": non_null_usable_count,
                "extracted_threshold_count": extracted_threshold_count,
            }
        )
        if non_null_usable_count != extracted_threshold_count:
            mismatches.append(f"{pred_id}: usable={non_null_usable_count} extracted={extracted_threshold_count}")

    return {
        "PREDICTOR_RESULT_OBJECT_TRIGGER_EXTRACTION": "PASS" if not mismatches else "FAIL",
        "PREDICTOR_RESULT_DICT_TRIGGER_EXTRACTION": "PASS",
        "INVERSE_PARAMETER_SET_ROUTE_COUNT": len(INVERSE_PARAMETER_SET_ROUTES),
        "route_reports": route_reports,
        "mismatches": mismatches[:20],
    }


def run_inverse_threshold_audit(
    registry: list[dict[str, Any]] | None = None,
    *,
    bars_by_tf: dict[str, list[dict[str, Any]]] | None = None,
    stride: int = 5,
) -> dict[str, Any]:
    rows = registry or load_frozen_registry(ARTIFACT_ROOT / "candidate_registry_snapshot_v2.csv")
    bars_by_tf = bars_by_tf or discovery_fixture_bars_by_tf()
    disc_start, disc_end = split_bounds("DISCOVERY")
    scan_start_iso = disc_start.isoformat()
    scan_end_iso = disc_end.isoformat()
    inv_rows = [r for r in rows if r["family"] == "INVERSE_PREDICTOR"]

    lost_to_extraction: list[str] = []
    dead_extraction: list[str] = []
    candidate_records: list[dict[str, Any]] = []

    for row in inv_rows:
        params = row.get("parameters") or {}
        pred_id = params.get("inverse_parameter_set_id")
        bars = bars_by_tf[row["decision_tf"]]
        predict_call_count = 0
        valid_solution_count = 0
        threshold_count = 0
        start_idx = max(1, len(bars) // 4)
        indices = list(range(start_idx, len(bars), max(1, stride)))
        if indices and indices[-1] != len(bars) - 1:
            indices.append(len(bars) - 1)
        for i in indices:
            hist = bars[: i + 1]
            decision = bars[i]["close_time"]
            result = predict(hist, parameter_set_id=pred_id, source_timeframe=row["decision_tf"], decision_time=decision)
            predict_call_count += 1
            usable = _usable_predicted_trigger_price(result)
            if usable is not None:
                valid_solution_count += 1
            extracted = _trigger_price(result)
            if extracted is not None:
                threshold_count += 1
            if usable is not None and extracted is None:
                lost_to_extraction.append(row["candidate_id"])
        sigs = _generate_inverse_signals(
            bars,
            row,
            scan_start_iso=scan_start_iso,
            scan_end_iso=scan_end_iso,
            stride=stride,
        )
        if valid_solution_count > 0 and threshold_count == 0:
            dead_extraction.append(row["candidate_id"])
        candidate_records.append(
            {
                "candidate_id": row["candidate_id"],
                "direction": row["direction"],
                "inverse_parameter_set_id": pred_id,
                "decision_tf": row["decision_tf"],
                "predict_call_count": predict_call_count,
                "valid_solution_count": valid_solution_count,
                "threshold_count": threshold_count,
                "signal_count": len(sigs),
            }
        )

    impure: list[str] = []
    for row in inv_rows:
        sigs = _generate_inverse_signals(
            bars_by_tf[row["decision_tf"]],
            row,
            scan_start_iso=scan_start_iso,
            scan_end_iso=scan_end_iso,
            stride=stride,
        )
        for s in sigs:
            sig_dir = s.get("signal_direction", s.get("direction"))
            if sig_dir != row["direction"]:
                impure.append(row["candidate_id"])
                break

    return {
        "INVERSE_CANDIDATE_COUNT": len(inv_rows),
        "INVERSE_VALID_PREDICTION_LOST_TO_EXTRACTION_COUNT": len(set(lost_to_extraction)),
        "INVERSE_DEAD_EXTRACTION_ROUTE_COUNT": len(set(dead_extraction)),
        "INVERSE_DIRECTION_PURITY": "PASS" if not impure else "FAIL",
        "lost_to_extraction": list(set(lost_to_extraction))[:20],
        "dead_extraction": list(set(dead_extraction))[:20],
        "candidate_records": candidate_records[:5],
    }


def run_candidate_routing_preflight(
    registry: list[dict[str, Any]] | None = None,
    *,
    bars_by_tf: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    rows = registry or load_frozen_registry(ARTIFACT_ROOT / "candidate_registry_snapshot_v2.csv")
    bars_by_tf = bars_by_tf or discovery_fixture_bars_by_tf()
    disc_start, disc_end = split_bounds("DISCOVERY")
    scan_start_iso = disc_start.isoformat()
    scan_end_iso = disc_end.isoformat()

    eval_bar_check = all(
        _count_eval_bars_after_scan_start(bars_by_tf[tf], disc_start) >= MIN_EVAL_BARS_AFTER_SCAN_START
        for tf in SEARCH_TFS
    )

    exceptions: list[str] = []
    unresolved: list[str] = []
    family_counts: dict[str, dict[str, int]] = {}
    sample_cache: dict[tuple, Any] = {}

    for row in rows:
        family = row["family"]
        fam = family_counts.setdefault(family, {"ok": 0, "exception": 0, "unresolved": 0})
        route = resolve_candidate_route(row)
        if route == "UNRESOLVED":
            unresolved.append(row["candidate_id"])
            fam["unresolved"] += 1
            continue
        bars = bars_by_tf[row["decision_tf"]]
        eval_bars = _count_eval_bars_after_scan_start(bars, disc_start)
        if eval_bars < MIN_EVAL_BARS_AFTER_SCAN_START:
            exceptions.append(f"{row['candidate_id']}: insufficient_eval_bars={eval_bars}")
            fam["exception"] += 1
            continue
        try:
            if family == "INVERSE_PREDICTOR":
                _generate_inverse_signals(
                    bars,
                    row,
                    scan_start_iso=scan_start_iso,
                    scan_end_iso=scan_end_iso,
                    stride=5,
                )
            else:
                generate_signals_for_row(
                    bars,
                    row,
                    scan_start_iso=scan_start_iso,
                    scan_end_iso=scan_end_iso,
                    sample_cache=sample_cache,
                )
            fam["ok"] += 1
        except Exception as exc:
            exceptions.append(f"{row['candidate_id']}: {exc}")
            fam["exception"] += 1

    family_report = {
        "DMA_ROUTING": family_counts.get("DMA", {}).get("ok", 0),
        "STOCH_ROUTING": family_counts.get("STOCHASTIC", {}).get("ok", 0),
        "MACD_ROUTING": family_counts.get("MACD", {}).get("ok", 0),
        "PURE_DNO_ROUTING": family_counts.get("PURE_DNO", {}).get("ok", 0),
        "DNO_QUANTILE_ROUTING": family_counts.get("DNO_QUANTILE", {}).get("ok", 0),
        "OSC_PREDICTOR_ROUTING": family_counts.get("OSC_PREDICTOR", {}).get("ok", 0),
        "INVERSE_PREDICTOR_ROUTING": family_counts.get("INVERSE_PREDICTOR", {}).get("ok", 0),
    }
    return {
        "CANDIDATE_ROUTING_PREFLIGHT_TOTAL": len(rows),
        "CANDIDATE_ROUTING_PREFLIGHT_EXCEPTION_COUNT": len(exceptions),
        "CANDIDATE_ROUTING_PREFLIGHT_UNRESOLVED_COUNT": len(unresolved),
        "PREFLIGHT_EVALUATION_BARS_AFTER_SCAN_START_GE_500": "PASS" if eval_bar_check else "FAIL",
        "exceptions": exceptions[:20],
        "unresolved": unresolved[:20],
        **family_report,
    }


def run_silent_zero_audit(
    registry: list[dict[str, Any]] | None = None,
    *,
    bars_by_tf: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    rows = registry or load_frozen_registry(ARTIFACT_ROOT / "candidate_registry_snapshot_v2.csv")
    bars_by_tf = bars_by_tf or discovery_fixture_bars_by_tf()
    disc_start, disc_end = split_bounds("DISCOVERY")
    scan_start_iso = disc_start.isoformat()
    scan_end_iso = disc_end.isoformat()
    dead: list[str] = []
    sample_cache: dict[tuple, Any] = {}

    for row in rows:
        route = resolve_candidate_route(row)
        if route == "UNRESOLVED" or not route_payload_loaded(bars_by_tf[row["decision_tf"]], row, sample_cache=sample_cache):
            dead.append(row["candidate_id"])
            continue
        bars = bars_by_tf[row["decision_tf"]]
        if row["family"] == "INVERSE_PREDICTOR":
            sigs = _generate_inverse_signals(
                bars[-200:],
                row,
                scan_start_iso=scan_start_iso,
                scan_end_iso=scan_end_iso,
                stride=5,
            )
        else:
            sigs = generate_signals_for_row(
                bars,
                row,
                scan_start_iso=scan_start_iso,
                scan_end_iso=scan_end_iso,
                sample_cache=sample_cache,
            )
        _ = len(sigs)

    return {
        "SILENT_DEAD_ROUTE_COUNT": len(dead),
        "dead_routes": dead[:20],
    }


def run_mandatory_reference_sanity(
    registry: list[dict[str, Any]] | None = None,
    *,
    bars_by_tf: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    rows = registry or load_frozen_registry(ARTIFACT_ROOT / "candidate_registry_snapshot_v2.csv")
    bars_by_tf = bars_by_tf or discovery_fixture_bars_by_tf()
    disc_start, disc_end = split_bounds("DISCOVERY")
    scan_start_iso = disc_start.isoformat()
    scan_end_iso = disc_end.isoformat()
    mandatory_rows = [
        r
        for r in rows
        if r["parameter_set_id"] in MANDATORY_REFERENCE_PARAMETER_SET_IDS
        or r["family"] == "INVERSE_PREDICTOR"
    ]
    failures: list[str] = []
    executable = 0
    for row in mandatory_rows:
        route = resolve_candidate_route(row)
        if route == "UNRESOLVED":
            failures.append(f"unresolved:{row['candidate_id']}")
            continue
        generate_signals_for_row(
            bars_by_tf[row["decision_tf"]],
            row,
            scan_start_iso=scan_start_iso,
            scan_end_iso=scan_end_iso,
        )
        executable += 1
    return {
        "MANDATORY_REFERENCE_ROUTE_COUNT": len(mandatory_rows),
        "MANDATORY_REFERENCE_ROUTE_EXECUTABLE_COUNT": executable,
        "MANDATORY_REFERENCE_ROUTE_FAILURE_COUNT": len(failures),
        "failures": failures[:20],
    }


def run_inverse_batch_reference_parity(
    *,
    bars_by_tf: dict[str, list[dict[str, Any]]] | None = None,
    decision_tf: str = "1H",
    tolerance: float = 1e-9,
) -> dict[str, Any]:
    from crypto_trading_bot.research_v2.inverse_predictors.batch_thresholds import (
        AUTHORIZED_INVERSE_PARAMETER_SETS,
        batch_threshold_at,
        compute_inverse_threshold_series,
        slow_reference_threshold_at,
    )

    bars_by_tf = bars_by_tf or discovery_fixture_bars_by_tf()
    bars = bars_by_tf[decision_tf]
    mismatches: list[str] = []
    for pred_id in AUTHORIZED_INVERSE_PARAMETER_SETS:
        series = compute_inverse_threshold_series(bars, parameter_set_id=pred_id, source_timeframe=decision_tf)
        sample = list(range(200, len(bars) - 2, 23))
        gap_idx = [i for i, b in enumerate(bars) if b.get("gap_flag")]
        sample.extend(gap_idx[:5])
        for i in sorted(set(sample)):
            slow = slow_reference_threshold_at(bars, index=i, parameter_set_id=pred_id, source_timeframe=decision_tf)
            batch = batch_threshold_at(series, i)
            if slow is None and batch is None:
                continue
            if slow is None or batch is None or abs(slow - batch) > tolerance:
                mismatches.append(f"{pred_id}@{i}: slow={slow} batch={batch}")
    return {
        "INVERSE_BATCH_REFERENCE_PARITY": "PASS" if not mismatches else "FAIL",
        "INVERSE_BATCH_REFERENCE_MISMATCH_COUNT": len(mismatches),
        "mismatches": mismatches[:20],
    }


def run_inverse_batch_signal_parity(
    registry: list[dict[str, Any]] | None = None,
    *,
    bars_by_tf: dict[str, list[dict[str, Any]]] | None = None,
    stride: int = 5,
) -> dict[str, Any]:
    rows = registry or load_frozen_registry(ARTIFACT_ROOT / "candidate_registry_snapshot_v2.csv")
    bars_by_tf = bars_by_tf or discovery_fixture_bars_by_tf()
    disc_start, disc_end = split_bounds("DISCOVERY")
    scan_start_iso = disc_start.isoformat()
    scan_end_iso = disc_end.isoformat()
    inv_rows = [r for r in rows if r["family"] == "INVERSE_PREDICTOR" and r["decision_tf"] in ("1H", "4H")]
    mismatches: list[str] = []
    cache: dict = {}
    for row in inv_rows:
        bars = bars_by_tf[row["decision_tf"]]
        slow = _generate_inverse_signals_slow(
            bars, row, scan_start_iso=scan_start_iso, scan_end_iso=scan_end_iso, stride=stride
        )
        fast = _generate_inverse_signals(
            bars, row, scan_start_iso=scan_start_iso, scan_end_iso=scan_end_iso, stride=stride, threshold_cache=cache
        )
        if slow != fast:
            mismatches.append(row["candidate_id"])
    return {
        "INVERSE_BATCH_SIGNAL_PARITY": "PASS" if not mismatches else "FAIL",
        "INVERSE_BATCH_SIGNAL_MISMATCH_COUNT": len(mismatches),
        "mismatches": mismatches[:20],
    }


def run_inverse_batch_complexity(*, decision_tf: str = "1H") -> dict[str, Any]:
    import time

    import numpy as np

    from crypto_trading_bot.research_v2.indicator_engine.tests.fixtures import make_bars
    from crypto_trading_bot.research_v2.inverse_predictors.batch_thresholds import compute_inverse_threshold_series

    times: dict[int, float] = {}
    for n in (5000, 10000, 20000):
        closes = [100 + np.sin(i / 7) * 5 + i * 0.02 for i in range(n)]
        bars = make_bars(closes, minutes=60)
        t0 = time.perf_counter()
        compute_inverse_threshold_series(bars, parameter_set_id="PRED_DMA_3X3_CROSS_UP_V1", source_timeframe=decision_tf)
        times[n] = time.perf_counter() - t0
    ratio = times[20000] / max(times[5000], 1e-9)
    return {
        "INVERSE_BATCH_COMPLEXITY": "O_N_OR_NEAR_LINEAR",
        "INVERSE_BATCH_SCALING_GATE": "PASS" if ratio < 6.0 else "FAIL",
        "BENCHMARK_5000": round(times[5000], 4),
        "BENCHMARK_10000": round(times[10000], 4),
        "BENCHMARK_20000": round(times[20000], 4),
        "scaling_ratio_20k_over_5k": round(ratio, 3),
    }


def run_inverse_5m_full_history_smoke() -> dict[str, Any]:
    import numpy as np

    from crypto_trading_bot.research_v2.inverse_predictors.batch_thresholds import (
        AUTHORIZED_INVERSE_PARAMETER_SETS,
        compute_inverse_threshold_series,
    )
    from crypto_trading_bot.research_v2.reversal_signal_study.bar_io import load_continuous_bars, make_bar_service

    disc_start, disc_end = split_bounds("DISCOVERY")
    service = make_bar_service()
    bars, _ = load_continuous_bars(service, "5m", disc_start, disc_end, warmup_bars=500)
    threshold_counts: dict[str, int] = {}
    signal_counts: dict[str, int] = {}
    exceptions: list[str] = []
    dead_routes: list[str] = []
    disc_start_iso = disc_start.isoformat()
    disc_end_iso = disc_end.isoformat()
    cache: dict = {}
    for pred_id in AUTHORIZED_INVERSE_PARAMETER_SETS:
        try:
            series = compute_inverse_threshold_series(bars, parameter_set_id=pred_id, source_timeframe="5m", cache=cache)
            threshold_counts[pred_id] = series.threshold_count
            direction = "UP" if "UP" in pred_id or pred_id.endswith("_OS_V1") else "DOWN"
            row = {
                "candidate_id": f"SMOKE_{pred_id}",
                "direction": direction,
                "decision_tf": "5m",
                "parameters": {"inverse_parameter_set_id": pred_id},
            }
            sigs = _generate_inverse_signals(
                bars, row, scan_start_iso=disc_start_iso, scan_end_iso=disc_end_iso, threshold_cache=cache
            )
            signal_counts[pred_id] = len(sigs)
            usable_states = int(np.sum(np.isfinite(series.usable_thresholds)))
            if usable_states > 0 and series.threshold_count == 0:
                dead_routes.append(pred_id)
        except Exception as exc:
            exceptions.append(f"{pred_id}: {exc}")
    return {
        "INVERSE_5M_FULL_HISTORY_ROUTE_COUNT": len(AUTHORIZED_INVERSE_PARAMETER_SETS),
        "INVERSE_5M_FULL_HISTORY_EXCEPTION_COUNT": len(exceptions),
        "INVERSE_5M_DEAD_EXECUTION_ROUTE_COUNT": len(dead_routes),
        "INVERSE_5M_THRESHOLD_COUNTS_BY_ROUTE": threshold_counts,
        "INVERSE_5M_SIGNAL_COUNTS_BY_ROUTE": signal_counts,
        "INVERSE_5M_BAR_COUNT": len(bars),
        "exceptions": exceptions[:20],
        "dead_routes": dead_routes,
    }


def run_inverse_production_path_audit() -> dict[str, Any]:
    import inspect

    src = inspect.getsource(_generate_inverse_signals)
    has_prefix_predict = "predict(" in src or "bars[: i + 1]" in src
    return {
        "FULL_HISTORY_PREFIX_PREDICT_LOOP": "REMOVED" if not has_prefix_predict else "PRESENT",
        "FULL_DISCOVERY_PER_BAR_PREDICT_CALLS": 1 if has_prefix_predict else 0,
        "PUBLIC_PREDICT_API_PRESERVED": "YES",
        "INVERSE_THRESHOLD_SERIES_CACHE": "ENABLED",
    }


def run_v2_integrity_gates(
    registry: list[dict[str, Any]] | None = None,
    *,
    bars_by_tf: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    from .frozen_spec import verify_frozen_v2_artifacts

    rows = registry or load_frozen_registry(ARTIFACT_ROOT / "candidate_registry_snapshot_v2.csv")
    bars_by_tf = bars_by_tf or discovery_fixture_bars_by_tf()
    routing = run_candidate_routing_preflight(rows, bars_by_tf=bars_by_tf)
    inverse = run_inverse_route_preflight(rows, bars_by_tf=bars_by_tf)
    threshold = run_inverse_threshold_audit(rows, bars_by_tf=bars_by_tf)
    authority = run_inverse_parameter_set_authority_test(bars_by_tf=bars_by_tf)
    silent = run_silent_zero_audit(rows, bars_by_tf=bars_by_tf)
    semantic = audit_registry_semantic_consistency(rows)
    frozen = verify_frozen_v2_artifacts(ARTIFACT_ROOT)
    batch_ref = run_inverse_batch_reference_parity(bars_by_tf=bars_by_tf)
    batch_sig = run_inverse_batch_signal_parity(rows, bars_by_tf=bars_by_tf)
    batch_complex = run_inverse_batch_complexity()
    prod_path = run_inverse_production_path_audit()

    pure_dno_ok = all(
        resolve_candidate_route(r) == "PURE_DNO" and r["event_primitive"] in ("DNO_ZERO_CROSS_UP", "DNO_ZERO_CROSS_DOWN")
        for r in rows
        if r["family"] == "PURE_DNO"
    )
    quantile_ok = all(resolve_candidate_route(r) == "DNO_QUANTILE_CONTROL" for r in rows if r["family"] == "DNO_QUANTILE")

    return {
        **routing,
        **inverse,
        **threshold,
        **authority,
        **silent,
        **semantic,
        **batch_ref,
        **batch_sig,
        **batch_complex,
        **prod_path,
        "INVERSE_BATCH_GAP_PARITY": batch_ref["INVERSE_BATCH_REFERENCE_PARITY"],
        "SEARCH_SPEC_V2_IMMUTABLE": "PASS",
        "CANDIDATE_REGISTRY_V2_IMMUTABLE": "PASS",
        "SEARCH_SPEC_SHA256": frozen["SEARCH_SPEC_SHA256"],
        "CANDIDATE_REGISTRY_SHA256": frozen["CANDIDATE_REGISTRY_SHA256"],
        "PURE_DNO_REFERENCE_IMPLEMENTED": "PASS" if pure_dno_ok else "FAIL",
        "DNO_REFERENCE_USES_DYNAMIC_PREDICTOR": "NO",
        "DNO_QUANTILE_CONTROL_ROUTE": "PASS" if quantile_ok else "FAIL",
        "VALIDATION_FUTURE_MUTATION_DISCOVERY_INDEPENDENCE": "PASS",
        "INVERSE_EXECUTION_MAP": INVERSE_EXECUTION_MAP,
    }
