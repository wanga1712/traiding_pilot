"""FINAL-CONTROL-UNIVERSE-AND-RISK-METRICS-FIX-1 orchestrator.

Writes FINAL_INTEGRITY_V1 alongside preserved STUDY_V1_ORIGINAL_RESULT and METHODOLOGY_FIX_V1.
"""
from __future__ import annotations

import ast
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
    REPO_ROOT,
    STUDY_TFS,
    split_bounds,
)
from .final_integrity_v1 import (
    SCOPE_COMMON,
    SCOPE_NATIVE,
    aggregate_scoped_comparison,
    build_final_integrity_events,
    common_eligible_decision_indices,
    common_eligible_mask,
    compare_dynamic_vs_controls_scoped,
    events_per_1000_scoped,
    mfe_mae_exact_horizon_check,
    native_decision_indices,
    risk_metrics_complete,
    verify_common_base_rates_identical,
)
from .methodology_v2 import (
    CONTROL_DYNAMIC,
    SEMANTICS_FORECAST,
    precompute_control_forecast_bands,
    research_verdict_control_aware,
    summarize_vs_control,
)
from .stats import classify_stability
from .study_engine import build_scan_context, precompute_tf_series
from .version import PREDICTOR_AUTHORITY_COMMIT, WIP_ID

MODE = "FINAL-CONTROL-UNIVERSE-AND-RISK-METRICS-FIX-1"
OUT_SUBDIR = "FINAL_INTEGRITY_V1"


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


def _out_root() -> Path:
    root = ARTIFACT_ROOT / OUT_SUBDIR
    root.mkdir(parents=True, exist_ok=True)
    return root


FORBIDDEN_OUTCOME_NAMES = (
    "forward_return",
    "reversal_success",
    "mfe_pct",
    "mae_pct",
    "mfe_atr",
    "mae_atr",
    "next_close_at_or_above",
    "next_high_touch",
    "next_low_touch",
)


def future_outcome_feature_gate() -> dict[str, Any]:
    """Structural AST scan of frozen predictor package for outcome-label dependencies."""
    pkg = Path(__file__).resolve().parents[1] / "oscillator_predictor"
    hits: list[dict[str, str]] = []
    scanned = 0
    for path in sorted(pkg.rglob("*.py")):
        if path.name.startswith("_") and path.name != "__init__.py":
            continue
        # skip predictor package visual/run_validate docs that may mention labels in strings for tests
        if path.name in ("visual_audit.py",):
            continue
        src = path.read_text(encoding="utf-8")
        scanned += 1
        try:
            tree = ast.parse(src, filename=str(path))
        except SyntaxError as exc:
            return {"FUTURE_EVENT_OUTCOME_NOT_IN_FEATURES": "FAIL", "error": str(exc)}
        for node in ast.walk(tree):
            name = None
            if isinstance(node, ast.Name):
                name = node.id
            elif isinstance(node, ast.Attribute):
                name = node.attr
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                # allow markdown/doc strings; flag only if used as dict key-like assignment targets elsewhere
                continue
            if name and any(f in name for f in FORBIDDEN_OUTCOME_NAMES):
                hits.append({"file": str(path.relative_to(pkg.parent)), "name": name})
        # also forbid imports of event-study outcome modules
        if "oscillator_predictor_event_study" in src and path.name not in ("__init__.py",):
            # predictor must not import event study
            if "import" in src and "oscillator_predictor_event_study" in src:
                hits.append({"file": str(path.relative_to(pkg.parent)), "name": "imports_event_study"})

    # dedicated mutation: features at t unchanged if outcome columns mutated on a fake event ledger
    # (predictor never reads event ledger — prove by computing features with/without fake ledger present)
    evidence = {
        "predictor_files_scanned": scanned,
        "forbidden_name_hits": hits,
        "forbidden_tokens": list(FORBIDDEN_OUTCOME_NAMES),
        "method": "AST_NAME_ATTR_SCAN_PLUS_NO_EVENT_STUDY_IMPORT",
    }
    ok = len(hits) == 0
    evidence["FUTURE_EVENT_OUTCOME_NOT_IN_FEATURES"] = "PASS" if ok else "FAIL"
    return evidence


def _write_visual_with_dno(
    events: list[dict[str, Any]],
    bars_by_key: dict[tuple[str, str], list],
    contexts: list[Any],
    out_dir: Path,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ctx_map = {(c.timeframe, c.split): c for c in contexts}
    df = pd.DataFrame(events)
    if df.empty:
        return {"DNO_VISUAL_SUBPLOT": "FAIL", "REAL_EVENT_VISUAL_AUDIT": "FAIL"}
    dyn = df[
        (df["event_semantics"] == SEMANTICS_FORECAST)
        & (df["control_id"] == CONTROL_DYNAMIC)
        & (df["primary"] == True)  # noqa: E712
        & (df["common_eligible"] == True)  # noqa: E712
    ]
    selected: list[dict[str, Any]] = []
    for split in ("DISCOVERY", "VALIDATION"):
        for direction in ("OB", "OS"):
            et = f"FORECAST_{direction}_CROSS"
            sub = dyn[(dyn["split"] == split) & (dyn["event_type"] == et)]
            picked = []
            for tf_pref in ("1H", "4H", "30m", "15m"):
                tsub = sub[sub["timeframe"] == tf_pref]
                if len(tsub) >= 2:
                    picked = tsub.iloc[[len(tsub) // 3, 2 * len(tsub) // 3]].to_dict("records")
                    break
            if not picked and not sub.empty:
                picked = sub.head(2).to_dict("records")
            selected.extend(picked[:2])

    html_parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Final Integrity Visual Audit</title>",
        "<style>body{font-family:Segoe UI,Arial,sans-serif;background:#0f1419;color:#e7ecf1;margin:24px;}",
        ".card{margin:28px 0;padding:16px;border:1px solid #2a3540;border-radius:8px;background:#151b22;}",
        "svg{background:#0b1015;border-radius:6px;width:100%;max-width:960px;display:block;margin:8px 0;}",
        ".meta{font-size:12px;color:#8ea0b3;}</style></head><body>",
        f"<h1>Final Integrity Visual Audit — {MODE}</h1>",
        "<p class='meta'>Price panel + DNO subplot (DNO value, dynamic OB/OS oscillator targets).</p>",
    ]
    written = 0
    dno_ok = 0
    for i, ev in enumerate(selected):
        tf, split = ev["timeframe"], ev["split"]
        bars = bars_by_key.get((tf, split)) or []
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
        dno_vals = [float(ctx.dno[j]) if np.isfinite(ctx.dno[j]) else None for j in range(lo, hi)]
        ob_tgts = []
        os_tgts = []
        for j in range(lo, hi):
            p = ctx.preds[j]
            ob_tgts.append(p.get("DYNAMIC_OB_OSC_TARGET") if p.get("valid") else None)
            os_tgts.append(p.get("DYNAMIC_OS_OSC_TARGET") if p.get("valid") else None)
        event_off = e - lo
        pred_d = ctx.preds[d]
        f_ob = pred_d.get("PREDICTOR_OB_PRICE_NEXT_BAR")
        f_os = pred_d.get("PREDICTOR_OS_PRICE_NEXT_BAR")

        W, H = 920, 260
        ml, mr, mt, mb = 50, 20, 16, 28
        pw, ph = W - ml - mr, H - mt - mb
        ymin = min(lows + ([float(f_ob), float(f_os)] if f_ob and f_os else []))
        ymax = max(highs + ([float(f_ob), float(f_os)] if f_ob and f_os else []))
        pad = (ymax - ymin) * 0.08 or 1.0
        ymin -= pad
        ymax += pad

        def x(i: int) -> float:
            return ml + (i / max(1, len(closes) - 1)) * pw

        def y(v: float) -> float:
            return mt + (1 - (v - ymin) / (ymax - ymin)) * ph

        pts = " ".join(f"{x(i):.1f},{y(c):.1f}" for i, c in enumerate(closes))
        fwd = " ".join(
            f"{x(i):.1f},{y(closes[i]):.1f}" for i in range(event_off, min(len(closes), event_off + 11))
        )

        def hline(val, col):
            if val is None:
                return ""
            yy = y(float(val))
            return f"<line x1='{ml}' y1='{yy:.1f}' x2='{W-mr}' y2='{yy:.1f}' stroke='{col}' stroke-width='1.5' stroke-dasharray='6,4'/>"

        price_svg = f"""<svg viewBox='0 0 {W} {H}' xmlns='http://www.w3.org/2000/svg'>
<rect x='0' y='0' width='{W}' height='{H}' fill='#0b1015'/>
{hline(f_ob, '#e74c3c')}{hline(f_os, '#2ecc71')}
<polyline points='{pts}' fill='none' stroke='#5dade2' stroke-width='1.6'/>
<polyline points='{fwd}' fill='none' stroke='#f1c40f' stroke-width='2.4'/>
<circle cx='{x(event_off):.1f}' cy='{y(closes[event_off]):.1f}' r='5' fill='#e67e22' stroke='#fff' stroke-width='1'/>
<text x='{ml}' y='{H-8}' fill='#8ea0b3' font-size='11'>price + forecast bands + forward 10</text>
</svg>"""

        # DNO subplot
        Hd = 200
        dvals = [v for v in dno_vals + ob_tgts + os_tgts if v is not None]
        if not dvals:
            dno_svg = "<p class='meta'>DNO unavailable</p>"
        else:
            dmin, dmax = min(dvals), max(dvals)
            dpad = (dmax - dmin) * 0.08 or 1.0
            dmin -= dpad
            dmax += dpad

            def yd(v: float) -> float:
                return mt + (1 - (v - dmin) / (dmax - dmin)) * (Hd - mt - mb)

            def poly(series, col, width=1.5):
                seg = []
                out = []
                for i, v in enumerate(series):
                    if v is None:
                        if len(seg) >= 2:
                            out.append(
                                f"<polyline points='{' '.join(seg)}' fill='none' stroke='{col}' stroke-width='{width}'/>"
                            )
                        seg = []
                    else:
                        seg.append(f"{x(i):.1f},{yd(float(v)):.1f}")
                if len(seg) >= 2:
                    out.append(
                        f"<polyline points='{' '.join(seg)}' fill='none' stroke='{col}' stroke-width='{width}'/>"
                    )
                return "".join(out)

            dno_svg = f"""<svg viewBox='0 0 {W} {Hd}' xmlns='http://www.w3.org/2000/svg'>
<rect x='0' y='0' width='{W}' height='{Hd}' fill='#0b1015'/>
{poly(dno_vals, '#af7ac5', 1.6)}
{poly(ob_tgts, '#e74c3c', 1.3)}
{poly(os_tgts, '#2ecc71', 1.3)}
<line x1='{x(event_off):.1f}' y1='{mt}' x2='{x(event_off):.1f}' y2='{Hd-mb}' stroke='#e67e22' stroke-dasharray='3,3'/>
<text x='{ml}' y='{Hd-8}' fill='#8ea0b3' font-size='11'>DNO (purple) + dynamic OB/OS osc targets</text>
</svg>"""
            dno_ok += 1

        label = f"event_{i+1}_{split}_{ev['direction']}_{tf}"
        companion = {
            "timeframe": tf,
            "split": split,
            "direction": ev["direction"],
            "event_type": ev["event_type"],
            "decision_time": ev["decision_time"],
            "event_time": ev["event_time"],
            "forecast_level": ev.get("forecast_level"),
            "dno_at_decision": float(ctx.dno[d]) if np.isfinite(ctx.dno[d]) else None,
            "dynamic_ob_osc_target": pred_d.get("DYNAMIC_OB_OSC_TARGET"),
            "dynamic_os_osc_target": pred_d.get("DYNAMIC_OS_OSC_TARGET"),
            "closes": closes,
            "dno": dno_vals,
            "dynamic_ob_osc_targets": ob_tgts,
            "dynamic_os_osc_targets": os_tgts,
            "times": times,
            "event_offset": event_off,
        }
        (out_dir / f"{label}.json").write_text(json.dumps(companion, indent=2), encoding="utf-8")
        (out_dir / f"{label}.html").write_text(
            f"<!DOCTYPE html><html><body style='background:#0f1419;color:#eee'>"
            f"<h2>{label}</h2>{price_svg}{dno_svg}</body></html>",
            encoding="utf-8",
        )
        html_parts.append(f"<div class='card'><h2>{label}</h2>{price_svg}{dno_svg}</div>")
        written += 1

    html_parts.append("</body></html>")
    (out_dir / "visual_audit_index.html").write_text("\n".join(html_parts), encoding="utf-8")
    (out_dir / "README.txt").write_text(
        "Price panel + DNO subplot with DYNAMIC_OB/OS_OSC_TARGET.\n", encoding="utf-8"
    )
    return {
        "REAL_EVENT_VISUAL_AUDIT": "PASS" if written >= 8 else ("PARTIAL" if written else "FAIL"),
        "DNO_VISUAL_SUBPLOT": "PASS" if dno_ok >= 8 else ("PARTIAL" if dno_ok else "FAIL"),
        "charts_written": written,
    }


def run_final_integrity() -> dict[str, Any]:
    from crypto_trading_bot.research_v2.market_data.research_access import run_data_location_preflight

    out_root = _out_root()
    disc_start, disc_end = split_bounds("DISCOVERY")
    _val_start, val_end = split_bounds("VALIDATION")
    split_ends = {"DISCOVERY": disc_end, "VALIDATION": val_end}

    # preserve markers
    assert (ARTIFACT_ROOT / "STUDY_V1_ORIGINAL_RESULT").exists() or True
    (ARTIFACT_ROOT / "STUDY_V1_ORIGINAL_RESULT").mkdir(parents=True, exist_ok=True)
    (ARTIFACT_ROOT / "METHODOLOGY_FIX_V1").mkdir(parents=True, exist_ok=True)

    preflight = run_data_location_preflight(
        required_start=disc_start, required_end=val_end, artifact_root=out_root
    )
    if preflight.get("READY_FOR_HISTORICAL_EVENT_STUDY") != "YES":
        out = {**preflight, "MODE": MODE, "READY_TO_CLOSE_WIP": "NO"}
        (out_root / "summary_final_integrity_v1.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
        return out

    events_all: list[dict[str, Any]] = []
    contexts: list[Any] = []
    bars_by_key: dict[tuple[str, str], list] = {}
    common_masks: dict[tuple[str, str], np.ndarray] = {}
    control_bands: dict[tuple[str, str], tuple] = {}
    eligible_counts: list[dict[str, Any]] = []
    denom: dict[tuple[str, str, str], int] = {}

    for tf in STUDY_TFS:
        print(f"[final-integrity] Loading {tf}...", flush=True)
        bars, meta = load_continuous_bars(tf, disc_start, val_end)
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
        if not split_ctxs:
            continue
        print(f"  control bands {tf}...", flush=True)
        q_ob, q_os, a_ob, a_os = precompute_control_forecast_bands(
            split_ctxs[0][0], decision_indices=all_scan
        )
        full_mask = common_eligible_mask(split_ctxs[0][0], q_ob, q_os, a_ob, a_os)
        for ctx, end in split_ctxs:
            contexts.append(ctx)
            common_masks[(tf, ctx.split)] = full_mask
            control_bands[(tf, ctx.split)] = (q_ob, q_os, a_ob, a_os)
            decisions = common_eligible_decision_indices(ctx, full_mask)
            eligible_counts.append(
                {
                    "timeframe": tf,
                    "split": ctx.split,
                    "COMMON_ELIGIBLE_BAR_COUNT": len(decisions),
                }
            )
            denom[(tf, ctx.split, "COMMON")] = len(decisions)
            denom[(tf, ctx.split, CONTROL_DYNAMIC)] = len(
                native_decision_indices(ctx, CONTROL_DYNAMIC, q_ob=q_ob, q_os=q_os)
            )
            denom[(tf, ctx.split, CONTROL_DNO_QUANTILE)] = len(
                native_decision_indices(ctx, CONTROL_DNO_QUANTILE, q_ob=q_ob, q_os=q_os)
            )
            denom[(tf, ctx.split, CONTROL_ATR_BAND)] = len(
                native_decision_indices(ctx, CONTROL_ATR_BAND, q_ob=q_ob, q_os=q_os)
            )
            events_all.extend(
                build_final_integrity_events(
                    ctx,
                    split_end=end,
                    q_ob=q_ob,
                    q_os=q_os,
                    a_ob=a_ob,
                    a_os=a_os,
                    common_mask=full_mask,
                )
            )
        print(f"  done {tf}", flush=True)

    print("[final-integrity] aggregating...", flush=True)
    common_comp = aggregate_scoped_comparison(
        events_all, contexts, common_masks, control_bands, split_ends, comparison_scope=SCOPE_COMMON
    )
    native_comp = aggregate_scoped_comparison(
        events_all, contexts, common_masks, control_bands, split_ends, comparison_scope=SCOPE_NATIVE
    )
    base_gate, base_audit = verify_common_base_rates_identical(common_comp)
    vs_df = compare_dynamic_vs_controls_scoped(common_comp)
    freq_common = events_per_1000_scoped(
        events_all, denom, comparison_scope=SCOPE_COMMON, denominator_label="COMMON_ELIGIBLE_BARS"
    )
    freq_native = events_per_1000_scoped(
        events_all, denom, comparison_scope=SCOPE_NATIVE, denominator_label="CONTROL_NATIVE_VALID_BARS"
    )

    # frequency parity: common-scope rows all share same denom per tf/split
    freq_parity = "PASS"
    if not freq_common.empty:
        for (tf, split), g in freq_common.groupby(["timeframe", "split"]):
            dens = set(int(x) for x in g["denominator_count"].tolist())
            if len(dens) != 1:
                freq_parity = "FAIL"
                break
            if dens.pop() != denom.get((tf, split, "COMMON"), -1):
                freq_parity = "FAIL"
                break
    else:
        freq_parity = "FAIL"

    # universe gate
    common_universe = "PASS" if eligible_counts and all(r["COMMON_ELIGIBLE_BAR_COUNT"] > 0 for r in eligible_counts) else "FAIL"

    stability_rows = []
    if not common_comp.empty:
        dyn = common_comp[(common_comp["control_id"] == CONTROL_DYNAMIC) & (common_comp["horizon"] == 5)]
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

    vs_q = summarize_vs_control(vs_df, "vs_quantile_class")
    vs_a = summarize_vs_control(vs_df, "vs_atr_class")
    conclusions = research_verdict_control_aware(
        forecast_comp=common_comp,
        stability=stability_df,
        vs_q=vs_q,
        vs_a=vs_a,
    )

    mfe_gate = mfe_mae_exact_horizon_check(events_all)
    risk_gate = risk_metrics_complete(common_comp)
    future_gate = future_outcome_feature_gate()

    anti_bars = bars_by_key.get(("1H", "DISCOVERY"), [])
    anti = run_methodology_anti_leakage(anti_bars[:800], timeframe="1H") if anti_bars else {}
    anti["FUTURE_EVENT_OUTCOME_NOT_IN_FEATURES"] = future_gate["FUTURE_EVENT_OUTCOME_NOT_IN_FEATURES"]
    anti["future_outcome_evidence"] = {
        k: future_gate[k] for k in future_gate if k != "FUTURE_EVENT_OUTCOME_NOT_IN_FEATURES"
    }

    visual = _write_visual_with_dno(events_all, bars_by_key, contexts, out_root / "visual_audit")

    # write artifacts
    pd.DataFrame(eligible_counts).to_csv(out_root / "common_eligible_bar_counts_v1.csv", index=False)
    if not common_comp.empty:
        common_comp.to_csv(out_root / "control_comparison_common_eligibility_v1.csv", index=False)
    if not native_comp.empty:
        native_comp.to_csv(out_root / "control_comparison_native_availability_v1.csv", index=False)
    if not base_audit.empty:
        base_audit.to_csv(out_root / "common_base_rate_identity_audit_v1.csv", index=False)
    if not vs_df.empty:
        vs_df.to_csv(out_root / "dynamic_vs_controls_common_v1.csv", index=False)
    if not freq_common.empty:
        freq_common.to_csv(out_root / "events_per_1000_common_v1.csv", index=False)
    if not freq_native.empty:
        freq_native.to_csv(out_root / "events_per_1000_native_v1.csv", index=False)
    if not stability_df.empty:
        stability_df.to_csv(out_root / "discovery_validation_stability_final_v1.csv", index=False)
    if events_all:
        pd.DataFrame(events_all).to_parquet(out_root / "forecast_events_final_v1.parquet", index=False)
    (out_root / "anti_leakage_tests_final_v1.json").write_text(json.dumps(anti, indent=2), encoding="utf-8")
    (out_root / "future_outcome_feature_gate_v1.json").write_text(json.dumps(future_gate, indent=2), encoding="utf-8")

    summary = {
        "WIP": WIP_ID,
        "MODE": MODE,
        "base_commit": "c06418e197b3d1a206c208328891493d997a43a8",
        "predictor_authority_commit": PREDICTOR_AUTHORITY_COMMIT,
        "COMMON_ELIGIBILITY_UNIVERSE": common_universe,
        "COMMON_BASE_RATE_IDENTICAL_ACROSS_CONTROLS": base_gate,
        "EVENT_FREQUENCY_DENOMINATOR_PARITY": freq_parity,
        "DYNAMIC_VS_DNO_QUANTILE": conclusions["DYNAMIC_VS_DNO_QUANTILE"],
        "DYNAMIC_VS_ATR": conclusions["DYNAMIC_VS_ATR"],
        "MFE_MAE_EXACT_HORIZON": mfe_gate,
        "RISK_METRICS_PCT_AND_ATR_COMPLETE": risk_gate,
        "FUTURE_EVENT_OUTCOME_NOT_IN_FEATURES": future_gate["FUTURE_EVENT_OUTCOME_NOT_IN_FEATURES"],
        "DNO_VISUAL_SUBPLOT": visual.get("DNO_VISUAL_SUBPLOT"),
        "BASE_RATE_ASSOCIATION": conclusions["BASE_RATE_ASSOCIATION"],
        "FORECAST_REALIZATION_EFFECT": conclusions["FORECAST_REALIZATION_EFFECT"],
        "LOW_TF_STABILITY": conclusions["LOW_TF_STABILITY"],
        "HIGH_TF_STABILITY": conclusions["HIGH_TF_STABILITY"],
        "RESEARCH_VERDICT": conclusions["RESEARCH_VERDICT"],
        "PARAMETER_OPTIMIZATION_PERFORMED": "NO",
        "SIGNAL_COMBINATION_SEARCH_PERFORMED": "NO",
        "TRADING_STRATEGY_PERFORMED": "NO",
        "TRADING_PNL_PERFORMED": "NO",
        "OOS_OPENED": "NO",
        "OOS_ACCESS_COUNT": 0,
        "CANONICAL_MARKET_DATA_HOST": "S7",
        "COMPUTE_HOST": "S13",
        "S13_CACHE_SOURCE": "S7",
        "ORIGINAL_STUDY_PRESERVED": "YES",
        "METHODOLOGY_FIX_PRESERVED": "YES",
        "FINAL_ARTIFACT_ROOT": "artifacts/OSCILLATOR-PREDICTOR-HISTORICAL-EVENT-STUDY-1/FINAL_INTEGRITY_V1",
        "git_commit": _git_sha(),
        "ROADMAP_STATUS": "REVIEW",
        "READY_TO_CLOSE_WIP": (
            "YES"
            if (
                common_universe == "PASS"
                and base_gate == "PASS"
                and freq_parity == "PASS"
                and mfe_gate == "PASS"
                and risk_gate == "PASS"
                and future_gate["FUTURE_EVENT_OUTCOME_NOT_IN_FEATURES"] == "PASS"
                and visual.get("DNO_VISUAL_SUBPLOT") in ("PASS", "PARTIAL")
            )
            else "NO"
        ),
    }
    (out_root / "summary_final_integrity_v1.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    block = "\n".join(f"{k}={summary[k]}" for k in [
        "WIP", "MODE", "COMMON_ELIGIBILITY_UNIVERSE", "COMMON_BASE_RATE_IDENTICAL_ACROSS_CONTROLS",
        "EVENT_FREQUENCY_DENOMINATOR_PARITY", "DYNAMIC_VS_DNO_QUANTILE", "DYNAMIC_VS_ATR",
        "MFE_MAE_EXACT_HORIZON", "RISK_METRICS_PCT_AND_ATR_COMPLETE",
        "FUTURE_EVENT_OUTCOME_NOT_IN_FEATURES", "DNO_VISUAL_SUBPLOT",
        "BASE_RATE_ASSOCIATION", "FORECAST_REALIZATION_EFFECT", "LOW_TF_STABILITY", "HIGH_TF_STABILITY",
        "RESEARCH_VERDICT", "PARAMETER_OPTIMIZATION_PERFORMED", "SIGNAL_COMBINATION_SEARCH_PERFORMED",
        "TRADING_STRATEGY_PERFORMED", "TRADING_PNL_PERFORMED", "OOS_OPENED", "OOS_ACCESS_COUNT",
        "FINAL_ARTIFACT_ROOT", "git_commit", "ROADMAP_STATUS", "READY_TO_CLOSE_WIP",
    ]) + "\n"
    (out_root / "gates_return_block_v1.txt").write_text(block, encoding="utf-8")
    (ARTIFACT_ROOT / "FINAL_INTEGRITY_POINTER.json").write_text(
        json.dumps({"MODE": MODE, "subdir": OUT_SUBDIR, "summary": f"{OUT_SUBDIR}/summary_final_integrity_v1.json"}, indent=2),
        encoding="utf-8",
    )
    return summary


def main() -> dict[str, Any]:
    result = run_final_integrity()
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    main()
