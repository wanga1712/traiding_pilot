"""MULTITF-COMPOSITE-SIGNAL-SEARCH-1 orchestrator CLI."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from crypto_trading_bot.research_v2.indicator_parameter_search.signals_bank import (
    generate_frozen_price_baselines,
)
from crypto_trading_bot.research_v2.market_data.research_access import run_data_location_preflight
from crypto_trading_bot.research_v2.reversal_signal_study.bar_io import load_continuous_bars, make_bar_service

from . import MODE, WIP_ID
from .atomic_replay import (
    load_stream_cache,
    replay_atomic_bank,
    run_validation_parity,
    write_representative_artifacts,
)
from .classify import (
    classify_composite,
    classification_payload,
    count_positive_precision_delta_folds,
    count_usable_folds,
)
from .compose import expand_all_templates
from .config import (
    ARTIFACT_ROOT,
    COMPOSITE_FDR_STATUS,
    DEVELOPMENT_END,
    DEVELOPMENT_FOLDS,
    DEVELOPMENT_START,
    EVENT_DIR,
    OOS_OPENED,
    PARENT_ARTIFACT_ROOT,
    SEARCH_TFS,
    load_atomic_bank,
    load_development_corpus_manifest,
    load_search_spec,
    load_templates,
)
from .evaluate_window import evaluate_signals_window
from .oos_guard import assert_events_exclude_oos, assert_oos_locked, guard_partition_iterable


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001
        return "UNKNOWN"


def _load_events() -> pd.DataFrame:
    """Load DISCOVERY+VALIDATION events only — never OOS."""
    guard_partition_iterable(("DISCOVERY", "VALIDATION"), context="load_events")
    ev = pd.read_parquet(EVENT_DIR / "reversal_events_v1.parquet")
    assert_events_exclude_oos(ev[ev["partition"].isin(["DISCOVERY", "VALIDATION"])], context="load_events")
    # Explicitly drop OOS if present in file.
    if "partition" in ev.columns and (ev["partition"].astype(str).str.upper() == "OOS").any():
        # File may contain OOS rows; we must not use them — filter out, do not "open".
        pass
    out = ev[(ev["partition"].isin(["DISCOVERY", "VALIDATION"])) & (ev["partition_usable"] == True)].reset_index(  # noqa: E712
        drop=True
    )
    assert_events_exclude_oos(out, context="filtered_events")
    return out


def _load_bars(service: Any, tf: str, start: Any, end: Any, *, warmup_bars: int = 500) -> list:
    loaded = load_continuous_bars(service, tf, start, end, warmup_bars=warmup_bars)
    if isinstance(loaded, tuple):
        return loaded[0]
    return loaded


def freeze_check(*, artifact_root: Path | None = None) -> dict[str, Any]:
    root = artifact_root or ARTIFACT_ROOT
    spec = load_search_spec(root=root)
    templates = load_templates(root=root)
    bank = load_atomic_bank(root=root)
    corpus = load_development_corpus_manifest(root=root)
    assert spec.get("OOS_OPENED") == "NO"
    assert corpus.get("OOS_OPENED") == "NO"
    assert int(bank.get("TOTAL", 0)) == 582
    assert len(bank["configs"]) == 582
    assert len(templates["templates"]) == 6
    assert OOS_OPENED == "NO"
    report = {
        "phase": "freeze-check",
        "WIP": WIP_ID,
        "MODE": MODE,
        "ATOMIC_BANK_TOTAL": 582,
        "templates": [t["template_id"] for t in templates["templates"]],
        "OOS_OPENED": OOS_OPENED,
        "COMPOSITE_FDR_STATUS": COMPOSITE_FDR_STATUS,
        "DEVELOPMENT_CORPUS": {
            "START": DEVELOPMENT_START.isoformat(),
            "END": DEVELOPMENT_END.isoformat(),
            "folds": [
                {"fold_id": fid, "start": s.isoformat(), "end": e.isoformat()}
                for fid, s, e in DEVELOPMENT_FOLDS
            ],
        },
        "status": "PASS",
        "git_commit": _git_sha(),
    }
    (root / "freeze_check_v1.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _safe_div(num: float | None, den: float | None) -> float | None:
    if num is None or den is None:
        return None
    if float(den) == 0:
        return None
    return float(num) / float(den)


def _delta(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return float(a) - float(b)


def _stream_to_signal_dicts(cid: str, stream: dict[str, Any], *, direction: str, decision_tf: str) -> list[dict[str, Any]]:
    out = []
    for s in stream.get("events") or []:
        out.append(
            {
                "candidate_id": cid,
                "signal_id": f"{cid}|{s['available_at']}",
                "signal_time": s["signal_time"],
                "signal_price": s.get("signal_price") or 0.0,
                "signal_direction": s.get("signal_direction", direction),
                "decision_tf": decision_tf,
                "calculated_at": s.get("calculated_at", s["available_at"]),
                "available_at": s["available_at"],
            }
        )
    return out


def _evaluate_bundle(
    signals: list[dict[str, Any]],
    events: pd.DataFrame,
    *,
    candidate_id: str,
    decision_tf: str,
    direction: str,
    family: str,
    start: Any,
    end: Any,
    bars: list | None,
) -> dict[str, Any]:
    return evaluate_signals_window(
        signals,
        events,
        candidate_id=candidate_id,
        decision_tf=decision_tf,
        direction=direction,
        family=family,
        start=start,
        end=end,
        bars=bars,
    )


def run_compose_phase(
    *,
    artifact_root: Path | None = None,
    streams: dict[str, Any] | None = None,
    reps_bank: dict[str, Any] | None = None,
    bars_by_tf: dict[str, list] | None = None,
    events: pd.DataFrame | None = None,
) -> dict[str, Any]:
    root = artifact_root or ARTIFACT_ROOT
    root.mkdir(parents=True, exist_ok=True)

    if events is None:
        events = _load_events()
    assert_events_exclude_oos(events, context="compose")

    if streams is None:
        streams = load_stream_cache(artifact_root=root)
    if reps_bank is None:
        reps_bank = json.loads((root / "atomic_representative_bank_v1.json").read_text(encoding="utf-8"))
    reps = list(reps_bank["configs"])
    all_configs = list(load_atomic_bank(root=root)["configs"])

    if bars_by_tf is None:
        preflight = run_data_location_preflight(
            required_start=DEVELOPMENT_START,
            required_end=DEVELOPMENT_END,
            artifact_root=root,
        )
        _ = preflight
        service = make_bar_service()
        bars_by_tf = {
            tf: _load_bars(service, tf, DEVELOPMENT_START, DEVELOPMENT_END, warmup_bars=500)
            for tf in SEARCH_TFS
        }

    # Price baselines per TF for DEVELOPMENT window.
    baselines_by_tf: dict[str, list] = {}
    for tf, bars in bars_by_tf.items():
        baselines_by_tf[tf] = generate_frozen_price_baselines(
            bars,
            decision_tf=tf,
            scan_start_iso=DEVELOPMENT_START.isoformat(),
            scan_end_iso=DEVELOPMENT_END.isoformat(),
        )

    composites = expand_all_templates(
        representatives=reps,
        streams_by_id=streams,
        all_configs_for_pairs=all_configs,
        bars_by_tf=bars_by_tf,
    )
    print(f"[composite] expanded {len(composites)} composites", flush=True)

    result_rows: list[dict[str, Any]] = []
    fold_rows: list[dict[str, Any]] = []
    trigger_cache: dict[str, dict[str, Any]] = {}
    price_cache: dict[tuple[str, str], dict[str, Any]] = {}

    for i, comp in enumerate(composites):
        cid = comp["composite_id"]
        tf = comp["decision_tf"]
        direction = comp["direction"]
        trig_id = comp["trigger_candidate_id"]
        bars = bars_by_tf.get(tf)

        # Aggregate DEVELOPMENT metrics
        agg = _evaluate_bundle(
            comp["signals"],
            events,
            candidate_id=cid,
            decision_tf=tf,
            direction=direction,
            family="COMPOSITE",
            start=DEVELOPMENT_START,
            end=DEVELOPMENT_END,
            bars=bars,
        )

        # Trigger baseline (atomic trigger alone)
        if trig_id not in trigger_cache:
            trig_sigs = _stream_to_signal_dicts(
                trig_id, streams[trig_id], direction=direction, decision_tf=tf
            )
            # Trigger may be on same tf as composite decision_tf
            trig_cfg = next(c for c in all_configs if c["candidate_id"] == trig_id)
            trigger_cache[trig_id] = _evaluate_bundle(
                trig_sigs,
                events,
                candidate_id=trig_id,
                decision_tf=trig_cfg["decision_tf"],
                direction=direction,
                family=trig_cfg["family"],
                start=DEVELOPMENT_START,
                end=DEVELOPMENT_END,
                bars=bars_by_tf.get(trig_cfg["decision_tf"]),
            )
        trig_m = trigger_cache[trig_id]

        # Price baseline
        pk = (tf, direction)
        if pk not in price_cache:
            price_cid = f"PRICE_ONE_BAR_DIRECTION_CHANGE_{tf}"
            price_sigs = [
                s
                for s in baselines_by_tf.get(tf, [])
                if s["candidate_id"] == price_cid and s.get("signal_direction") == direction
            ]
            price_cache[pk] = _evaluate_bundle(
                price_sigs,
                events,
                candidate_id=price_cid,
                decision_tf=tf,
                direction=direction,
                family="PRICE_ONLY",
                start=DEVELOPMENT_START,
                end=DEVELOPMENT_END,
                bars=bars,
            )
        price_m = price_cache[pk]

        precision_delta_trig = _delta(agg.get("PRECISION"), trig_m.get("PRECISION"))
        precision_delta_price = _delta(agg.get("PRECISION"), price_m.get("PRECISION"))
        recall_retention = _safe_div(agg.get("EVENT_RECALL"), trig_m.get("EVENT_RECALL"))
        fpr_delta_trig = _delta(agg.get("FALSE_POSITIVE_RATE"), trig_m.get("FALSE_POSITIVE_RATE"))
        delay_delta = _delta(agg.get("MEDIAN_DELAY_SECONDS"), trig_m.get("MEDIAN_DELAY_SECONDS"))
        prec_rate_delta = _delta(agg.get("PRE_C_SIGNAL_RATE"), trig_m.get("PRE_C_SIGNAL_RATE"))
        signal_retention = _safe_div(agg.get("TOTAL_SIGNALS"), trig_m.get("TOTAL_SIGNALS"))

        fold_prec_deltas: list[float | None] = []
        fold_counts: list[int] = []
        for fold_id, fs, fe in DEVELOPMENT_FOLDS:
            fm = _evaluate_bundle(
                comp["signals"],
                events,
                candidate_id=cid,
                decision_tf=tf,
                direction=direction,
                family="COMPOSITE",
                start=fs,
                end=fe,
                bars=bars,
            )
            # Trigger fold
            trig_cfg = next(c for c in all_configs if c["candidate_id"] == trig_id)
            trig_sigs = _stream_to_signal_dicts(
                trig_id, streams[trig_id], direction=direction, decision_tf=trig_cfg["decision_tf"]
            )
            tm = _evaluate_bundle(
                trig_sigs,
                events,
                candidate_id=trig_id,
                decision_tf=trig_cfg["decision_tf"],
                direction=direction,
                family=trig_cfg["family"],
                start=fs,
                end=fe,
                bars=bars_by_tf.get(trig_cfg["decision_tf"]),
            )
            fpd = _delta(fm.get("PRECISION"), tm.get("PRECISION"))
            fold_prec_deltas.append(fpd)
            fold_counts.append(int(fm.get("TOTAL_SIGNALS") or 0))
            fold_rows.append(
                {
                    "composite_id": cid,
                    "fold_id": fold_id,
                    "TOTAL_SIGNALS": fm.get("TOTAL_SIGNALS"),
                    "PRECISION": fm.get("PRECISION"),
                    "PRECISION_DELTA_VS_TRIGGER": fpd,
                    "EVENT_RECALL": fm.get("EVENT_RECALL"),
                    "FALSE_POSITIVE_RATE": fm.get("FALSE_POSITIVE_RATE"),
                    "sample_flag": fm.get("sample_flag"),
                    "trigger_TOTAL_SIGNALS": tm.get("TOTAL_SIGNALS"),
                    "trigger_PRECISION": tm.get("PRECISION"),
                }
            )

        usable = count_usable_folds(fold_counts)
        pos_folds = count_positive_precision_delta_folds(fold_prec_deltas, fold_counts)
        cclass = classify_composite(
            aggregate_sample_flag=str(agg.get("sample_flag") or "INSUFFICIENT"),
            precision_delta_vs_trigger=precision_delta_trig,
            recall_retention_vs_trigger=recall_retention,
            fpr_delta_vs_trigger=fpr_delta_trig,
            fold_precision_deltas=fold_prec_deltas,
            fold_signal_counts=fold_counts,
        )
        payload = classification_payload(
            composite_class=cclass, usable_folds=usable, positive_delta_folds=pos_folds
        )

        result_rows.append(
            {
                "composite_id": cid,
                "template_id": comp["template_id"],
                "direction": direction,
                "decision_tf": tf,
                "diagnostic": comp.get("diagnostic", False),
                "trigger_candidate_id": trig_id,
                "context_candidate_ids": "|".join(comp.get("context_candidate_ids") or []),
                "TOTAL_SIGNALS": agg.get("TOTAL_SIGNALS"),
                "PRECISION": agg.get("PRECISION"),
                "EVENT_RECALL": agg.get("EVENT_RECALL"),
                "FALSE_POSITIVE_RATE": agg.get("FALSE_POSITIVE_RATE"),
                "MEDIAN_DELAY_SECONDS": agg.get("MEDIAN_DELAY_SECONDS"),
                "MEDIAN_MFE_AFTER_SIGNAL": agg.get("MEDIAN_MFE_AFTER_SIGNAL"),
                "MEDIAN_MAE_AFTER_SIGNAL": agg.get("MEDIAN_MAE_AFTER_SIGNAL"),
                "PRE_C_SIGNAL_RATE": agg.get("PRE_C_SIGNAL_RATE"),
                "sample_flag": agg.get("sample_flag"),
                "trigger_PRECISION": trig_m.get("PRECISION"),
                "trigger_EVENT_RECALL": trig_m.get("EVENT_RECALL"),
                "trigger_TOTAL_SIGNALS": trig_m.get("TOTAL_SIGNALS"),
                "trigger_FALSE_POSITIVE_RATE": trig_m.get("FALSE_POSITIVE_RATE"),
                "price_PRECISION": price_m.get("PRECISION"),
                "PRECISION_DELTA_VS_TRIGGER": precision_delta_trig,
                "PRECISION_DELTA_VS_PRICE_BASELINE": precision_delta_price,
                "RECALL_RETENTION_VS_TRIGGER": recall_retention,
                "FPR_DELTA_VS_TRIGGER": fpr_delta_trig,
                "MEDIAN_DELAY_DELTA_VS_TRIGGER": delay_delta,
                "PRE_C_SIGNAL_RATE_DELTA_VS_TRIGGER": prec_rate_delta,
                "SIGNAL_RETENTION": signal_retention,
                "usable_folds": usable,
                "positive_delta_folds": pos_folds,
                "composite_class": cclass,
                "is_survivor": payload["is_survivor"],
            }
        )
        if (i + 1) % 100 == 0:
            print(f"[composite] evaluated {i + 1}/{len(composites)}", flush=True)

    results_df = pd.DataFrame(result_rows)
    fold_df = pd.DataFrame(fold_rows)
    results_df.to_parquet(root / "composite_results_all_v1.parquet", index=False)
    results_df.to_csv(root / "composite_results_all_v1.csv", index=False)
    fold_df.to_csv(root / "composite_fold_stability_v1.csv", index=False)

    _write_summaries(results_df, root)
    survivors = results_df[results_df["composite_class"].isin(["INCREMENTAL_BALANCED", "SELECTIVE"])]
    survivor_bank = _freeze_survivors(survivors, root)
    handoff = _write_model_handoff(survivor_bank, root)
    summary = _write_summary(results_df, survivors, root)

    return {
        "n_composites": len(results_df),
        "n_survivors": len(survivors),
        "survivor_hash": survivor_bank.get("COMPOSITE_SURVIVOR_SET_HASH"),
        "handoff": handoff.get("artifact"),
        "summary": summary,
    }


def _write_summaries(results_df: pd.DataFrame, root: Path) -> None:
    if results_df.empty:
        for name in (
            "composite_summary_by_template_v1.csv",
            "composite_summary_by_tf_direction_v1.csv",
            "composite_summary_by_family_v1.csv",
            "composite_negative_results_v1.csv",
            "composite_redundancy_v1.csv",
        ):
            pd.DataFrame().to_csv(root / name, index=False)
        return

    def _agg(g: pd.DataFrame) -> pd.Series:
        return pd.Series(
            {
                "n": len(g),
                "n_survivors": int(g["is_survivor"].sum()) if "is_survivor" in g else 0,
                "mean_PRECISION_DELTA_VS_TRIGGER": g["PRECISION_DELTA_VS_TRIGGER"].mean(skipna=True),
                "median_PRECISION_DELTA_VS_TRIGGER": g["PRECISION_DELTA_VS_TRIGGER"].median(skipna=True),
                "mean_RECALL_RETENTION_VS_TRIGGER": g["RECALL_RETENTION_VS_TRIGGER"].mean(skipna=True),
                "class_counts": json.dumps(g["composite_class"].value_counts().to_dict()),
            }
        )

    results_df.groupby("template_id", dropna=False).apply(_agg).reset_index().to_csv(
        root / "composite_summary_by_template_v1.csv", index=False
    )
    results_df.groupby(["decision_tf", "direction"], dropna=False).apply(_agg).reset_index().to_csv(
        root / "composite_summary_by_tf_direction_v1.csv", index=False
    )

    # Family = trigger family inferred from trigger id prefix / lookup
    fam = results_df.copy()
    fam["trigger_family"] = fam["trigger_candidate_id"].astype(str).str.split("|").str[0]
    fam.groupby("trigger_family", dropna=False).apply(_agg).reset_index().to_csv(
        root / "composite_summary_by_family_v1.csv", index=False
    )

    neg = results_df[results_df["composite_class"].isin(["NO_INCREMENTAL_EDGE", "INSUFFICIENT", "WEAK_INCREMENTAL"])]
    neg.to_csv(root / "composite_negative_results_v1.csv", index=False)

    # Composite redundancy: identical context+trigger component sets across templates
    red_rows = []
    by_key: dict[str, list[str]] = defaultdict(list)
    for _, r in results_df.iterrows():
        key = f"{r['trigger_candidate_id']}|{r['context_candidate_ids']}|{r['direction']}"
        by_key[key].append(str(r["composite_id"]))
    cid = 0
    for key, members in by_key.items():
        if len(members) > 1:
            red_rows.append({"cluster_id": cid, "key": key, "size": len(members), "members": "|".join(sorted(members))})
            cid += 1
    pd.DataFrame(red_rows).to_csv(root / "composite_redundancy_v1.csv", index=False)


def _freeze_survivors(survivors: pd.DataFrame, root: Path) -> dict[str, Any]:
    ids = sorted(survivors["composite_id"].astype(str).tolist()) if not survivors.empty else []
    digest = hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode()).hexdigest()
    bank = {
        "artifact": "frozen_composite_survivor_bank_v1",
        "COMPOSITE_SURVIVOR_SET_HASH": digest,
        "n_survivors": len(ids),
        "survivor_classes": ["INCREMENTAL_BALANCED", "SELECTIVE"],
        "OOS_OPENED": OOS_OPENED,
        "COMPOSITE_FDR_STATUS": COMPOSITE_FDR_STATUS,
        "configs": survivors.to_dict(orient="records") if not survivors.empty else [],
    }
    (root / "frozen_composite_survivor_bank_v1.json").write_text(json.dumps(bank, indent=2), encoding="utf-8")
    return bank


def _write_model_handoff(survivor_bank: dict[str, Any], root: Path) -> dict[str, Any]:
    handoff = {
        "artifact": "model_feature_handoff_v1",
        "WIP": WIP_ID,
        "OOS_OPENED": OOS_OPENED,
        "COMPOSITE_FDR_STATUS": COMPOSITE_FDR_STATUS,
        "ATOMIC_INDICATOR_RECOMPUTE_PER_COMPOSITE": "NO",
        "COMPOSITE_SURVIVOR_SET_HASH": survivor_bank.get("COMPOSITE_SURVIVOR_SET_HASH"),
        "n_survivors": survivor_bank.get("n_survivors"),
        "survivor_composite_ids": [c["composite_id"] for c in survivor_bank.get("configs", [])],
        "notes": [
            "Boolean context-state ∧ trigger composites only.",
            "Survivors frozen for downstream model feature use.",
            "OOS remains locked; no monetary / execution simulation.",
        ],
    }
    (root / "model_feature_handoff_v1.json").write_text(json.dumps(handoff, indent=2), encoding="utf-8")
    return handoff


def _write_summary(results_df: pd.DataFrame, survivors: pd.DataFrame, root: Path) -> dict[str, Any]:
    class_counts = results_df["composite_class"].value_counts().to_dict() if not results_df.empty else {}
    summary = {
        "artifact": "summary_composite_v1",
        "WIP": WIP_ID,
        "MODE": MODE,
        "OOS_OPENED": OOS_OPENED,
        "OOS_ACCESS_COUNT": 0,
        "COMPOSITE_FDR_STATUS": COMPOSITE_FDR_STATUS,
        "PNL_TESTED": "NO",
        "NO_MODEL_TRAINING": True,
        "NO_EXECUTION_SIMULATOR": True,
        "DEVELOPMENT_START": DEVELOPMENT_START.isoformat(),
        "DEVELOPMENT_END": DEVELOPMENT_END.isoformat(),
        "N_COMPOSITES_EVALUATED": int(len(results_df)),
        "N_SURVIVORS": int(len(survivors)),
        "CLASS_COUNTS": class_counts,
        "N_INCREMENTAL_BALANCED": int(class_counts.get("INCREMENTAL_BALANCED", 0)),
        "N_SELECTIVE": int(class_counts.get("SELECTIVE", 0)),
        "N_WEAK_INCREMENTAL": int(class_counts.get("WEAK_INCREMENTAL", 0)),
        "N_NO_INCREMENTAL_EDGE": int(class_counts.get("NO_INCREMENTAL_EDGE", 0)),
        "N_INSUFFICIENT": int(class_counts.get("INSUFFICIENT", 0)),
        "MEAN_PRECISION_DELTA_VS_TRIGGER": None
        if results_df.empty
        else float(results_df["PRECISION_DELTA_VS_TRIGGER"].mean(skipna=True))
        if results_df["PRECISION_DELTA_VS_TRIGGER"].notna().any()
        else None,
        "PARENT_ARTIFACT_ROOT": str(PARENT_ARTIFACT_ROOT),
        "ARTIFACT_ROOT": str(root),
        "git_commit": _git_sha(),
        "ROADMAP_STATUS_AFTER": "REVIEW",
        "READY_FOR_COMPOSITE_INDEPENDENT_REVIEW_AFTER": "YES",
    }
    # Attach survivor hash if present
    surv_path = root / "frozen_composite_survivor_bank_v1.json"
    if surv_path.exists():
        bank = json.loads(surv_path.read_text(encoding="utf-8"))
        summary["COMPOSITE_SURVIVOR_SET_HASH"] = bank.get("COMPOSITE_SURVIVOR_SET_HASH")
    (root / "summary_composite_v1.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def run_atomic_phase(*, artifact_root: Path | None = None) -> dict[str, Any]:
    root = artifact_root or ARTIFACT_ROOT
    events = _load_events()
    return replay_atomic_bank(events=events, artifact_root=root)


def run_parity_phase(*, artifact_root: Path | None = None) -> dict[str, Any]:
    root = artifact_root or ARTIFACT_ROOT
    events = _load_events()
    streams = load_stream_cache(artifact_root=root)
    configs = list(load_atomic_bank(root=root)["configs"])
    return run_validation_parity(streams, configs, events, artifact_root=root)


def run_all(*, artifact_root: Path | None = None) -> dict[str, Any]:
    root = artifact_root or ARTIFACT_ROOT
    root.mkdir(parents=True, exist_ok=True)
    freeze = freeze_check(artifact_root=root)
    events = _load_events()
    replay = replay_atomic_bank(events=events, artifact_root=root)
    parity = run_validation_parity(
        replay["streams"],
        replay["configs"],
        events,
        bars_by_tf=replay["bars_by_tf"],
        artifact_root=root,
    )
    reps = write_representative_artifacts(replay["configs"], replay["streams"], artifact_root=root)
    compose_out = run_compose_phase(
        artifact_root=root,
        streams=replay["streams"],
        reps_bank=reps,
        bars_by_tf=replay["bars_by_tf"],
        events=events,
    )
    return {
        "freeze": freeze,
        "parity": {"status": parity["status"], "n_compared": parity["n_compared"]},
        "n_representatives": reps["n_representatives"],
        "compose": compose_out,
        "OOS_OPENED": OOS_OPENED,
        "COMPOSITE_FDR_STATUS": COMPOSITE_FDR_STATUS,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MULTITF-COMPOSITE-SIGNAL-SEARCH-1")
    parser.add_argument(
        "--phase",
        choices=(
            "freeze-check",
            "atomic",
            "parity",
            "compose",
            "compose-bounded",
            "memory-smoke",
            "all",
        ),
        required=True,
    )
    parser.add_argument("--max-candidates", type=int, default=None)
    parser.add_argument("--no-resume", action="store_true", default=False)
    args = parser.parse_args(argv)

    # Hard lock: never allow OOS phase names.
    if args.phase.lower() == "oos":
        assert_oos_locked(context="cli --phase oos")

    print(f"OOS_OPENED={OOS_OPENED}", flush=True)
    print(f"COMPOSITE_FDR_STATUS={COMPOSITE_FDR_STATUS}", flush=True)

    if args.phase == "freeze-check":
        out = freeze_check()
    elif args.phase == "atomic":
        freeze_check()
        out = run_atomic_phase()
        write_representative_artifacts(
            list(load_atomic_bank()["configs"]),
            out["streams"],
        )
    elif args.phase == "parity":
        out = run_parity_phase()
    elif args.phase == "compose":
        # Legacy full-RAM path retained for parity reference only.
        # Production execution must use compose-bounded.
        configs = list(load_atomic_bank()["configs"])
        streams = load_stream_cache()
        write_representative_artifacts(configs, streams)
        out = run_compose_phase()
    elif args.phase == "compose-bounded":
        from .bounded_compose import run_bounded_compose

        out = run_bounded_compose(
            max_candidates=args.max_candidates,
            resume=not args.no_resume,
        )
    elif args.phase == "memory-smoke":
        from .bounded_compose import run_bounded_compose

        smoke_root = ARTIFACT_ROOT / "_memory_smoke_runtime"
        smoke_root.mkdir(parents=True, exist_ok=True)
        smoke_csv = smoke_root / "composite_memory_smoke_v1.csv"
        out = run_bounded_compose(
            max_candidates=args.max_candidates or 120,
            smoke_rss_csv=smoke_csv,
            resume=False,
            runtime_subdir="_memory_smoke_runtime",
        )
        out["smoke_csv"] = str(smoke_csv)
        out["SMOKE_USES_PRODUCTION_CHECKPOINT"] = "NO"
        out["SMOKE_USES_PRODUCTION_RESULT_PARTS"] = "NO"
    else:
        # all: atomic+parity+reps then bounded compose (never unbounded expand)
        from .bounded_compose import run_bounded_compose

        freeze = freeze_check()
        replay = run_atomic_phase()
        write_representative_artifacts(replay["configs"], replay["streams"])
        run_validation_parity(
            replay["streams"],
            replay["configs"],
            _load_events(),
            bars_by_tf=replay.get("bars_by_tf"),
        )
        # Drop full stream dict before bounded compose.
        del replay
        out = run_bounded_compose(max_candidates=args.max_candidates, resume=not args.no_resume)
        out["freeze"] = freeze

    print(json.dumps({k: out[k] for k in out if k not in {"streams", "bars_by_tf", "configs"}}, default=str)[:2000], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
