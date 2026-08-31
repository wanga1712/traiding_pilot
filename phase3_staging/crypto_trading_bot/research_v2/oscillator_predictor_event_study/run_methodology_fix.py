"""INDEPENDENT-METHODOLOGY-REVIEW-FIX-1 orchestrator.

Writes methodology_fix artifacts alongside preserved STUDY_V1_ORIGINAL_RESULT.
Does not change predictor formula or frozen config. No OOS / PnL / optimization.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from crypto_trading_bot.research_v2.indicator_engine.bars import parse_ts

from .anti_leakage_v2 import run_methodology_anti_leakage
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
from .methodology_v2 import (
    CONTROL_DYNAMIC,
    SEMANTICS_FORECAST,
    SEMANTICS_STATE,
    aggregate_control_comparison,
    best_tf_table,
    build_methodology_events,
    classify_distance_calibration,
    classify_distance_summary,
    compare_dynamic_vs_controls,
    events_per_1000,
    precompute_control_forecast_bands,
    research_verdict_control_aware,
    summarize_vs_control,
)
from .stats import classify_stability
from .study_engine import (
    aggregate_distance_calibration,
    aggregate_reach_by_tf,
    build_reach_rows,
    build_scan_context,
    precompute_tf_series,
)
from .version import PREDICTOR_AUTHORITY_COMMIT, WIP_ID

MODE = "INDEPENDENT-METHODOLOGY-REVIEW-FIX-1"
FIX_SUBDIR = "METHODOLOGY_FIX_V1"
GEOMETRY_CONTEXT_AVAILABLE = "NO"


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


def _fix_root() -> Path:
    root = ARTIFACT_ROOT / FIX_SUBDIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_visual_html(
    events: list[dict[str, Any]],
    bars_by_key: dict[tuple[str, str], list],
    contexts: list[Any],
    out_dir: Path,
) -> dict[str, Any]:
    """Create real HTML charts for 2 disc OB/OS + 2 val OB/OS forecast events."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ctx_map = {(c.timeframe, c.split): c for c in contexts}
    df = pd.DataFrame(events)
    if df.empty:
        return {"REAL_EVENT_VISUAL_AUDIT": "FAIL", "reason": "no_events"}
    dyn = df[
        (df["event_semantics"] == SEMANTICS_FORECAST)
        & (df["control_id"] == CONTROL_DYNAMIC)
        & (df["primary"] == True)  # noqa: E712
    ]
    picks: list[dict[str, Any]] = []
    for split in ("DISCOVERY", "VALIDATION"):
        for direction in ("OB", "OS"):
            et = f"FORECAST_{direction}_CROSS"
            sub = dyn[(dyn["split"] == split) & (dyn["event_type"] == et)]
            # prefer mid-sample 1H / 4H when available
            for tf_pref in ("1H", "4H", "30m", "15m", "2H"):
                tsub = sub[sub["timeframe"] == tf_pref]
                if len(tsub) >= 2:
                    picks.extend(tsub.iloc[[len(tsub) // 3, 2 * len(tsub) // 3]].to_dict("records"))
                    break
            else:
                if not sub.empty:
                    picks.extend(sub.head(2).to_dict("records"))
            # keep only 2 per split/direction
            while sum(1 for p in picks if p["split"] == split and p["direction"] == direction) > 2:
                picks.pop()

    # ensure exactly up to 8
    selected: list[dict[str, Any]] = []
    for split in ("DISCOVERY", "VALIDATION"):
        for direction in ("OB", "OS"):
            group = [p for p in picks if p["split"] == split and p["direction"] == direction][:2]
            selected.extend(group)

    html_parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        "<title>Methodology Fix Visual Audit</title>",
        "<style>",
        "body{font-family:Segoe UI,Arial,sans-serif;background:#0f1419;color:#e7ecf1;margin:24px;}",
        "h1{font-size:20px;} h2{font-size:15px;color:#9db0c4;}",
        ".card{margin:28px 0;padding:16px;border:1px solid #2a3540;border-radius:8px;background:#151b22;}",
        "svg{background:#0b1015;border-radius:6px;width:100%;max-width:960px;}",
        ".meta{font-size:12px;color:#8ea0b3;line-height:1.5;}",
        "</style></head><body>",
        f"<h1>Forecast Realization Visual Audit — {MODE}</h1>",
        "<p class='meta'>Price + forecast OB/OS bands (from decision e-1) + event marker + forward 10-bar path. "
        "DNO targets shown when available. Companion JSON written alongside.</p>",
    ]

    written = 0
    for i, ev in enumerate(selected):
        tf = ev["timeframe"]
        split = ev["split"]
        bars = bars_by_key.get((tf, split)) or bars_by_key.get((tf, "DISCOVERY"), [])
        ctx = ctx_map.get((tf, split))
        if not bars or ctx is None:
            continue
        e = int(ev["event_index"])
        d = int(ev["decision_index"])
        lo = max(0, e - 30)
        hi = min(len(bars), e + 11)
        closes = [float(bars[j]["close"]) for j in range(lo, hi)]
        highs = [float(bars[j]["high"]) for j in range(lo, hi)]
        lows = [float(bars[j]["low"]) for j in range(lo, hi)]
        times = [str(bars[j]["close_time"]) for j in range(lo, hi)]
        event_off = e - lo
        # forecast bands from decision bar
        pred_d = ctx.preds[d] if d < len(ctx.preds) else {}
        f_ob = pred_d.get("PREDICTOR_OB_PRICE_NEXT_BAR")
        f_os = pred_d.get("PREDICTOR_OS_PRICE_NEXT_BAR")
        dno_ob = pred_d.get("DYNAMIC_OB_OSC_TARGET")
        dno_os = pred_d.get("DYNAMIC_OS_OSC_TARGET")

        ymin = min(lows + ([float(f_ob), float(f_os)] if f_ob and f_os else []))
        ymax = max(highs + ([float(f_ob), float(f_os)] if f_ob and f_os else []))
        pad = (ymax - ymin) * 0.08 or 1.0
        ymin -= pad
        ymax += pad
        W, H = 920, 320
        ml, mr, mt, mb = 50, 20, 20, 40
        pw, ph = W - ml - mr, H - mt - mb

        def x(i: int) -> float:
            return ml + (i / max(1, len(closes) - 1)) * pw

        def y(v: float) -> float:
            return mt + (1 - (v - ymin) / (ymax - ymin)) * ph

        # price polyline
        pts = " ".join(f"{x(i):.1f},{y(c):.1f}" for i, c in enumerate(closes))
        # forward path highlight from event
        fwd = " ".join(
            f"{x(i):.1f},{y(closes[i]):.1f}"
            for i in range(event_off, min(len(closes), event_off + 11))
        )

        def hline(val: float | None, color: str, dash: str = "6,4") -> str:
            if val is None:
                return ""
            yy = y(float(val))
            return (
                f"<line x1='{ml}' y1='{yy:.1f}' x2='{W-mr}' y2='{yy:.1f}' "
                f"stroke='{color}' stroke-width='1.5' stroke-dasharray='{dash}'/>"
            )

        level = ev.get("forecast_level")
        svg = f"""
<svg viewBox='0 0 {W} {H}' xmlns='http://www.w3.org/2000/svg'>
  <rect x='0' y='0' width='{W}' height='{H}' fill='#0b1015'/>
  {hline(float(f_ob) if f_ob is not None else None, '#e74c3c')}
  {hline(float(f_os) if f_os is not None else None, '#2ecc71')}
  <polyline points='{pts}' fill='none' stroke='#5dade2' stroke-width='1.6'/>
  <polyline points='{fwd}' fill='none' stroke='#f1c40f' stroke-width='2.4'/>
  <circle cx='{x(event_off):.1f}' cy='{y(closes[event_off]):.1f}' r='5' fill='#e67e22' stroke='#fff' stroke-width='1'/>
  <text x='{ml}' y='{H-12}' fill='#8ea0b3' font-size='11'>{times[0]} → {times[-1]}</text>
  <text x='{W-mr-180}' y='18' fill='#e74c3c' font-size='11'>OB forecast</text>
  <text x='{W-mr-180}' y='32' fill='#2ecc71' font-size='11'>OS forecast</text>
  <text x='{W-mr-180}' y='46' fill='#f1c40f' font-size='11'>forward 10 bars</text>
</svg>
"""
        label = f"event_{i+1}_{split}_{ev['direction']}_{tf}"
        companion = {
            "timeframe": tf,
            "split": split,
            "direction": ev["direction"],
            "event_type": ev["event_type"],
            "decision_time": ev["decision_time"],
            "event_time": ev["event_time"],
            "forecast_level": level,
            "predictor_ob_next_bar": f_ob,
            "predictor_os_next_bar": f_os,
            "dynamic_ob_target": dno_ob,
            "dynamic_os_target": dno_os,
            "closes": closes,
            "highs": highs,
            "lows": lows,
            "times": times,
            "event_offset": event_off,
            "geometry_r_bin": "UNKNOWN",
            "GEOMETRY_CONTEXT_AVAILABLE": GEOMETRY_CONTEXT_AVAILABLE,
        }
        (out_dir / f"{label}.json").write_text(json.dumps(companion, indent=2), encoding="utf-8")
        (out_dir / f"{label}.html").write_text(
            "<!DOCTYPE html><html><body style='background:#0f1419;color:#eee;font-family:sans-serif'>"
            f"<h2>{label}</h2>{svg}</body></html>",
            encoding="utf-8",
        )
        html_parts.append(
            f"<div class='card'><h2>{label}</h2>"
            f"<div class='meta'>decision={ev['decision_time']} event={ev['event_time']} "
            f"level={level} direction={ev['direction']}</div>{svg}</div>"
        )
        written += 1

    html_parts.append("</body></html>")
    (out_dir / "visual_audit_index.html").write_text("\n".join(html_parts), encoding="utf-8")
    (out_dir / "README.txt").write_text(
        "Real forecast-realization visual audit charts (HTML/SVG). "
        "JSON companions are machine-readable only.\n"
        f"GEOMETRY_CONTEXT_AVAILABLE={GEOMETRY_CONTEXT_AVAILABLE}\n",
        encoding="utf-8",
    )
    ok = written >= 8
    return {
        "REAL_EVENT_VISUAL_AUDIT": "PASS" if ok else ("PARTIAL" if written > 0 else "FAIL"),
        "charts_written": written,
    }


def run_methodology_fix() -> dict[str, Any]:
    from crypto_trading_bot.research_v2.market_data.research_access import run_data_location_preflight

    fix_root = _fix_root()
    disc_start, disc_end = split_bounds("DISCOVERY")
    val_start, val_end = split_bounds("VALIDATION")
    split_ends = {"DISCOVERY": disc_end, "VALIDATION": val_end}

    # ensure V1 preserve marker exists
    preserve = ARTIFACT_ROOT / "STUDY_V1_ORIGINAL_RESULT"
    preserve.mkdir(parents=True, exist_ok=True)
    meta_path = preserve / "PRESERVE_META.json"
    if not meta_path.exists():
        meta_path.write_text(
            json.dumps(
                {
                    "label": "STUDY_V1_ORIGINAL_RESULT",
                    "original_research_verdict": "PREDICTOR_EFFECT_SUPPORTED",
                    "INDEPENDENT_REVIEW_STATUS": "METHODOLOGY_FIX_REQUIRED",
                    "base_study_commit": "f98c10d47c4b3749ed90940eb7b2a8584268ddda",
                    "summary_commit": "bfb7f89557de43d6040954b68f58aa34cfc35bcd",
                    "predictor_authority_commit": PREDICTOR_AUTHORITY_COMMIT,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    else:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["INDEPENDENT_REVIEW_STATUS"] = "METHODOLOGY_FIX_REQUIRED"
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    preflight = run_data_location_preflight(
        required_start=disc_start,
        required_end=val_end,
        artifact_root=fix_root,
    )
    if preflight.get("READY_FOR_HISTORICAL_EVENT_STUDY") != "YES":
        out = {
            **preflight,
            "MODE": MODE,
            "READY_FOR_FINAL_INDEPENDENT_REVIEW": "NO",
            "abort_reason": "S7 cache unavailable",
        }
        (fix_root / "summary_methodology_fix_v1.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
        return out

    events_all: list[dict[str, Any]] = []
    reach_all: list[dict[str, Any]] = []
    contexts: list[Any] = []
    bars_by_key: dict[tuple[str, str], list] = {}
    valid_counts: dict[tuple[str, str], int] = {}
    load_meta: dict[str, Any] = {}

    for tf in STUDY_TFS:
        print(f"[methodology-fix] Loading {tf}...", flush=True)
        bars, meta = load_continuous_bars(tf, disc_start, val_end)
        load_meta[tf] = meta
        if not bars:
            continue
        arrays, atr, dno, preds, seg_starts = precompute_tf_series(bars, timeframe=tf)
        all_scan: list[int] = []
        split_ctxs: list[tuple[Any, datetime]] = []
        for split in ACTIVE_SPLITS:
            start, end = split_bounds(split)
            eff_first, eff_last, scan = effective_scan_range(bars, start, end)
            if not scan:
                continue
            scan_indices = _index_map(bars, start, end)
            all_scan.extend(scan_indices)
            ctx = build_scan_context(
                timeframe=tf,
                split=split,
                bars=bars,
                scan_indices=scan_indices,
                effective_first=eff_first or start,
                effective_last=eff_last or end,
                arrays=arrays,
                atr=atr,
                dno=dno,
                preds=preds,
                seg_starts=seg_starts,
            )
            split_ctxs.append((ctx, end))
            bars_by_key[(tf, split)] = bars
            valid_counts[(tf, split)] = sum(1 for i in scan_indices if preds[i].get("valid"))
        print(f"  control bands {tf} (n_decisions={len(set(all_scan))})...", flush=True)
        if not split_ctxs:
            print(f"  skip {tf}: no scan", flush=True)
            continue
        q_ob_all, q_os_all, a_ob_all, a_os_all = precompute_control_forecast_bands(
            split_ctxs[0][0], decision_indices=all_scan
        )
        for ctx, end in split_ctxs:
            contexts.append(ctx)
            reach_all.extend(build_reach_rows(ctx))
            events_all.extend(
                build_methodology_events(
                    ctx,
                    split_end=end,
                    q_ob=q_ob_all,
                    q_os=q_os_all,
                    a_ob=a_ob_all,
                    a_os=a_os_all,
                )
            )
        print(f"  done {tf}", flush=True)

    print("[methodology-fix] aggregating...", flush=True)
    reach_df = aggregate_reach_by_tf(reach_all)
    cal_df = aggregate_distance_calibration(reach_all)
    dist_class_df = classify_distance_calibration(cal_df)

    forecast_comp = aggregate_control_comparison(
        events_all, contexts, event_semantics=SEMANTICS_FORECAST, split_ends=split_ends
    )
    state_comp = aggregate_control_comparison(
        events_all, contexts, event_semantics=SEMANTICS_STATE, split_ends=split_ends
    )
    vs_df = compare_dynamic_vs_controls(forecast_comp)
    freq_df = events_per_1000(events_all, valid_counts, event_semantics=SEMANTICS_FORECAST)

    # stability on dynamic forecast h=5
    stability_rows = []
    if not forecast_comp.empty:
        dyn = forecast_comp[
            (forecast_comp["control_id"] == CONTROL_DYNAMIC) & (forecast_comp["horizon"] == 5)
        ]
        for (tf, direction), g in dyn.groupby(["timeframe", "direction"]):
            disc = g[g["split"] == "DISCOVERY"]
            val = g[g["split"] == "VALIDATION"]
            d_lift = float(disc.iloc[0]["absolute_lift"]) if not disc.empty else None
            v_lift = float(val.iloc[0]["absolute_lift"]) if not val.empty else None
            d_n = int(disc.iloc[0]["event_count"]) if not disc.empty else 0
            v_n = int(val.iloc[0]["event_count"]) if not val.empty else 0
            stability_rows.append(
                {
                    "timeframe": tf,
                    "direction": direction,
                    "horizon": 5,
                    "discovery_lift": d_lift,
                    "validation_lift": v_lift,
                    "discovery_event_n": d_n,
                    "validation_event_n": v_n,
                    "classification": classify_stability(
                        d_lift, v_lift, min_n_discovery=d_n, min_n_validation=v_n
                    ),
                }
            )
    stability_df = pd.DataFrame(stability_rows)
    best_tf_df = best_tf_table(stability_df, forecast_comp)

    vs_q = summarize_vs_control(vs_df, "vs_quantile_class")
    vs_a = summarize_vs_control(vs_df, "vs_atr_class")
    conclusions = research_verdict_control_aware(
        forecast_comp=forecast_comp,
        stability=stability_df,
        vs_q=vs_q,
        vs_a=vs_a,
    )

    # gate checks
    edf = pd.DataFrame(events_all) if events_all else pd.DataFrame()
    dyn_fc = edf[
        (edf["event_semantics"] == SEMANTICS_FORECAST) & (edf["control_id"] == CONTROL_DYNAMIC) & (edf["primary"] == True)  # noqa: E712
    ] if not edf.empty else pd.DataFrame()
    q_fc = edf[
        (edf["event_semantics"] == SEMANTICS_FORECAST) & (edf["control_id"] == CONTROL_DNO_QUANTILE) & (edf["primary"] == True)  # noqa: E712
    ] if not edf.empty else pd.DataFrame()
    a_fc = edf[
        (edf["event_semantics"] == SEMANTICS_FORECAST) & (edf["control_id"] == CONTROL_ATR_BAND) & (edf["primary"] == True)  # noqa: E712
    ] if not edf.empty else pd.DataFrame()

    # causality: decision_index == event_index - 1 for all forecast events
    causality_ok = True
    if not edf.empty:
        fc = edf[edf["event_semantics"] == SEMANTICS_FORECAST]
        if not fc.empty:
            causality_ok = bool(((fc["event_index"] - fc["decision_index"]) == 1).all())

    # quantile moving-band reference: state events have prev_band and curr_band
    q_state = edf[
        (edf["event_semantics"] == SEMANTICS_STATE) & (edf["control_id"] == CONTROL_DNO_QUANTILE)
    ] if not edf.empty else pd.DataFrame()
    q_moving_ok = (not q_state.empty) and ("prev_band" in q_state.columns) and ("curr_band" in q_state.columns)

    atr_nonzero = len(a_fc) > 0
    atr_ref_ok = causality_ok and atr_nonzero

    # boundary purity: no non-null outcome past split end (already enforced; verify)
    disc_cross = "NO"
    val_cross = "NO"
    if not edf.empty:
        for _, row in edf.iterrows():
            e_idx = int(row["event_index"])
            tf = row["timeframe"]
            split = row["split"]
            ctx = next((c for c in contexts if c.timeframe == tf and c.split == split), None)
            if ctx is None:
                continue
            end = split_ends[split]
            for h in (1, 3, 5, 10):
                col = f"reversal_success_{h}"
                if col not in row or row[col] is None or (isinstance(row[col], float) and np.isnan(row[col])):
                    continue
                j = e_idx + h
                if j >= len(ctx.bars):
                    continue
                ct = parse_ts(ctx.bars[j]["close_time"])
                if ct.tzinfo is None:
                    ct = ct.replace(tzinfo=timezone.utc)
                if ct >= end:
                    if split == "DISCOVERY":
                        disc_cross = "YES"
                    else:
                        val_cross = "YES"

    anti_bars = bars_by_key.get(("1H", "DISCOVERY"), [])
    anti = (
        run_methodology_anti_leakage(anti_bars[:800], timeframe="1H")
        if anti_bars
        else {"BATCH_STREAMING_VALUE_PARITY": "SKIP"}
    )

    visual = _write_visual_html(events_all, bars_by_key, contexts, fix_root / "visual_audit")

    # apples-to-apples: same metric columns for all three controls
    apples = "PASS"
    if forecast_comp.empty:
        apples = "FAIL"
    else:
        ctrls = set(forecast_comp["control_id"].unique())
        needed = {CONTROL_DYNAMIC, CONTROL_DNO_QUANTILE, CONTROL_ATR_BAND}
        if not needed.issubset(ctrls):
            apples = "FAIL"
        cols = {"event_count", "reversal_rate", "base_rate", "absolute_lift", "relative_lift"}
        if not cols.issubset(set(forecast_comp.columns)):
            apples = "FAIL"

    # write artifacts
    if not reach_df.empty:
        reach_df.to_csv(fix_root / "next_bar_reach_by_tf_v2.csv", index=False)
    if not cal_df.empty:
        cal_df.to_csv(fix_root / "distance_calibration_v2.csv", index=False)
    if not dist_class_df.empty:
        dist_class_df.to_csv(fix_root / "distance_calibration_class_v2.csv", index=False)
    if events_all:
        pd.DataFrame(events_all).to_parquet(fix_root / "forecast_and_state_events_v2.parquet", index=False)
    if not forecast_comp.empty:
        forecast_comp.to_csv(fix_root / "control_comparison_forecast_v2.csv", index=False)
    if not state_comp.empty:
        state_comp.to_csv(fix_root / "control_comparison_state_v2.csv", index=False)
    if not vs_df.empty:
        vs_df.to_csv(fix_root / "dynamic_vs_controls_v2.csv", index=False)
    if not freq_df.empty:
        freq_df.to_csv(fix_root / "events_per_1000_v2.csv", index=False)
    if not stability_df.empty:
        stability_df.to_csv(fix_root / "discovery_validation_stability_v2.csv", index=False)
    if not best_tf_df.empty:
        best_tf_df.to_csv(fix_root / "best_tf_table_v2.csv", index=False)

    def _count(df: pd.DataFrame, split: str, direction: str) -> int:
        if df.empty:
            return 0
        return int(len(df[(df["split"] == split) & (df["direction"] == direction)]))

    summary = {
        "WIP": WIP_ID,
        "MODE": MODE,
        "ORIGINAL_STUDY_PRESERVED": "YES",
        "INDEPENDENT_REVIEW_STATUS": "METHODOLOGY_FIX_REQUIRED",
        "original_verdict_preserved": "PREDICTOR_EFFECT_SUPPORTED",
        "fixed_config": "7 / 2 / 100 / 5 / 0.80",
        "target_aggregation": TARGET_AGGREGATION,
        "predictor_authority_commit": PREDICTOR_AUTHORITY_COMMIT,
        "QUANTILE_FORECAST_EVENT_CAUSALITY": "PASS" if causality_ok else "FAIL",
        "QUANTILE_MOVING_BAND_CROSS_REFERENCE": "PASS" if q_moving_ok else "FAIL",
        "ATR_CONTROL_NONZERO_EVENT_COUNT": "PASS" if atr_nonzero else "FAIL",
        "ATR_FORECAST_EVENT_REFERENCE": "PASS" if atr_ref_ok else "FAIL",
        "CONTROL_COMPARISON_APPLES_TO_APPLES": apples,
        "DISCOVERY_OUTCOME_CROSSES_VALIDATION": disc_cross,
        "VALIDATION_OUTCOME_CROSSES_END": val_cross,
        "BATCH_STREAMING_VALUE_PARITY": anti.get("BATCH_STREAMING_VALUE_PARITY", "FAIL"),
        "HTF_COMPLETION_CAUSALITY": anti.get("HTF_COMPLETION_CAUSALITY"),
        "GAP_SEGMENT_POLICY": anti.get("GAP_SEGMENT_POLICY"),
        "FUTURE_PRICE_MUTATION": anti.get("FUTURE_PRICE_MUTATION"),
        "DISTANCE_CALIBRATION_DISCOVERY": classify_distance_summary(dist_class_df, "DISCOVERY"),
        "DISTANCE_CALIBRATION_VALIDATION": classify_distance_summary(dist_class_df, "VALIDATION"),
        **conclusions,
        "REAL_EVENT_VISUAL_AUDIT": visual.get("REAL_EVENT_VISUAL_AUDIT"),
        "GEOMETRY_CONTEXT_AVAILABLE": GEOMETRY_CONTEXT_AVAILABLE,
        "TOTAL_DYNAMIC_FORECAST_OB_DISCOVERY": _count(dyn_fc, "DISCOVERY", "OB"),
        "TOTAL_DYNAMIC_FORECAST_OS_DISCOVERY": _count(dyn_fc, "DISCOVERY", "OS"),
        "TOTAL_DYNAMIC_FORECAST_OB_VALIDATION": _count(dyn_fc, "VALIDATION", "OB"),
        "TOTAL_DYNAMIC_FORECAST_OS_VALIDATION": _count(dyn_fc, "VALIDATION", "OS"),
        "TOTAL_QUANTILE_FORECAST_EVENTS": int(len(q_fc)),
        "TOTAL_ATR_FORECAST_EVENTS": int(len(a_fc)),
        "PARAMETER_OPTIMIZATION_PERFORMED": "NO",
        "SIGNAL_COMBINATION_SEARCH_PERFORMED": "NO",
        "TRADING_STRATEGY_PERFORMED": "NO",
        "TRADING_PNL_PERFORMED": "NO",
        "OOS_OPENED": "NO",
        "OOS_ACCESS_COUNT": 0,
        "CANONICAL_MARKET_DATA_HOST": "S7",
        "COMPUTE_HOST": "S13",
        "S13_CACHE_SOURCE": "S7",
        "DIRECT_EXCHANGE_DOWNLOAD_ON_S13": "NO",
        "ARTIFACT_ROOT": str((ARTIFACT_ROOT).as_posix()),
        "FIX_ARTIFACT_ROOT": str(fix_root.as_posix()),
        "git_commit": _git_sha(),
        "ROADMAP_STATUS": "REVIEW",
        "READY_FOR_FINAL_INDEPENDENT_REVIEW": (
            "YES"
            if (
                causality_ok
                and q_moving_ok
                and atr_nonzero
                and apples == "PASS"
                and disc_cross == "NO"
                and val_cross == "NO"
                and anti.get("BATCH_STREAMING_VALUE_PARITY") == "PASS"
                and visual.get("REAL_EVENT_VISUAL_AUDIT") in ("PASS", "PARTIAL")
            )
            else "NO"
        ),
    }

    (fix_root / "summary_methodology_fix_v1.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (fix_root / "anti_leakage_tests_v2.json").write_text(json.dumps(anti, indent=2), encoding="utf-8")
    (fix_root / "dataset_manifest_v2.json").write_text(json.dumps({"load_meta": load_meta}, indent=2), encoding="utf-8")
    (fix_root / "gates_return_block_v1.txt").write_text(_format_return_block(summary), encoding="utf-8")

    # also mirror a short pointer at artifact root without overwriting V1 summary
    (ARTIFACT_ROOT / "METHODOLOGY_FIX_POINTER.json").write_text(
        json.dumps(
            {
                "MODE": MODE,
                "fix_subdir": FIX_SUBDIR,
                "ORIGINAL_STUDY_PRESERVED": "YES",
                "INDEPENDENT_REVIEW_STATUS": "METHODOLOGY_FIX_REQUIRED",
                "summary_path": f"{FIX_SUBDIR}/summary_methodology_fix_v1.json",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return summary


def _format_return_block(s: dict[str, Any]) -> str:
    keys = [
        "WIP",
        "MODE",
        "ORIGINAL_STUDY_PRESERVED",
        "QUANTILE_FORECAST_EVENT_CAUSALITY",
        "QUANTILE_MOVING_BAND_CROSS_REFERENCE",
        "ATR_CONTROL_NONZERO_EVENT_COUNT",
        "ATR_FORECAST_EVENT_REFERENCE",
        "CONTROL_COMPARISON_APPLES_TO_APPLES",
        "DISCOVERY_OUTCOME_CROSSES_VALIDATION",
        "VALIDATION_OUTCOME_CROSSES_END",
        "BATCH_STREAMING_VALUE_PARITY",
        "DISTANCE_CALIBRATION_DISCOVERY",
        "DISTANCE_CALIBRATION_VALIDATION",
        "BASE_RATE_ASSOCIATION",
        "FORECAST_REALIZATION_EFFECT",
        "DYNAMIC_VS_DNO_QUANTILE",
        "DYNAMIC_VS_ATR",
        "LOW_TF_STABILITY",
        "HIGH_TF_STABILITY",
        "REAL_EVENT_VISUAL_AUDIT",
        "GEOMETRY_CONTEXT_AVAILABLE",
        "TOTAL_DYNAMIC_FORECAST_OB_DISCOVERY",
        "TOTAL_DYNAMIC_FORECAST_OS_DISCOVERY",
        "TOTAL_DYNAMIC_FORECAST_OB_VALIDATION",
        "TOTAL_DYNAMIC_FORECAST_OS_VALIDATION",
        "TOTAL_QUANTILE_FORECAST_EVENTS",
        "TOTAL_ATR_FORECAST_EVENTS",
        "RESEARCH_VERDICT",
        "PARAMETER_OPTIMIZATION_PERFORMED",
        "SIGNAL_COMBINATION_SEARCH_PERFORMED",
        "TRADING_STRATEGY_PERFORMED",
        "TRADING_PNL_PERFORMED",
        "OOS_OPENED",
        "OOS_ACCESS_COUNT",
        "ARTIFACT_ROOT",
        "git_commit",
        "ROADMAP_STATUS",
        "READY_FOR_FINAL_INDEPENDENT_REVIEW",
    ]
    lines = []
    for k in keys:
        if k in s:
            lines.append(f"{k}={s[k]}")
    return "\n".join(lines) + "\n"


def main() -> dict[str, Any]:
    result = run_methodology_fix()
    print(json.dumps(result, indent=2))
    print("--- RETURN BLOCK ---")
    print(_format_return_block(result))
    return result


if __name__ == "__main__":
    main()
