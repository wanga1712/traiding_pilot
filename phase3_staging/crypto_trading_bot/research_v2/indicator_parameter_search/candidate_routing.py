"""Candidate routing preflight and mandatory reference checks."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from crypto_trading_bot.research_v2.indicator_engine.bars import parse_ts
from .candidate_registry import load_frozen_registry
from .config import ARTIFACT_ROOT, SEARCH_TFS, split_bounds
from .signals_bank import generate_signals_for_row, resolve_candidate_route

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
INVERSE_ROUTES = {
    "DMA_PRICE_CROSS_PREDICTOR",
    "STANDARD_STOCH_THRESHOLD_PREDICTOR",
    "STANDARD_MACD_CROSS_PREDICTOR",
    "DNO_OB_OS_PREDICTOR",
}


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


def representative_bars_by_tf(*, n_eval_bars: int = 220) -> dict[str, list[dict[str, Any]]]:
    disc_start, _ = split_bounds("DISCOVERY")
    warmup_start = disc_start - timedelta(days=30)
    tf_seconds = {
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
    bars_by_tf: dict[str, list[dict[str, Any]]] = {}
    for tf in SEARCH_TFS:
        step = tf_seconds[tf]
        n = max(n_eval_bars, 120)
        bars_by_tf[tf] = _oscillating_bars(warmup_start.replace(tzinfo=timezone.utc), n, step_seconds=step)
    return bars_by_tf


def run_candidate_routing_preflight(
    registry: list[dict[str, Any]] | None = None,
    *,
    bars_by_tf: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    rows = registry or load_frozen_registry(ARTIFACT_ROOT / "candidate_registry_snapshot_v1.csv")
    bars_by_tf = bars_by_tf or representative_bars_by_tf()
    disc_start, disc_end = split_bounds("DISCOVERY")
    scan_start_iso = disc_start.isoformat()
    scan_end_iso = disc_end.isoformat()
    exceptions: list[str] = []
    unresolved: list[str] = []
    family_counts: dict[str, dict[str, int]] = {}
    sample_cache: dict[tuple, Any] = {}
    for row in rows:
        family = row["family"]
        fam = family_counts.setdefault(family, {"ok": 0, "exception": 0, "unresolved": 0})
        try:
            route = resolve_candidate_route(row)
            if route == "UNRESOLVED":
                unresolved.append(row["candidate_id"])
                fam["unresolved"] += 1
                continue
            bars = bars_by_tf[row["decision_tf"]]
            generate_signals_for_row(
                bars,
                row,
                scan_start_iso=scan_start_iso,
                scan_end_iso=scan_end_iso,
                sample_cache=sample_cache,
            )
            fam["ok"] += 1
        except Exception as exc:  # noqa: BLE001
            exceptions.append(f"{row['candidate_id']}: {exc}")
            fam["exception"] += 1
    family_report = {
        "DMA_ROUTING": family_counts.get("DMA", {}).get("ok", 0),
        "STOCH_ROUTING": family_counts.get("STOCHASTIC", {}).get("ok", 0),
        "MACD_ROUTING": family_counts.get("MACD", {}).get("ok", 0),
        "DNO_PREDICTOR_ROUTING": family_counts.get("DNO_PREDICTOR", {}).get("ok", 0),
        "OSC_PREDICTOR_ROUTING": family_counts.get("OSC_PREDICTOR", {}).get("ok", 0),
        "INVERSE_PREDICTOR_ROUTING": family_counts.get("INVERSE_PREDICTOR", {}).get("ok", 0),
    }
    return {
        "CANDIDATE_ROUTING_PREFLIGHT_TOTAL": len(rows),
        "CANDIDATE_ROUTING_PREFLIGHT_EXCEPTION_COUNT": len(exceptions),
        "CANDIDATE_ROUTING_PREFLIGHT_UNRESOLVED_COUNT": len(unresolved),
        "exceptions": exceptions[:20],
        "unresolved": unresolved[:20],
        **family_report,
    }


def run_mandatory_reference_sanity(
    registry: list[dict[str, Any]] | None = None,
    *,
    bars_by_tf: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    rows = registry or load_frozen_registry(ARTIFACT_ROOT / "candidate_registry_snapshot_v1.csv")
    bars_by_tf = bars_by_tf or representative_bars_by_tf()
    disc_start, disc_end = split_bounds("DISCOVERY")
    scan_start_iso = disc_start.isoformat()
    scan_end_iso = disc_end.isoformat()
    mandatory_rows = [
        r
        for r in rows
        if r["parameter_set_id"] in MANDATORY_REFERENCE_PARAMETER_SET_IDS
        or (
            r["family"] == "INVERSE_PREDICTOR"
            and (r.get("parameters") or {}).get("inverse_route") in INVERSE_ROUTES
        )
    ]
    failures: list[str] = []
    executable = 0
    for row in mandatory_rows:
        try:
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
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{row['candidate_id']}: {exc}")
    return {
        "MANDATORY_REFERENCE_ROUTE_COUNT": len(mandatory_rows),
        "MANDATORY_REFERENCE_ROUTE_EXECUTABLE_COUNT": executable,
        "MANDATORY_REFERENCE_ROUTE_FAILURE_COUNT": len(failures),
        "failures": failures[:20],
    }
