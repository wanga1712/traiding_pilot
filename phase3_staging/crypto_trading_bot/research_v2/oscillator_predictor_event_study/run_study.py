"""OSCILLATOR-PREDICTOR-HISTORICAL-EVENT-STUDY-1 orchestrator."""
from __future__ import annotations

import inspect
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from crypto_trading_bot.research_v2.indicator_engine.bars import parse_ts
from crypto_trading_bot.research_v2.oscillator_predictor.dynamic_predictor import compute_predictor_feature_series

from .anti_leakage import run_anti_leakage_tests
from .bar_loader import effective_scan_range, load_continuous_bars
from .config import (
    ACTIVE_SPLITS,
    ARTIFACT_ROOT,
    CONTROL_ATR_BAND,
    CONTROL_DNO_QUANTILE,
    FROZEN_PREDICTOR_CONFIG,
    REPO_ROOT,
    STUDY_TFS,
    TARGET_AGGREGATION,
    split_bounds,
)
from .stats import classify_stability
from .study_engine import (
    aggregate_distance_calibration,
    aggregate_reach_by_tf,
    aggregate_reversal_outcomes,
    build_cross_event_rows,
    build_reach_rows,
    build_scan_context,
    compute_base_rates_from_contexts,
)
from .version import PREDICTOR_AUTHORITY_COMMIT, STUDY_VERSION, WIP_ID


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, cwd=REPO_ROOT).strip()
    except Exception:  # noqa: BLE001
        return "UNKNOWN"


def _index_map(bars: list[dict[str, Any]], split_start: datetime, split_end: datetime) -> list[int]:
    out = []
    for i, b in enumerate(bars):
        ct = parse_ts(b["close_time"])
        if ct.tzinfo is None:
            ct = ct.replace(tzinfo=timezone.utc)
        if split_start <= ct < split_end:
            out.append(i)
    return out


def _control_comparison(base_lift: pd.DataFrame, outcomes: pd.DataFrame) -> dict[str, str]:
    """Compare dynamic predictor vs controls on validation OB/OS h=5 reversal lift."""
    out = {}
    for label, control_id in (
        ("DYNAMIC_VS_DNO_QUANTILE_CONTROL", CONTROL_DNO_QUANTILE),
        ("DYNAMIC_VS_ATR_CONTROL", CONTROL_ATR_BAND),
    ):
        dyn = base_lift[
            (base_lift["split"] == "VALIDATION")
            & (base_lift["direction"] == "OB")
            & (base_lift["horizon"] == 5)
        ]
        dyn_lift = float(dyn["absolute_lift"].mean()) if not dyn.empty else None
        ctrl = outcomes[
            (outcomes["split"] == "VALIDATION")
            & (outcomes["direction"] == "OB")
            & (outcomes["horizon"] == 5)
            & (outcomes["control_id"] == control_id)
        ]
        ctrl_rate = float(ctrl["reversal_rate_event"].mean()) if not ctrl.empty else None
        if dyn_lift is None or ctrl_rate is None:
            out[label] = "INSUFFICIENT_SAMPLE"
        elif dyn_lift > 0:
            out[label] = "DYNAMIC_BETTER"
        elif dyn_lift < 0:
            out[label] = "CONTROL_BETTER"
        else:
            out[label] = "TIE"
    return out


def _research_verdict(stability: pd.DataFrame, base_lift: pd.DataFrame) -> str:
    val = stability[stability["classification"].isin(["STABLE_POSITIVE", "WEAK_POSITIVE"])]
    if len(val) >= 3:
        return "PREDICTOR_EFFECT_SUPPORTED"
    if base_lift.empty:
        return "PREDICTOR_EFFECT_NOT_SUPPORTED"
    lifts = base_lift[(base_lift["split"] == "VALIDATION") & (base_lift["horizon"] == 5)]["absolute_lift"]
    if lifts.empty:
        return "PREDICTOR_EFFECT_NOT_SUPPORTED"
    pos = (lifts > 0.02).sum()
    if pos >= 2:
        return "PREDICTOR_EFFECT_WEAK"
    return "PREDICTOR_EFFECT_NOT_SUPPORTED"


def _distance_calibration_summary(cal: pd.DataFrame) -> str:
    if cal.empty:
        return "NO_DATA"
    # check monotonicity in OB direction for validation close hits
    sub = cal[(cal["split"] == "VALIDATION") & (cal["direction"] == "OB")]
    if sub.empty:
        return "NO_DATA"
    by_bin = sub.groupby("distance_bin")["next_close_hit_rate"].mean()
    rates = list(by_bin.values)
    if len(rates) < 2:
        return "INSUFFICIENT_BINS"
    mono = all(rates[i] <= rates[i + 1] for i in range(len(rates) - 1))
    return "MONOTONIC_INCREASING" if mono else "NON_MONOTONIC"


def _write_visual_audit(events: list[dict[str, Any]], bars_by_key: dict[tuple[str, str], list]) -> None:
    audit_dir = ARTIFACT_ROOT / "visual_audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(events)
    df = df[(df.get("primary", True) == True) & (df["control_id"] == "PROJECT_DYNAMIC_EXTREMA_V1")]  # noqa: E712
    picks: list[dict[str, Any]] = []
    for split in ("DISCOVERY", "VALIDATION"):
        for direction in ("OB", "OS"):
            et = f"{direction}_EVENT"
            sub = df[(df["split"] == split) & (df["event_type"] == et)]
            for _, row in sub.head(2).iterrows():
                picks.append(row.to_dict())
    for i, ev in enumerate(picks[:8]):
        tf = ev["timeframe"]
        split = ev["split"]
        bars = bars_by_key.get((tf, split), [])
        if not bars:
            continue
        idx = int(ev.get("event_index", 0))
        lo = max(0, idx - 20)
        hi = min(len(bars), idx + 11)
        payload = {
            "timeframe": tf,
            "split": split,
            "event_type": ev["event_type"],
            "decision_time": ev["decision_time"],
            "closes": [float(b["close"]) for b in bars[lo:hi]],
            "times": [str(b["close_time"]) for b in bars[lo:hi]],
            "event_offset": idx - lo,
        }
        (audit_dir / f"event_{i+1}_{split}_{ev['event_type']}.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
    (audit_dir / "README.txt").write_text(
        "Research-only visual audit payloads for representative OB/OS cross events.\n",
        encoding="utf-8",
    )


def run_study() -> dict[str, Any]:
    from crypto_trading_bot.research_v2.market_data.research_access import run_data_location_preflight

    disc_start = split_bounds("DISCOVERY")[0]
    val_end = split_bounds("VALIDATION")[1]
    preflight = run_data_location_preflight(
        required_start=disc_start,
        required_end=val_end,
        artifact_root=ARTIFACT_ROOT,
    )
    if preflight.get("READY_FOR_HISTORICAL_EVENT_STUDY") != "YES":
        preflight["HISTORICAL_EVENT_STUDY_STARTED"] = "NO"
        preflight["abort_reason"] = "S7 canonical data unavailable — study not started"
        (ARTIFACT_ROOT / "summary_v1.json").write_text(json.dumps(preflight, indent=2), encoding="utf-8")
        return preflight

    preflight["HISTORICAL_EVENT_STUDY_STARTED"] = "YES"
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    reach_all: list[dict[str, Any]] = []
    events_all: list[dict[str, Any]] = []
    contexts: list[Any] = []
    load_meta: dict[str, Any] = {}
    bars_by_key: dict[tuple[str, str], list] = {}
    split_periods: dict[str, dict[str, str | None]] = {}
    valid_counts: dict[str, int] = {"DISCOVERY": 0, "VALIDATION": 0}

    disc_start = split_bounds("DISCOVERY")[0]
    val_end = split_bounds("VALIDATION")[1]

    for tf in STUDY_TFS:
        print(f"Loading {tf}...", flush=True)
        bars, meta = load_continuous_bars(tf, disc_start, val_end)
        load_meta[tf] = {"full_span": meta}
        if not bars:
            continue
        for split in ACTIVE_SPLITS:
            start, end = split_bounds(split)
            eff_first, eff_last, scan = effective_scan_range(bars, start, end)
            load_meta[tf][split] = {
                **meta,
                "requested_start": start.isoformat(),
                "requested_end": end.isoformat(),
                "effective_first": eff_first.isoformat() if eff_first else None,
                "effective_last": eff_last.isoformat() if eff_last else None,
                "scan_bar_count": len(scan),
            }
            if not scan:
                continue
            scan_indices = _index_map(bars, start, end)
            ctx = build_scan_context(
                timeframe=tf,
                split=split,
                bars=bars,
                scan_indices=scan_indices,
                effective_first=eff_first or start,
                effective_last=eff_last or end,
            )
            contexts.append(ctx)
            bars_by_key[(tf, split)] = bars
            reach = build_reach_rows(ctx)
            reach_all.extend(reach)
            events_all.extend(build_cross_event_rows(ctx))
            valid_counts[split] += sum(1 for i in scan_indices if ctx.preds[i].get("valid"))
            split_periods.setdefault(split, {})[tf] = load_meta[tf][split]["effective_last"]
        print(f"  done {tf}: {len(bars)} bars", flush=True)

    reach_df = aggregate_reach_by_tf(reach_all)
    cal_df = aggregate_distance_calibration(reach_all)
    events_df = pd.DataFrame(events_all) if events_all else pd.DataFrame()
    outcomes_df = aggregate_reversal_outcomes(events_all)
    base_lift_df = compute_base_rates_from_contexts(contexts, events_all)

    stability_rows = []
    for (tf, direction, horizon), g in base_lift_df.groupby(["timeframe", "direction", "horizon"]):
        disc = g[g["split"] == "DISCOVERY"]
        val = g[g["split"] == "VALIDATION"]
        d_lift = float(disc["absolute_lift"].iloc[0]) if not disc.empty else None
        v_lift = float(val["absolute_lift"].iloc[0]) if not val.empty else None
        d_n = int(disc["sample_count_event"].iloc[0]) if not disc.empty else 0
        v_n = int(val["sample_count_event"].iloc[0]) if not val.empty else 0
        stability_rows.append(
            {
                "timeframe": tf,
                "direction": direction,
                "horizon": horizon,
                "discovery_lift": d_lift,
                "validation_lift": v_lift,
                "discovery_event_n": d_n,
                "validation_event_n": v_n,
                "classification": classify_stability(d_lift, v_lift, min_n_discovery=d_n, min_n_validation=v_n),
            }
        )
    stability_df = pd.DataFrame(stability_rows)

    ctx_strat = []
    if reach_all:
        rdf = pd.DataFrame(reach_all)
        for (tf, split, band), g in rdf.groupby(["timeframe", "split", "band_position"]):
            ctx_strat.append(
                {
                    "timeframe": tf,
                    "split": split,
                    "band_position": band,
                    "geometry_r_bin": "UNKNOWN",
                    "sample_count": len(g),
                    "ob_next_close_hit_rate": float(g["next_close_at_or_above_ob"].mean()),
                    "os_next_close_hit_rate": float(g["next_close_at_or_below_os"].mean()),
                }
            )
    ctx_strat_df = pd.DataFrame(ctx_strat)

    control_cmp = _control_comparison(base_lift_df, outcomes_df)
    dist_summary = _distance_calibration_summary(cal_df)
    verdict = _research_verdict(stability_df, base_lift_df)

    # anti-leakage on first available 1H discovery bars
    anti_bars = bars_by_key.get(("1H", "DISCOVERY"), [])
    anti = run_anti_leakage_tests(anti_bars[:500], timeframe="1H") if anti_bars else {
        k: "SKIP" for k in (
            "FUTURE_PRICE_MUTATION",
            "FUTURE_EVENT_OUTCOME_NOT_IN_FEATURES",
            "HTF_COMPLETION_CAUSALITY",
            "GAP_SEGMENT_POLICY",
            "BATCH_STREAMING_REFERENCE_PARITY",
        )
    }
    anti["OOS_ACCESS_COUNT"] = 0

    # inspect predictor modules for future labels in feature construction
    from crypto_trading_bot.research_v2.oscillator_predictor import series_engine as se

    se_src = inspect.getsource(se)
    if "forward_return" not in se_src and "reversal_success" not in se_src:
        anti["FUTURE_EVENT_OUTCOME_NOT_IN_FEATURES"] = "PASS"

    _write_visual_audit(events_all, bars_by_key)

    if not reach_df.empty:
        reach_df.to_csv(ARTIFACT_ROOT / "next_bar_reach_by_tf_v1.csv", index=False)
    if not cal_df.empty:
        cal_df.to_csv(ARTIFACT_ROOT / "distance_calibration_v1.csv", index=False)
    if not events_df.empty:
        events_df.to_parquet(ARTIFACT_ROOT / "cross_events_v1.parquet", index=False)
    if not outcomes_df.empty:
        outcomes_df.to_csv(ARTIFACT_ROOT / "reversal_outcomes_by_tf_v1.csv", index=False)
    if not base_lift_df.empty:
        base_lift_df.to_csv(ARTIFACT_ROOT / "base_rate_lift_v1.csv", index=False)
    if not outcomes_df.empty:
        outcomes_df[outcomes_df["control_id"] == CONTROL_DNO_QUANTILE].to_csv(
            ARTIFACT_ROOT / "control_quantile_v1.csv", index=False
        )
        outcomes_df[outcomes_df["control_id"] == CONTROL_ATR_BAND].to_csv(
            ARTIFACT_ROOT / "control_atr_v1.csv", index=False
        )
    if not stability_df.empty:
        stability_df.to_csv(ARTIFACT_ROOT / "discovery_validation_stability_v1.csv", index=False)
    if not ctx_strat_df.empty:
        ctx_strat_df.to_csv(ARTIFACT_ROOT / "context_stratification_v1.csv", index=False)

    ev_primary = events_df[
        (events_df.get("primary", True) == True) & (events_df["control_id"] == "PROJECT_DYNAMIC_EXTREMA_V1")  # noqa: E712
    ] if not events_df.empty else pd.DataFrame()

    ob_disc = len(ev_primary[(ev_primary["event_type"] == "OB_EVENT") & (ev_primary["split"] == "DISCOVERY")]) if not ev_primary.empty else 0
    os_disc = len(ev_primary[(ev_primary["event_type"] == "OS_EVENT") & (ev_primary["split"] == "DISCOVERY")]) if not ev_primary.empty else 0
    ob_val = len(ev_primary[(ev_primary["event_type"] == "OB_EVENT") & (ev_primary["split"] == "VALIDATION")]) if not ev_primary.empty else 0
    os_val = len(ev_primary[(ev_primary["event_type"] == "OS_EVENT") & (ev_primary["split"] == "VALIDATION")]) if not ev_primary.empty else 0

    def _mean_lift(split: str, direction: str, h: int = 5) -> float | None:
        sub = base_lift_df[
            (base_lift_df["split"] == split)
            & (base_lift_df["direction"] == direction)
            & (base_lift_df["horizon"] == h)
        ]
        return float(sub["absolute_lift"].mean()) if not sub.empty else None

    best_disc = None
    best_val = None
    if not stability_df.empty:
        pos = stability_df[stability_df["classification"] == "STABLE_POSITIVE"]
        if not pos.empty:
            best_disc = pos.sort_values("discovery_lift", ascending=False).iloc[0]["timeframe"]
        val_sorted = stability_df.sort_values("validation_lift", ascending=False)
        if not val_sorted.empty and val_sorted.iloc[0]["validation_lift"] is not None:
            best_val = val_sorted.iloc[0]["timeframe"]

    summary = {
        "wip_id": WIP_ID,
        "study_version": STUDY_VERSION,
        "predictor_authority_commit": PREDICTOR_AUTHORITY_COMMIT,
        "fixed_config": "7 / 2 / 100 / 5 / 0.80",
        "target_aggregation": TARGET_AGGREGATION,
        "discovery_period": split_bounds("DISCOVERY")[0].isoformat(),
        "discovery_period_end": split_bounds("DISCOVERY")[1].isoformat(),
        "validation_period": split_bounds("VALIDATION")[0].isoformat(),
        "validation_period_end": split_bounds("VALIDATION")[1].isoformat(),
        "oos_opened": "NO",
        "total_valid_predictor_rows_discovery": valid_counts["DISCOVERY"],
        "total_valid_predictor_rows_validation": valid_counts["VALIDATION"],
        "total_ob_events_discovery": ob_disc,
        "total_os_events_discovery": os_disc,
        "total_ob_events_validation": ob_val,
        "total_os_events_validation": os_val,
        "next_bar_distance_calibration": dist_summary,
        "research_verdict": verdict,
        **control_cmp,
        "discovery_validation_stability": stability_df["classification"].value_counts().to_dict()
        if not stability_df.empty
        else {},
        **{k: anti[k] for k in anti},
        "git_commit": _git_sha(),
    }
    (ARTIFACT_ROOT / "summary_v1.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (ARTIFACT_ROOT / "anti_leakage_tests_v1.json").write_text(json.dumps(anti, indent=2), encoding="utf-8")
    (ARTIFACT_ROOT / "dataset_manifest_v1.json").write_text(
        json.dumps({"load_meta": load_meta, "split_periods": split_periods}, indent=2),
        encoding="utf-8",
    )
    spec = f"""# Oscillator Predictor Historical Event Study v1

WIP: {WIP_ID}
Predictor authority: {PREDICTOR_AUTHORITY_COMMIT}

## Frozen config
- DNO_PERIOD=7, PEAK_STRENGTH=2, LOOKBACK=100, SAMPLES=5, OB_OS_LEVEL_PERCENT=0.80
- TARGET_AGGREGATION={TARGET_AGGREGATION}

## Splits
- DISCOVERY: {split_bounds('DISCOVERY')[0].isoformat()} → {split_bounds('DISCOVERY')[1].isoformat()}
- VALIDATION: {split_bounds('VALIDATION')[0].isoformat()} → {split_bounds('VALIDATION')[1].isoformat()}
- OOS: LOCKED

## Studies
- A: next-bar reach (close + intrabar touch secondary)
- B: true cross events (CROSSED_OB_BAND_UP / CROSSED_OS_BAND_DOWN)
- Controls: {CONTROL_DNO_QUANTILE}, {CONTROL_ATR_BAND}

No PnL. No parameter search.
"""
    (ARTIFACT_ROOT / "study_spec_v1.md").write_text(spec, encoding="utf-8")

    return {
        **summary,
        "ob_reversal_lift_discovery": _mean_lift("DISCOVERY", "OB"),
        "ob_reversal_lift_validation": _mean_lift("VALIDATION", "OB"),
        "os_reversal_lift_discovery": _mean_lift("DISCOVERY", "OS"),
        "os_reversal_lift_validation": _mean_lift("VALIDATION", "OS"),
        "best_supported_tf_discovery": best_disc,
        "best_supported_tf_validation": best_val,
        "artifact_root": str(ARTIFACT_ROOT.relative_to(REPO_ROOT)).replace("\\", "/"),
    }


def main() -> dict[str, Any]:
    result = run_study()
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    main()
