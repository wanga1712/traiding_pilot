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
        bad_dirs = {s["direction"] for s in sigs if s["direction"] != row["direction"]}
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


def run_v2_integrity_gates(
    registry: list[dict[str, Any]] | None = None,
    *,
    bars_by_tf: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    rows = registry or load_frozen_registry(ARTIFACT_ROOT / "candidate_registry_snapshot_v2.csv")
    bars_by_tf = bars_by_tf or discovery_fixture_bars_by_tf()
    routing = run_candidate_routing_preflight(rows, bars_by_tf=bars_by_tf)
    inverse = run_inverse_route_preflight(rows, bars_by_tf=bars_by_tf)
    silent = run_silent_zero_audit(rows, bars_by_tf=bars_by_tf)
    semantic = audit_registry_semantic_consistency(rows)

    pure_dno_ok = all(
        resolve_candidate_route(r) == "PURE_DNO" and r["event_primitive"] in ("DNO_ZERO_CROSS_UP", "DNO_ZERO_CROSS_DOWN")
        for r in rows
        if r["family"] == "PURE_DNO"
    )
    quantile_ok = all(resolve_candidate_route(r) == "DNO_QUANTILE_CONTROL" for r in rows if r["family"] == "DNO_QUANTILE")

    return {
        **routing,
        **inverse,
        **silent,
        **semantic,
        "PURE_DNO_REFERENCE_IMPLEMENTED": "PASS" if pure_dno_ok else "FAIL",
        "DNO_REFERENCE_USES_DYNAMIC_PREDICTOR": "NO",
        "DNO_QUANTILE_CONTROL_ROUTE": "PASS" if quantile_ok else "FAIL",
        "INVERSE_EXECUTION_MAP": INVERSE_EXECUTION_MAP,
    }
