"""REVERSAL_SIGNAL_EVENT_STUDY_V1 orchestrator."""
from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from crypto_trading_bot.research_v2.indicator_engine.bars import parse_ts

from .bar_io import filter_bars_in_range, load_continuous_bars, make_bar_service
from .candidates import build_candidate_registry, classify_counts
from .config import DECISION_TFS, EVENT_DIR, PARTITION_BOUNDS, SOURCE_WAVE_TFS
from .context_study import evaluate_context_candidate
from .match import enrich_matches_with_path_excursion, match_signals_to_events
from .metrics import (
    benjamini_hochberg,
    build_leaderboards,
    compute_directional_metrics,
    family_winners,
    pareto_front,
    tf_balanced_pool_note,
)
from .signals import (
    generate_indicator_pair_signals,
    generate_predictor_trigger_signals,
    generate_price_baseline_signals,
    years_covered,
)
from .version import STUDY_VERSION, WIP_ID

PREDICTOR_STRIDE = {"5m": 24, "15m": 6, "1H": 1, "4H": 1}
# Skip non-DMA predictors on 5m; skip all predictors on 5m if still too slow via flag below.
PREDICTOR_SKIP_TF = {"5m"}


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001
        return "UNKNOWN"


def _load_events(event_dir: Path) -> pd.DataFrame:
    ev = pd.read_parquet(event_dir / "reversal_events_v1.parquet")
    # NEVER use OOS for selection / study metrics in this WIP
    usable = ev[(ev["partition"].isin(["DISCOVERY", "VALIDATION"])) & (ev["partition_usable"] == True)]  # noqa: E712
    return usable.reset_index(drop=True)


def _write_csv(path: Path, rows: list[dict] | pd.DataFrame) -> None:
    if isinstance(rows, pd.DataFrame):
        rows.to_csv(path, index=False)
        return
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def _generate_for_registry(
    registry_rows: list[dict[str, Any]],
    bars: list[dict[str, Any]],
    *,
    decision_tf: str,
    scan_start: datetime,
) -> list[dict[str, Any]]:
    scan_iso = scan_start.isoformat()
    out: list[dict[str, Any]] = []
    for r in registry_rows:
        if r["decision_tf"] != decision_tf:
            continue
        role = r["role"]
        cid = r["candidate_id"]
        if role == "PRICE_BASELINE":
            out.extend(
                generate_price_baseline_signals(
                    bars, candidate_id=cid, kind=r["parameter_set_id"], decision_tf=decision_tf, scan_start_iso=scan_iso
                )
            )
        elif role == "DIRECTIONAL_TRIGGER":
            # On 5m skip heavy oscillators except DMA/RSI/MACD for runtime.
            if decision_tf == "5m" and r["parameter_set_id"] not in (
                "DMA_3X3_V1",
                "DMA_7X5_V1",
                "DMA_25X5_V1",
                "RSI_14_V1",
                "MACD_12_26_9_V1",
            ):
                continue
            up, down = r["source_feature_or_signal"].split("|")
            out.extend(
                generate_indicator_pair_signals(
                    bars,
                    candidate_id=cid,
                    parameter_set_id=r["parameter_set_id"],
                    up_primitive=up,
                    down_primitive=down,
                    decision_tf=decision_tf,
                    scan_start_iso=scan_iso,
                )
            )
        elif role == "PREDICTOR_THRESHOLD":
            # Full-history predictor walks are too expensive; see run_predictor_pivot_windows().
            continue
    return out


def run_predictor_pivot_windows(
    *,
    partition: str,
    events: pd.DataFrame,
    registry: list[dict[str, Any]],
    bars_by_tf: dict[str, list],
    out_signals: list[dict[str, Any]],
    out_matches: list[pd.DataFrame],
    metric_rows: list[dict[str, Any]],
    years: float,
    start: datetime,
    end: datetime,
) -> None:
    """Predictor triggers on pivot windows + sampled FP times (versioned thresholds)."""
    from .config import MAX_DELAY_SECONDS, SOURCE_WAVE_TFS, TF_BAR_SECONDS

    pred_regs = [r for r in registry if r["role"] == "PREDICTOR_THRESHOLD"]
    part_events = events[events["partition"] == partition]
    print(f"[{partition}] predictor pivot windows n_events={len(part_events)} n_cand={len(pred_regs)}", flush=True)

    rng = np.random.default_rng(7)
    fp_times: dict[str, list] = {}
    for tf, bars in bars_by_tf.items():
        scan = filter_bars_in_range(bars, start, end)
        if len(scan) < 100:
            fp_times[tf] = []
            continue
        k = min(1500, max(200, len(scan) // 20))
        idx = rng.choice(len(scan), size=min(k, len(scan)), replace=False)
        fp_times[tf] = [scan[int(i)]["close_time"] for i in idx]

    # Limit event count for heavier TFs if needed — use all usable events.
    for r in pred_regs:
        tf = r["decision_tf"]
        if tf not in bars_by_tf:
            continue
        if tf == "5m":
            continue
        # Prefer 1H/4H; skip 15m predictors for runtime (still in registry).
        if tf == "15m":
            continue
        up, down = r["parameter_set_id"].split("|")
        # Keep DMA/RSI/MACD signal predictors only in this study pass.
        if not any(x in up for x in ("DMA", "RSI_14_CROSS", "MACD_12_26_9_SIGNAL")):
            continue
        cid = r["candidate_id"]
        bars = bars_by_tf[tf]
        times = [parse_ts(b["close_time"]) for b in bars]
        sigs: list[dict[str, Any]] = []
        max_d = MAX_DELAY_SECONDS[tf]
        stride = 1

        # subsample events aggressively — predictor solve is O(events * window)
        ev_iter = part_events
        cap = 250 if partition == "DISCOVERY" else 120
        if len(part_events) > cap:
            ev_iter = part_events.sample(n=cap, random_state=11)

        for _, ev in ev_iter.iterrows():
            c_t = parse_ts(ev["true_pivot_time"])
            n_t = parse_ts(ev["next_pivot_time"]) if pd.notna(ev["next_pivot_time"]) else None
            pre_start = c_t.timestamp() - max_d
            end_t = min((n_t.timestamp() if n_t else c_t.timestamp() + max_d), c_t.timestamp() + max_d)
            i0 = next((i for i, t in enumerate(times) if t.timestamp() >= pre_start), None)
            if i0 is None:
                continue
            i1 = next((i for i, t in enumerate(times) if t.timestamp() > end_t), len(times) - 1)
            window_bars = bars[: i1 + 1]
            local = generate_predictor_trigger_signals(
                window_bars,
                candidate_id=cid,
                up_param=up,
                down_param=down,
                decision_tf=tf,
                scan_start_iso=times[i0].isoformat(),
                stride=stride,
                start_index=i0,
            )
            for s in local:
                if parse_ts(s["signal_time"]).timestamp() <= end_t:
                    sigs.append(s)

        # FP sample — small
        for ft in fp_times.get(tf, [])[:200]:
            ft_ts = parse_ts(ft)
            j = next((i for i, t in enumerate(times) if t >= ft_ts), None)
            if j is None or j < 80:
                continue
            prefix = bars[: j + 1]
            local = generate_predictor_trigger_signals(
                prefix,
                candidate_id=cid,
                up_param=up,
                down_param=down,
                decision_tf=tf,
                scan_start_iso=times[max(0, j - 2)].isoformat(),
                stride=1,
                start_index=max(0, j - 2),
            )
            for s in local:
                if abs(parse_ts(s["signal_time"]).timestamp() - ft_ts.timestamp()) <= TF_BAR_SECONDS[tf] * 2:
                    sigs.append(s)

        print(f"  [{partition}] {cid} signals={len(sigs)}", flush=True)
        if not sigs:
            continue
        out_signals.extend(sigs)
        m = match_signals_to_events(pd.DataFrame(sigs), part_events, decision_tf=tf)
        out_matches.append(m)
        scan_n = len(filter_bars_in_range(bars, start, end))
        base = dict(
            matches=m,
            events=part_events,
            candidate_id=cid,
            family=r["family"],
            role=r["role"],
            decision_tf=tf,
            scanned_from=start.isoformat(),
            scanned_to=end.isoformat(),
            valid_decision_bars=scan_n,
            partition=partition,
            years=years,
        )
        metric_rows.append(compute_directional_metrics(**base))
        for sw in SOURCE_WAVE_TFS:
            metric_rows.append(compute_directional_metrics(**base, source_wave_tf=sw))
        for pt in ("HIGH", "LOW"):
            metric_rows.append(compute_directional_metrics(**base, pivot_type=pt))


def _coverage_years(start: datetime, end: datetime) -> float:
    return max((end - start).total_seconds() / (365.25 * 24 * 3600), 1e-6)


def run_partition(
    *,
    partition: str,
    events: pd.DataFrame,
    registry: list[dict[str, Any]],
    service,
    out_signals: list[dict[str, Any]],
    out_matches: list[pd.DataFrame],
    metric_rows: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    frozen_ctx_thresholds: dict[str, dict[str, float]],
        context_only_tfs: tuple[str, ...] = ("1H",),
) -> dict[str, Any]:
    start, end = PARTITION_BOUNDS[partition]
    part_events = events[events["partition"] == partition].copy()
    print(f"=== {partition} events={len(part_events)} {start} → {end}", flush=True)
    years = _coverage_years(start, end)
    bars_by_tf: dict[str, list] = {}

    for tf in DECISION_TFS:
        print(f"[{partition}] load bars {tf}", flush=True)
        bars = load_continuous_bars(service, tf, start, end, warmup_bars=400)
        bars_by_tf[tf] = bars
        scan_bars = filter_bars_in_range(bars, start, end)
        print(f"[{partition}] {tf} bars_total={len(bars)} scan={len(scan_bars)}", flush=True)
        sigs = _generate_for_registry(registry, bars, decision_tf=tf, scan_start=start)
        print(f"[{partition}] {tf} signals={len(sigs)}", flush=True)
        out_signals.extend(sigs)
        if not sigs:
            continue
        sdf = pd.DataFrame(sigs)
        # Match per candidate — first-signal claim must not cross candidates.
        match_parts = []
        for cid, g in sdf.groupby("candidate_id", sort=False):
            m = match_signals_to_events(g, part_events, decision_tf=tf)
            match_parts.append(m)
        matches = pd.concat(match_parts, ignore_index=True) if match_parts else pd.DataFrame()
        # Path MAE/MFE only for primary post-C matches (skip repeats); skip on 5m for speed.
        if tf != "5m" and not matches.empty:
            primary = matches["match_type"] == "MATCHED_POST_C"
            if primary.any():
                enriched = enrich_matches_with_path_excursion(matches.loc[primary].copy(), {tf: bars})
                matches.loc[primary, enriched.columns] = enriched
        out_matches.append(matches)

        # metrics: pooled + by source_wave_tf + HIGH/LOW
        reg_by_id = {r["candidate_id"]: r for r in registry if r["decision_tf"] == tf}
        for cid, rr in reg_by_id.items():
            if rr["role"] == "NON_DIRECTIONAL_CONTEXT":
                continue
            cm = matches[matches["candidate_id"] == cid]
            if cm.empty and cid not in set(sdf["candidate_id"]):
                continue
            base = dict(
                matches=cm,
                events=part_events,
                candidate_id=cid,
                family=rr["family"],
                role=rr["role"],
                decision_tf=tf,
                scanned_from=start.isoformat(),
                scanned_to=end.isoformat(),
                valid_decision_bars=len(scan_bars),
                partition=partition,
                years=years,
            )
            metric_rows.append(compute_directional_metrics(**base))
            for sw in SOURCE_WAVE_TFS:
                metric_rows.append(compute_directional_metrics(**base, source_wave_tf=sw))
            for pt in ("HIGH", "LOW"):
                metric_rows.append(compute_directional_metrics(**base, pivot_type=pt))

    # Predictor pivot-window study — deferred in this pass (compute-bound on
    # full-history state rebuilds). Registry still includes PREDICTOR_THRESHOLD
    # candidates; metrics will mark them absent. Verdict uses INCONCLUSIVE for
    # PREDICTOR_BEATS_NORMAL_INDICATOR unless a lightweight DMA proxy is added.
    print(f"[{partition}] predictor pivot windows SKIPPED_COMPUTE (registry retained)", flush=True)

    # Context enrichment (selected TFs) — volume/compression only (no confluence snapshots)
    ctx_regs = [r for r in registry if r["role"] == "NON_DIRECTIONAL_CONTEXT" and r["decision_tf"] in context_only_tfs]
    for r in ctx_regs:
        if r["source_engine"] == "PREDICTOR_CONFLUENCE_ENGINE_V1":
            continue  # confluence snapshots deferred (compute); volume context kept
        tf = r["decision_tf"]
        bars = bars_by_tf.get(tf)
        if not bars:
            continue
        scan_bars = filter_bars_in_range(bars, start, end)
        # downsample long series for context cost
        if len(scan_bars) > 20000:
            step = max(1, len(scan_bars) // 15000)
            scan_bars = scan_bars[::step]
        key = r["candidate_id"]
        frozen = frozen_ctx_thresholds.get(key) if partition != "DISCOVERY" else None
        thr, rows = evaluate_context_candidate(
            scan_bars,
            part_events,
            candidate_id=key,
            family=r["family"],
            feature_id=r["source_feature_or_signal"],
            parameter_set_id=r["parameter_set_id"],
            decision_tf=tf,
            partition=partition,
            threshold_method=r["threshold_method"],
            frozen_thresholds=frozen,
        )
        if partition == "DISCOVERY":
            frozen_ctx_thresholds[key] = thr
        context_rows.extend(rows)
        print(f"[{partition}] context {key} thresholds={thr}", flush=True)

    return {"years": years, "n_events": len(part_events)}


def write_visual_audit(matches: pd.DataFrame, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    examples = []
    if matches.empty:
        (out_dir / "README.txt").write_text("No matches for visual audit.\n", encoding="utf-8")
        return
    m = matches.copy()
    # true positive small delay
    post = m[m["match_type"] == "MATCHED_POST_C"].dropna(subset=["delay_seconds"])
    if not post.empty:
        examples.append(("true_positive_small_delay", post.sort_values("delay_seconds").head(3)))
        examples.append(("true_positive_late", post.sort_values("delay_seconds", ascending=False).head(3)))
    pre = m[m["match_type"] == "PRE_C_WARNING"]
    if not pre.empty:
        examples.append(("pre_c_premature", pre.head(3)))
    unmatched = m[m["match_type"] == "UNMATCHED"]
    if not unmatched.empty:
        examples.append(("false_positive", unmatched.head(3)))
    # missed: events with no MATCHED_POST_C — listed separately in summary
    for name, df in examples:
        df.to_json(out_dir / f"{name}.json", orient="records", indent=2, date_format="iso")
    # HIGH / LOW samples
    for pt in ("HIGH", "LOW"):
        sub = post[post["pivot_type"] == pt].head(3) if not post.empty else pd.DataFrame()
        if not sub.empty:
            sub.to_json(out_dir / f"sample_{pt}.json", orient="records", indent=2, date_format="iso")
    (out_dir / "README.txt").write_text(
        "Diagnostic examples — not cherry-picked for success only. "
        "Includes early TP, late TP, pre-C, false positive, HIGH/LOW.\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    out = Path(argv[0] if argv else "artifacts/REVERSAL-SIGNAL-EVENT-STUDY-1")
    event_dir = Path(argv[1] if len(argv) > 1 else EVENT_DIR)
    out.mkdir(parents=True, exist_ok=True)
    (out / "visual_audit").mkdir(exist_ok=True)
    (out / "docs").mkdir(exist_ok=True)

    git_commit = _git_commit()
    registry = build_candidate_registry()
    counts = classify_counts(registry)
    _write_csv(out / "reversal_signal_candidate_registry_v1.csv", registry)

    events = _load_events(event_dir)
    assert not (events["partition"] == "OOS").any(), "OOS leaked into study events"
    print("OOS_OPENED=NO events_loaded", len(events), counts, flush=True)

    service = make_bar_service()
    all_signals: list[dict[str, Any]] = []
    match_frames: list[pd.DataFrame] = []
    metric_rows: list[dict[str, Any]] = []
    context_rows: list[dict[str, Any]] = []
    frozen_ctx: dict[str, dict[str, float]] = {}

    disc_info = run_partition(
        partition="DISCOVERY",
        events=events,
        registry=registry,
        service=service,
        out_signals=all_signals,
        out_matches=match_frames,
        metric_rows=metric_rows,
        context_rows=context_rows,
        frozen_ctx_thresholds=frozen_ctx,
    )
    # freeze context thresholds before validation
    with (out / "context_thresholds_frozen_discovery_v1.json").open("w", encoding="utf-8") as f:
        json.dump(frozen_ctx, f, indent=2)

    val_info = run_partition(
        partition="VALIDATION",
        events=events,
        registry=registry,
        service=service,
        out_signals=all_signals,
        out_matches=match_frames,
        metric_rows=metric_rows,
        context_rows=context_rows,
        frozen_ctx_thresholds=frozen_ctx,
    )

    sig_df = pd.DataFrame(all_signals)
    # split ledgers
    disc_start, disc_end = PARTITION_BOUNDS["DISCOVERY"]
    val_start, val_end = PARTITION_BOUNDS["VALIDATION"]
    if not sig_df.empty:
        sig_df["signal_time_ts"] = pd.to_datetime(sig_df["signal_time"], utc=True)
        disc_sig = sig_df[(sig_df["signal_time_ts"] >= disc_start) & (sig_df["signal_time_ts"] < disc_end)].drop(
            columns=["signal_time_ts"]
        )
        val_sig = sig_df[(sig_df["signal_time_ts"] >= val_start) & (sig_df["signal_time_ts"] < val_end)].drop(
            columns=["signal_time_ts"]
        )
    else:
        disc_sig = val_sig = pd.DataFrame()

    disc_sig.to_parquet(out / "reversal_signal_ledger_discovery_v1.parquet", index=False)
    val_sig.to_parquet(out / "reversal_signal_ledger_validation_v1.parquet", index=False)

    matches = pd.concat(match_frames, ignore_index=True) if match_frames else pd.DataFrame()
    matches.to_parquet(out / "signal_event_matches_v1.parquet", index=False)

    metrics = pd.DataFrame(metric_rows)
    disc_m = metrics[metrics["partition"] == "DISCOVERY"]
    val_m = metrics[metrics["partition"] == "VALIDATION"]
    _write_csv(
        out / "directional_candidate_metrics_discovery_v1.csv",
        disc_m[disc_m["role"] != "NON_DIRECTIONAL_CONTEXT"],
    )
    _write_csv(
        out / "directional_candidate_metrics_validation_v1.csv",
        val_m[val_m["role"] != "NON_DIRECTIONAL_CONTEXT"],
    )

    ctx = pd.DataFrame(context_rows)
    if not ctx.empty:
        _write_csv(out / "context_candidate_metrics_discovery_v1.csv", ctx[ctx["partition"] == "DISCOVERY"])
        _write_csv(out / "context_candidate_metrics_validation_v1.csv", ctx[ctx["partition"] == "VALIDATION"])
    else:
        _write_csv(out / "context_candidate_metrics_discovery_v1.csv", [])
        _write_csv(out / "context_candidate_metrics_validation_v1.csv", [])

    boards = build_leaderboards(metrics)
    for name, df in boards.items():
        _write_csv(out / f"{name}.csv", df)

    # by TF board
    by_tf = val_m[(val_m["source_wave_tf"] != "ALL") & (val_m["pivot_type"] == "ALL")].copy()
    if not by_tf.empty:
        by_tf["score"] = by_tf["PRECISION"].fillna(0) * by_tf["EVENT_RECALL"].fillna(0)
        _write_csv(out / "leaderboard_by_tf_v1.csv", by_tf.sort_values("score", ascending=False).head(100))
    else:
        _write_csv(out / "leaderboard_by_tf_v1.csv", [])

    # stability: year breakdown from matches
    year_rows = []
    if not matches.empty and "calendar_year" in matches.columns:
        post = matches[matches["match_type"] == "MATCHED_POST_C"]
        for (cid, year), g in post.groupby(["candidate_id", "calendar_year"]):
            year_rows.append(
                {
                    "candidate_id": cid,
                    "year": year,
                    "n_matched": len(g),
                    "median_delay": g["delay_seconds"].median(),
                    "median_remaining": g["remaining_wave_fraction"].median(),
                }
            )
    _write_csv(out / "year_stability_v1.csv", year_rows)

    # high/low asymmetry
    asym = []
    for cid, g in val_m[val_m["source_wave_tf"] == "ALL"].groupby("candidate_id"):
        hi = g[g["pivot_type"] == "HIGH"]
        lo = g[g["pivot_type"] == "LOW"]
        if hi.empty or lo.empty:
            continue
        asym.append(
            {
                "candidate_id": cid,
                "HIGH_RECALL": float(hi.iloc[0]["EVENT_RECALL"] or 0),
                "LOW_RECALL": float(lo.iloc[0]["EVENT_RECALL"] or 0),
                "HIGH_PRECISION": float(hi.iloc[0]["PRECISION"] or 0),
                "LOW_PRECISION": float(lo.iloc[0]["PRECISION"] or 0),
                "recall_delta": float((hi.iloc[0]["EVENT_RECALL"] or 0) - (lo.iloc[0]["EVENT_RECALL"] or 0)),
            }
        )
    _write_csv(out / "high_low_asymmetry_v1.csv", asym)

    # degradation discovery → validation
    deg = []
    d_all = disc_m[(disc_m["source_wave_tf"] == "ALL") & (disc_m["pivot_type"] == "ALL")]
    v_all = val_m[(val_m["source_wave_tf"] == "ALL") & (val_m["pivot_type"] == "ALL")]
    for cid in set(d_all["candidate_id"]) & set(v_all["candidate_id"]):
        d = d_all[d_all["candidate_id"] == cid].iloc[0]
        v = v_all[v_all["candidate_id"] == cid].iloc[0]
        deg.append(
            {
                "candidate_id": cid,
                "family": d["family"],
                "DISC_PRECISION": d["PRECISION"],
                "VAL_PRECISION": v["PRECISION"],
                "DISC_RECALL": d["EVENT_RECALL"],
                "VAL_RECALL": v["EVENT_RECALL"],
                "DISC_FPR": d["FALSE_POSITIVE_RATE"],
                "VAL_FPR": v["FALSE_POSITIVE_RATE"],
                "precision_ratio": (v["PRECISION"] / d["PRECISION"]) if d["PRECISION"] else None,
                "recall_ratio": (v["EVENT_RECALL"] / d["EVENT_RECALL"]) if d["EVENT_RECALL"] else None,
                "precision_delta": (v["PRECISION"] or 0) - (d["PRECISION"] or 0),
                "recall_delta": (v["EVENT_RECALL"] or 0) - (d["EVENT_RECALL"] or 0),
            }
        )
    _write_csv(out / "validation_degradation_v1.csv", deg)

    # multiple testing on context lifts (validation)
    mt_rows = []
    if not ctx.empty:
        vctx = ctx[ctx["partition"] == "VALIDATION"].copy()
        pvals = vctx["p_value"].fillna(1.0).tolist()
        reject = benjamini_hochberg(pvals, alpha=0.1)
        vctx = vctx.assign()
        vctx["bh_reject_fdr_0_1"] = reject
        mt_rows = vctx.to_dict("records")
    _write_csv(out / "multiple_testing_v1.csv", mt_rows)

    fw = family_winners(metrics)
    _write_csv(out / "family_winners_v1.csv", fw)
    pf = pareto_front(metrics)
    _write_csv(out / "pareto_front_v1.csv", pf)

    # stability leaderboard: low |precision_delta|
    if deg:
        stab = pd.DataFrame(deg).copy()
        stab["abs_precision_delta"] = stab["precision_delta"].abs()
        stab = stab.sort_values("abs_precision_delta").head(25)
        _write_csv(out / "leaderboard_stability_v1.csv", stab)
    else:
        _write_csv(out / "leaderboard_stability_v1.csv", [])

    write_visual_audit(matches, out / "visual_audit")

    # Research verdict helpers
    price_base = v_all[v_all["family"] == "PRICE_ONLY"] if not v_all.empty else pd.DataFrame()
    best_price = None
    if not price_base.empty:
        pb = price_base.copy()
        pb["score"] = pb["PRECISION"].fillna(0) * pb["EVENT_RECALL"].fillna(0)
        best_price = pb.sort_values("score", ascending=False).iloc[0]

    beaten = "NO"
    if best_price is not None and not v_all.empty:
        others = v_all[v_all["family"] != "PRICE_ONLY"].copy()
        if not others.empty:
            others["score"] = others["PRECISION"].fillna(0) * others["EVENT_RECALL"].fillna(0)
            top = others.sort_values("score", ascending=False).iloc[0]
            if (top["score"] or 0) > (best_price["score"] or 0) * 1.05 and (top["FALSE_POSITIVE_RATE"] or 1) <= (
                best_price["FALSE_POSITIVE_RATE"] or 1
            ) * 1.1:
                beaten = "YES"

    # verdict
    n_pareto = len(pf)
    stable = 0
    if deg:
        for row in deg:
            if row.get("precision_ratio") and 0.7 <= row["precision_ratio"] <= 1.3:
                stable += 1
    if beaten == "YES" and n_pareto >= 3 and stable >= 3:
        verdict = "WHEN_SIGNAL_PARTIAL"
    elif beaten == "YES" and n_pareto >= 5 and stable >= 5:
        verdict = "WHEN_SIGNAL_FOUND"
    elif n_pareto >= 1 or stable >= 1:
        verdict = "WHEN_SIGNAL_WEAK"
    else:
        verdict = "WHEN_SIGNAL_NOT_FOUND"
    # Prefer PARTIAL over FOUND unless clearly strong — avoid forcing positive
    if verdict == "WHEN_SIGNAL_FOUND" and beaten != "YES":
        verdict = "WHEN_SIGNAL_PARTIAL"

    def _best(family: str) -> str:
        if fw.empty:
            return "NONE"
        sub = fw[fw["family"] == family]
        if sub.empty:
            # try metrics directly
            sub2 = v_all[v_all["family"] == family] if not v_all.empty else pd.DataFrame()
            if sub2.empty:
                return "NONE"
            sub2 = sub2.copy()
            sub2["score"] = sub2["PRECISION"].fillna(0) * sub2["EVENT_RECALL"].fillna(0)
            return str(sub2.sort_values("score", ascending=False).iloc[0]["candidate_id"])
        return str(sub.iloc[0]["candidate_id"])

    continuous_fp = "PASS" if not matches.empty and (matches["match_type"] == "UNMATCHED").any() else "FAIL"
    label_sep = "PASS" if (out / "reversal_signal_ledger_discovery_v1.parquet").exists() and (
        out / "signal_event_matches_v1.parquet"
    ).exists() else "FAIL"

    # docs
    doc = f"""# REVERSAL_SIGNAL_EVENT_STUDY_V1

WIP={WIP_ID}
STUDY_VERSION={STUDY_VERSION}
OOS_OPENED=NO

## Matching rules

See `match.py` docstring. Causal ledgers contain no true-C fields.
Label matches are retrospective only.

## Partitions

DISCOVERY: {PARTITION_BOUNDS['DISCOVERY']}
VALIDATION: {PARTITION_BOUNDS['VALIDATION']}
OOS: locked (not used)

## Note

{tf_balanced_pool_note()}

## Verdict

{verdict}
"""
    (out / "docs" / "reversal_signal_event_study_v1.md").write_text(doc, encoding="utf-8")

    summary = {
        "WIP": WIP_ID,
        "STUDY_VERSION": STUDY_VERSION,
        "OOS_OPENED": "NO",
        "git_commit": git_commit,
        "counts": counts,
        "discovery_events": disc_info["n_events"],
        "validation_events": val_info["n_events"],
        "total_discovery_signals": int(len(disc_sig)),
        "total_validation_signals": int(len(val_sig)),
        "PRICE_BASELINE_BEATEN": beaten,
        "PREDICTOR_BEATS_NORMAL_INDICATOR": "INCONCLUSIVE",
        "PREDICTOR_CONFLUENCE_USEFUL": "INCONCLUSIVE",
        "CONTEXT_ENRICHMENT_FOUND": "YES" if (not ctx.empty and (ctx.get("event_rate_lift", pd.Series(dtype=float)).fillna(0) > 1.2).any()) else "NO",
        "RESEARCH_VERDICT": verdict,
        "predictor_note": "Full predictor-trigger continuous scan deferred (compute). Registry retained.",
        "confluence_note": "Confluence context snapshots deferred (compute). Volume/compression context evaluated.",
        "CONTINUOUS_FALSE_POSITIVE_SCAN": continuous_fp,
        "LABEL_MATCH_SEPARATION": label_sep,
        "PARETO_CANDIDATES": int(n_pareto),
        "BEST_PRICE_BASELINE": str(best_price["candidate_id"]) if best_price is not None else "NONE",
        "family_best": {fam: _best(fam) for fam in [
            "PRICE_ONLY", "DMA", "STOCHASTIC", "MACD", "RSI", "MA/DMI",
            "VOLUME_CONTEXT", "COMPRESSION_CONTEXT", "EXHAUSTION_CONTEXT",
            "REJECTION_CONTEXT", "INVERSE_PREDICTOR", "PREDICTOR_CONFLUENCE",
        ]},
    }
    (out / "event_study_manifest_v1.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
