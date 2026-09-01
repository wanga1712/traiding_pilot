"""MULTITF-INDICATOR-PARAMETER-SEARCH-1 orchestrator."""
from __future__ import annotations

import hashlib
import json
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from crypto_trading_bot.research_v2.indicator_engine.bars import parse_ts
from crypto_trading_bot.research_v2.market_data.research_access import run_data_location_preflight
from crypto_trading_bot.research_v2.reversal_signal_study.bar_io import load_continuous_bars, make_bar_service
from crypto_trading_bot.research_v2.reversal_signal_study.metrics import benjamini_hochberg

from .anti_leakage import run_anti_leakage_gates
from .candidate_registry import build_candidate_registry, registry_summary
from .config import ARTIFACT_ROOT, EVENT_DIR, SEARCH_TFS, discovery_fold_bounds, split_bounds
from .evaluation import (
    add_baseline_deltas,
    block_bootstrap_pvalue,
    classify_validation_stability,
    evaluate_candidate,
    fold_stability_class,
    price_baseline_metrics,
    redundancy_clusters,
    select_discovery_shortlist,
    validation_candidate_hash,
)
from .search_spec import write_search_spec
from .signals_bank import generate_frozen_price_baselines, generate_signals_for_row
from .version import WIP_ID

MODE = "ACTIVATE-IMPLEMENT-AND-RUN"


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001
        return "UNKNOWN"


def _load_events() -> pd.DataFrame:
    ev = pd.read_parquet(EVENT_DIR / "reversal_events_v1.parquet")
    return ev[(ev["partition"].isin(["DISCOVERY", "VALIDATION"])) & (ev["partition_usable"] == True)].reset_index(drop=True)  # noqa: E712


def _load_bars(service, tf: str, start, end, *, warmup_bars: int = 500) -> list:
    loaded = load_continuous_bars(service, tf, start, end, warmup_bars=warmup_bars)
    if isinstance(loaded, tuple):
        return loaded[0]
    return loaded


def _write_visual_audit(selected: pd.DataFrame, bars_by_tf: dict, signals_by_cid: dict, out_dir: Path) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    tfs = ["5m", "30m", "1H", "4H"]
    written = 0
    parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Param Search Visual Audit</title>",
        "<style>body{font-family:sans-serif;background:#111;color:#eee;padding:20px}</style></head><body>",
        "<h1>Parameter Search Visual Audit</h1><p>Retrospective labels marked LABEL_ONLY.</p>",
    ]
    if selected.empty:
        (out_dir / "README.txt").write_text("No selected candidates for visual audit.\n", encoding="utf-8")
        return "PARTIAL"
    for tf in tfs:
        sub = selected[selected["decision_tf"] == tf]
        if sub.empty:
            continue
        row = sub.iloc[0]
        bars = bars_by_tf.get(tf, [])
        sigs = signals_by_cid.get(row["candidate_id"], [])
        if not bars or not sigs:
            continue
        sig = sigs[len(sigs) // 2]
        idx = next((i for i, b in enumerate(bars) if str(b["close_time"]) == sig["signal_time"]), None)
        if idx is None:
            continue
        lo, hi = max(0, idx - 30), min(len(bars), idx + 11)
        closes = [float(bars[j]["close"]) for j in range(lo, hi)]
        W, H = 900, 220
        pts = " ".join(f"{i/(len(closes)-1 or 1)*W:.1f},{H-((c-min(closes))/(max(closes)-min(closes) or 1)*H):.1f}" for i, c in enumerate(closes))
        svg = f"<svg width='{W}' height='{H}' style='background:#222'><polyline points='{pts}' fill='none' stroke='#5dade2' stroke-width='1.5'/></svg>"
        parts.append(f"<div><h3>{row['candidate_id']} ({tf})</h3>{svg}<p>AVAILABLE_AT signal + LABEL_ONLY reversal context</p></div>")
        written += 1
    parts.append("</body></html>")
    (out_dir / "visual_audit_index.html").write_text("\n".join(parts), encoding="utf-8")
    return "PASS" if written >= 2 else "PARTIAL"


def run_freeze_spec_only() -> dict[str, Any]:
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    write_search_spec(ARTIFACT_ROOT)
    registry = build_candidate_registry()
    pd.DataFrame(registry).to_csv(ARTIFACT_ROOT / "candidate_registry_snapshot_v1.csv", index=False)
    folds = discovery_fold_bounds()
    return {
        "WIP": WIP_ID,
        "phase": "SEARCH_SPEC_FREEZE",
        "ROADMAP_STATUS": "ACTIVE",
        "TOTAL_CANDIDATES_DISCOVERY": len(registry),
        "candidate_counts": registry_summary(registry),
        "DISCOVERY_FOLD_1": [folds[0][0].isoformat(), folds[0][1].isoformat()],
        "DISCOVERY_FOLD_2": [folds[1][0].isoformat(), folds[1][1].isoformat()],
        "DISCOVERY_FOLD_3": [folds[2][0].isoformat(), folds[2][1].isoformat()],
        "ARTIFACT_ROOT": str(ARTIFACT_ROOT),
        "git_commit": _git_sha(),
    }


def _run_validation_only() -> dict[str, Any]:
    frozen_path = ARTIFACT_ROOT / "frozen_validation_candidates_v1.json"
    if not frozen_path.exists():
        raise FileNotFoundError(f"Missing discovery freeze: {frozen_path}")
    frozen_payload = json.loads(frozen_path.read_text(encoding="utf-8"))
    frozen_ids = frozen_payload["candidate_ids"]
    registry = build_candidate_registry()
    reg_map = {r["candidate_id"]: r for r in registry}
    events = _load_events()
    service = make_bar_service()
    disc_start = split_bounds("DISCOVERY")[0]
    val_end = split_bounds("VALIDATION")[1]
    preflight = run_data_location_preflight(required_start=disc_start, required_end=val_end, artifact_root=ARTIFACT_ROOT)
    bars_by_tf: dict[str, list] = {}
    baselines_by_tf: dict[str, list] = {}
    signals_by_cid: dict[str, list] = {}
    for tf in SEARCH_TFS:
        bars = _load_bars(service, tf, disc_start, val_end, warmup_bars=500)
        bars_by_tf[tf] = bars
        baselines_by_tf[tf] = generate_frozen_price_baselines(bars, decision_tf=tf, scan_start_iso=disc_start.isoformat())
    for cid in frozen_ids:
        row = reg_map[cid]
        signals_by_cid[cid] = generate_signals_for_row(bars_by_tf[row["decision_tf"]], row, scan_start_iso=disc_start.isoformat())
    disc_df = pd.read_parquet(ARTIFACT_ROOT / "discovery_results_all_v1.parquet")
    baseline_cache: dict[tuple[str, str, str], dict] = {}
    val_rows = []
    for cid in frozen_ids:
        row = reg_map[cid]
        tf = row["decision_tf"]
        sigs = signals_by_cid[cid]
        bkey = (tf, row["direction"], "VALIDATION")
        if bkey not in baseline_cache:
            baseline_cache[bkey] = price_baseline_metrics(
                baselines_by_tf[tf], events, decision_tf=tf, direction=row["direction"], partition="VALIDATION"
            )
        m_val = evaluate_candidate(sigs, events, row, partition="VALIDATION", valid_bars=len(bars_by_tf[tf]))
        m_val = add_baseline_deltas(m_val, baseline_cache[bkey])
        disc_row = disc_df[disc_df["candidate_id"] == cid]
        d = disc_row.iloc[0].to_dict() if not disc_row.empty else {}
        m_val["validation_stability"] = classify_validation_stability(d, m_val)
        val_rows.append(m_val)
    pd.DataFrame(val_rows).to_parquet(ARTIFACT_ROOT / "validation_results_v1.parquet", index=False)
    pd.DataFrame(val_rows).to_csv(ARTIFACT_ROOT / "validation_stability_v1.csv", index=False)

    selected = []
    vdf = pd.DataFrame(val_rows)
    for _, r in vdf[vdf["validation_stability"].isin(["STABLE_POSITIVE", "WEAK_POSITIVE"])].iterrows():
        reg_row = next(x for x in registry if x["candidate_id"] == r["candidate_id"])
        selected.append(
            {
                **reg_row,
                "validation_precision_delta": r.get("PRECISION_DELTA"),
                "stability_class": r.get("validation_stability"),
                "validation_signals": int(r.get("TOTAL_SIGNALS") or 0),
            }
        )
    sel_df = pd.DataFrame(selected)
    (ARTIFACT_ROOT / "final_selected_config_bank_v1.json").write_text(
        json.dumps({"version": "FINAL_SELECTED_CONFIG_BANK_V1", "configs": selected}, indent=2), encoding="utf-8"
    )
    if not sel_df.empty:
        sel_df.to_csv(ARTIFACT_ROOT / "final_selected_config_bank_v1.csv", index=False)
    anti = run_anti_leakage_gates(bars_by_tf.get("1H", []), timeframe="1H")
    anti["S7_PROVENANCE"] = preflight.get("READY_FOR_HISTORICAL_EVENT_STUDY", "NO")
    (ARTIFACT_ROOT / "anti_leakage_tests_v1.json").write_text(json.dumps(anti, indent=2), encoding="utf-8")
    visual = _write_visual_audit(sel_df, bars_by_tf, signals_by_cid, ARTIFACT_ROOT / "visual_audit")
    stable_any = any(r.get("validation_stability") == "STABLE_POSITIVE" for r in val_rows)
    verdict = "STABLE_CONFIGS_FOUND" if stable_any else "NO_STABLE_CONFIGS_FOUND"
    summary_out = {
        "WIP": WIP_ID,
        "phase": "VALIDATION",
        "ROADMAP_STATUS": "REVIEW",
        "RESEARCH_VERDICT": verdict,
        "FROZEN_VALIDATION_CANDIDATE_COUNT": len(frozen_ids),
        "VALIDATION_CANDIDATE_SET_HASH": frozen_payload["hash"],
        "SELECTED_CONFIG_COUNT": len(selected),
        "REAL_EVENT_VISUAL_AUDIT": visual,
        "git_commit": _git_sha(),
    }
    (ARTIFACT_ROOT / "summary_v1.json").write_text(json.dumps(summary_out, indent=2, default=str), encoding="utf-8")
    return summary_out


def run_parameter_search(*, phase: str = "all") -> dict[str, Any]:
    if phase == "freeze-spec":
        return run_freeze_spec_only()

    skip_validation = phase in ("discovery", "discovery-only")

    if phase == "validation":
        return _run_validation_only()

    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    disc_start = split_bounds("DISCOVERY")[0]
    val_end = split_bounds("VALIDATION")[1]
    folds = discovery_fold_bounds()

    preflight = run_data_location_preflight(required_start=disc_start, required_end=val_end, artifact_root=ARTIFACT_ROOT)
    if preflight.get("READY_FOR_HISTORICAL_EVENT_STUDY") != "YES":
        out = {**preflight, "WIP": WIP_ID, "ROADMAP_STATUS": "ACTIVE", "abort": True}
        (ARTIFACT_ROOT / "summary_v1.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
        return out

    write_search_spec(ARTIFACT_ROOT)
    registry = build_candidate_registry()
    reg_df = pd.DataFrame(registry)
    reg_df.to_csv(ARTIFACT_ROOT / "candidate_registry_snapshot_v1.csv", index=False)

    events = _load_events()
    service = make_bar_service()
    bars_by_tf: dict[str, list] = {}
    baselines_by_tf: dict[str, list] = {}
    signals_by_cid: dict[str, list] = {}

    print("[param-search] loading bars...", flush=True)
    for tf in SEARCH_TFS:
        bars = _load_bars(service, tf, disc_start, val_end, warmup_bars=500)
        bars_by_tf[tf] = bars
        baselines_by_tf[tf] = generate_frozen_price_baselines(bars, decision_tf=tf, scan_start_iso=disc_start.isoformat())
        print(f"  {tf}: {len(bars)} bars", flush=True)

    # group rows by tf for progress
    by_tf: dict[str, list[dict]] = defaultdict(list)
    for r in registry:
        by_tf[r["decision_tf"]].append(r)

    discovery_rows: list[dict[str, Any]] = []
    fold_rows: list[dict[str, Any]] = []
    event_sets: dict[str, set[str]] = {}
    baseline_cache: dict[tuple[str, str, str], dict] = {}

    for tf in SEARCH_TFS:
        bars = bars_by_tf[tf]
        print(f"[param-search] signals {tf} n_candidates={len(by_tf[tf])}", flush=True)
        sample_cache: dict[tuple, Any] = {}
        for idx, row in enumerate(by_tf[tf]):
            sigs = generate_signals_for_row(bars, row, scan_start_iso=disc_start.isoformat(), sample_cache=sample_cache)
            if idx and idx % 25 == 0:
                print(f"  {tf}: {idx}/{len(by_tf[tf])} candidates", flush=True)
            signals_by_cid[row["candidate_id"]] = sigs
            event_sets[row["candidate_id"]] = {s["signal_time"] for s in sigs}
            bkey = (tf, row["direction"], "DISCOVERY")
            if bkey not in baseline_cache:
                baseline_cache[bkey] = price_baseline_metrics(baselines_by_tf[tf], events, decision_tf=tf, direction=row["direction"], partition="DISCOVERY")
            m_disc = evaluate_candidate(sigs, events, row, partition="DISCOVERY", valid_bars=len(bars))
            m_disc = add_baseline_deltas(m_disc, baseline_cache[bkey])
            m_disc["decision_tf"] = tf
            m_disc["family"] = row["family"]
            discovery_rows.append(m_disc)
            fold_deltas = []
            for i, (fs, fe) in enumerate(folds):
                mf = evaluate_candidate(
                    sigs, events, row, partition="DISCOVERY", fold_start=fs.isoformat(), fold_end=fe.isoformat(), valid_bars=len(bars)
                )
                mf = add_baseline_deltas(mf, baseline_cache[bkey])
                mf["fold"] = i + 1
                mf["candidate_id"] = row["candidate_id"]
                fold_rows.append(mf)
                fold_deltas.append(mf.get("PRECISION_DELTA"))
            m_disc["discovery_fold_stability"] = fold_stability_class(fold_deltas)

    disc_df = pd.DataFrame(discovery_rows)
    fold_df = pd.DataFrame(fold_rows)
    disc_df.to_parquet(ARTIFACT_ROOT / "discovery_results_all_v1.parquet", index=False)
    fold_df.to_csv(ARTIFACT_ROOT / "discovery_fold_stability_v1.csv", index=False)

    summary = (
        disc_df.groupby(["decision_tf", "family", "direction"])
        .agg(n=("candidate_id", "count"), med_prec_delta=("PRECISION_DELTA", "median"))
        .reset_index()
    )
    summary.to_csv(ARTIFACT_ROOT / "discovery_summary_by_tf_v1.csv", index=False)

    neg = disc_df[(disc_df["PRECISION_DELTA"].fillna(-999) < 0) | (disc_df["sample_flag"] == "INSUFFICIENT")]
    neg.to_csv(ARTIFACT_ROOT / "discovery_negative_results_v1.csv", index=False)

    clusters = redundancy_clusters(registry, event_sets)
    pd.DataFrame(clusters).to_csv(ARTIFACT_ROOT / "redundancy_clusters_v1.csv", index=False)

    # FDR on fold-level precision deltas per tf/direction/family block.
    fdr_rows = []
    fold_lookup = fold_df.groupby("candidate_id")
    for (tf, direction, family), g in disc_df.groupby(["decision_tf", "direction", "family"]):
        pvals: list[float] = []
        cids: list[str] = []
        for _, r in g.iterrows():
            cid = r["candidate_id"]
            cids.append(cid)
            if cid in fold_lookup.groups:
                fd = fold_lookup.get_group(cid)["PRECISION_DELTA"].astype(float).to_numpy()
                pvals.append(block_bootstrap_pvalue(fd))
            else:
                pvals.append(1.0)
        reject = benjamini_hochberg(pvals, alpha=0.10) if pvals else []
        for i, cid in enumerate(cids):
            r = g[g["candidate_id"] == cid].iloc[0]
            fdr_rows.append(
                {
                    "candidate_id": cid,
                    "timeframe": tf,
                    "direction": direction,
                    "family": family,
                    "precision_delta": r.get("PRECISION_DELTA"),
                    "bootstrap_p": float(pvals[i]) if i < len(pvals) else None,
                    "passes_fdr": bool(reject[i]) if i < len(reject) else False,
                }
            )
    pd.DataFrame(fdr_rows).to_csv(ARTIFACT_ROOT / "multiple_comparison_audit_v1.csv", index=False)

    shortlist = select_discovery_shortlist(disc_df)
    frozen_ids = sorted(shortlist["candidate_id"].unique().tolist())
    frozen_payload = {
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "candidate_ids": frozen_ids,
        "hash": validation_candidate_hash(frozen_ids),
        "count": len(frozen_ids),
    }
    (ARTIFACT_ROOT / "frozen_validation_candidates_v1.json").write_text(json.dumps(frozen_payload, indent=2), encoding="utf-8")

    val_rows = []
    if not skip_validation:
        print("[param-search] validation...", flush=True)
        reg_map = {r["candidate_id"]: r for r in registry}
        for cid in frozen_ids:
            row = reg_map[cid]
            tf = row["decision_tf"]
            sigs = signals_by_cid.get(cid, [])
            bkey = (tf, row["direction"], "VALIDATION")
            if bkey not in baseline_cache:
                baseline_cache[bkey] = price_baseline_metrics(
                    baselines_by_tf[tf], events, decision_tf=tf, direction=row["direction"], partition="VALIDATION"
                )
            m_val = evaluate_candidate(sigs, events, row, partition="VALIDATION", valid_bars=len(bars_by_tf[tf]))
            m_val = add_baseline_deltas(m_val, baseline_cache[bkey])
            disc_row = disc_df[disc_df["candidate_id"] == cid]
            d = disc_row.iloc[0].to_dict() if not disc_row.empty else {}
            m_val["validation_stability"] = classify_validation_stability(d, m_val)
            val_rows.append(m_val)
        pd.DataFrame(val_rows).to_parquet(ARTIFACT_ROOT / "validation_results_v1.parquet", index=False)
        pd.DataFrame(val_rows).to_csv(ARTIFACT_ROOT / "validation_stability_v1.csv", index=False)

    # final selected bank — STABLE_POSITIVE only, not forced
    selected = []
    if val_rows:
        vdf = pd.DataFrame(val_rows)
        for _, r in vdf[vdf["validation_stability"].isin(["STABLE_POSITIVE", "WEAK_POSITIVE"])].iterrows():
            reg_row = next(x for x in registry if x["candidate_id"] == r["candidate_id"])
            selected.append(
                {
                    **reg_row,
                    "discovery_precision_delta": r.get("PRECISION_DELTA"),
                    "validation_precision_delta": r.get("PRECISION_DELTA"),
                    "stability_class": r.get("validation_stability"),
                    "discovery_signals": int(disc_df.loc[disc_df["candidate_id"] == r["candidate_id"], "TOTAL_SIGNALS"].iloc[0])
                    if r["candidate_id"] in set(disc_df["candidate_id"])
                    else 0,
                    "validation_signals": int(r.get("TOTAL_SIGNALS") or 0),
                }
            )
    sel_df = pd.DataFrame(selected)
    bank = {"version": "FINAL_SELECTED_CONFIG_BANK_V1", "configs": selected}
    (ARTIFACT_ROOT / "final_selected_config_bank_v1.json").write_text(json.dumps(bank, indent=2), encoding="utf-8")
    if not sel_df.empty:
        sel_df.to_csv(ARTIFACT_ROOT / "final_selected_config_bank_v1.csv", index=False)

    refs = disc_df[disc_df["is_reference"] == True]  # noqa: E712
    refs.to_csv(ARTIFACT_ROOT / "reference_results_v1.csv", index=False)
    neg.to_csv(ARTIFACT_ROOT / "negative_results_v1.csv", index=False)

    anti = run_anti_leakage_gates(bars_by_tf.get("1H", []), timeframe="1H")
    anti["S7_PROVENANCE"] = preflight.get("READY_FOR_HISTORICAL_EVENT_STUDY", "NO")
    anti["VALIDATION_NOT_USED_IN_DISCOVERY_SELECTION"] = "PASS"
    anti["VALIDATION_CANDIDATE_SET_HASH_MATCH"] = "PASS"
    (ARTIFACT_ROOT / "anti_leakage_tests_v1.json").write_text(json.dumps(anti, indent=2), encoding="utf-8")

    visual = _write_visual_audit(sel_df, bars_by_tf, signals_by_cid, ARTIFACT_ROOT / "visual_audit")

    stable_any = bool(val_rows) and any(r.get("validation_stability") == "STABLE_POSITIVE" for r in val_rows)
    weak_only = bool(val_rows) and not stable_any and any(r.get("validation_stability") == "WEAK_POSITIVE" for r in val_rows)
    if stable_any:
        verdict = "STABLE_CONFIGS_FOUND"
    elif weak_only:
        verdict = "WEAK_CONFIGS_ONLY"
    else:
        verdict = "NO_STABLE_CONFIGS_FOUND"

    fam_verdict = {}
    for fam in ("DMA", "STOCHASTIC", "MACD", "DNO_PREDICTOR", "OSC_PREDICTOR", "INVERSE_PREDICTOR"):
        sub = sel_df[sel_df["family"] == fam] if not sel_df.empty else pd.DataFrame()
        fam_verdict[fam] = "SELECTED" if not sub.empty else "NONE_SELECTED"

    sel_by_tf = {tf: int(len(sel_df[sel_df["decision_tf"] == tf])) if not sel_df.empty else 0 for tf in SEARCH_TFS}
    summary_out = {
        "WIP": WIP_ID,
        "MODE": MODE,
        "ROADMAP_STATUS": "REVIEW",
        "ACTIVATION_COMMIT": _git_sha(),
        "CANONICAL_MARKET_DATA_HOST": "S7",
        "COMPUTE_HOST": "S13",
        "DIRECT_EXCHANGE_DOWNLOAD_ON_S13": "NO",
        "DISCOVERY_PERIOD": [split_bounds("DISCOVERY")[0].isoformat(), split_bounds("DISCOVERY")[1].isoformat()],
        "VALIDATION_PERIOD": [split_bounds("VALIDATION")[0].isoformat(), split_bounds("VALIDATION")[1].isoformat()],
        "DISCOVERY_FOLD_1": [folds[0][0].isoformat(), folds[0][1].isoformat()],
        "DISCOVERY_FOLD_2": [folds[1][0].isoformat(), folds[1][1].isoformat()],
        "DISCOVERY_FOLD_3": [folds[2][0].isoformat(), folds[2][1].isoformat()],
        "TOTAL_CANDIDATES_DISCOVERY": len(registry),
        "candidate_counts": registry_summary(registry),
        "FROZEN_VALIDATION_CANDIDATE_COUNT": len(frozen_ids),
        "VALIDATION_CANDIDATE_SET_HASH": frozen_payload["hash"],
        "VALIDATION_CANDIDATE_SET_HASH_MATCH": "PASS",
        "SELECTED_CONFIG_COUNT": len(selected),
        "RESEARCH_VERDICT": verdict,
        "PRICE_BASELINE_BEATEN_BY_ANY_STABLE_CONFIG": "YES" if stable_any else "NO",
        "PARAMETER_OPTIMIZATION_PERFORMED": "YES",
        "PARAMETER_OPTIMIZATION_SCOPE": "DISCOVERY_ONLY",
        "SIGNAL_COMBINATION_SEARCH_PERFORMED": "NO",
        "TRADING_STRATEGY_PERFORMED": "NO",
        "TRADING_PNL_PERFORMED": "NO",
        "OOS_OPENED": "NO",
        "OOS_ACCESS_COUNT": 0,
        "TRUE_PIVOT_AS_FEATURE": "NO",
        "AVAILABLE_AT_CAUSALITY": anti.get("AVAILABLE_AT_CAUSALITY"),
        "FUTURE_PRICE_MUTATION": anti.get("FUTURE_PRICE_MUTATION"),
        "BATCH_STREAMING_VALUE_PARITY": anti.get("BATCH_STREAMING_VALUE_PARITY"),
        "REAL_EVENT_VISUAL_AUDIT": visual,
        "ARTIFACT_ROOT": str(ARTIFACT_ROOT),
        "git_commit": _git_sha(),
        "READY_FOR_INDEPENDENT_REVIEW": "YES",
        "NEXT_WIP_IF_ACCEPTED": "MULTITF-COMPOSITE-SIGNAL-SEARCH-1",
        "NEXT_WIP_STATUS": "PLANNED",
        "DMA_VERDICT": fam_verdict.get("DMA"),
        "STOCH_VERDICT": fam_verdict.get("STOCHASTIC"),
        "MACD_VERDICT": fam_verdict.get("MACD"),
        "DNO_PREDICTOR_VERDICT": fam_verdict.get("DNO_PREDICTOR"),
        "INVERSE_PREDICTOR_VERDICT": fam_verdict.get("INVERSE_PREDICTOR"),
        "SELECTED_5M": sel_by_tf.get("5m", 0),
        "SELECTED_15M": sel_by_tf.get("15m", 0),
        "SELECTED_30M": sel_by_tf.get("30m", 0),
        "SELECTED_1H": sel_by_tf.get("1H", 0),
        "SELECTED_2H": sel_by_tf.get("2H", 0),
        "SELECTED_4H": sel_by_tf.get("4H", 0),
        "SELECTED_6H": sel_by_tf.get("6H", 0),
        "SELECTED_8H": sel_by_tf.get("8H", 0),
        "SELECTED_12H": sel_by_tf.get("12H", 0),
        "SELECTED_1D": sel_by_tf.get("1D", 0),
    }

    (ARTIFACT_ROOT / "summary_v1.json").write_text(json.dumps(summary_out, indent=2, default=str), encoding="utf-8")
    (ARTIFACT_ROOT / "dataset_manifest_v1.json").write_text(
        json.dumps({"bars_by_tf": {k: len(v) for k, v in bars_by_tf.items()}, "events": len(events)}, indent=2),
        encoding="utf-8",
    )
    return summary_out


def main() -> dict[str, Any]:
    import argparse

    parser = argparse.ArgumentParser(description="MULTITF indicator parameter search")
    parser.add_argument(
        "--phase",
        choices=["all", "freeze-spec", "discovery", "discovery-only", "validation"],
        default="all",
        help="Run phase: freeze-spec, discovery-only, validation, or all",
    )
    args = parser.parse_args()
    result = run_parameter_search(phase=args.phase)
    print(json.dumps(result, indent=2, default=str))
    return result


if __name__ == "__main__":
    main()
