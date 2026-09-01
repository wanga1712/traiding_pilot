"""Discovery evaluation, selection, validation helpers."""
from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np
import pandas as pd

from crypto_trading_bot.research_v2.indicator_engine.bars import parse_ts
from crypto_trading_bot.research_v2.reversal_signal_study.match import enrich_matches_with_path_excursion, match_signals_to_events
from crypto_trading_bot.research_v2.reversal_signal_study.metrics import benjamini_hochberg, compute_directional_metrics
from crypto_trading_bot.research_v2.reversal_signal_study.signals import years_covered

from .config import (
    BOOTSTRAP_BLOCKS,
    BOOTSTRAP_SEED,
    DISCOVERY_SHORTLIST_CAP_PER_FAMILY,
    FDR_ALPHA,
    MAX_DELAY_SECONDS,
    REDUNDANCY_CORR,
    REDUNDANCY_JACCARD,
    TF_BAR_SECONDS,
    discovery_fold_bounds,
)


def _patch_match_config():
    import crypto_trading_bot.research_v2.reversal_signal_study.config as rc

    rc.MAX_DELAY_SECONDS.update(MAX_DELAY_SECONDS)
    rc.TF_BAR_SECONDS.update(TF_BAR_SECONDS)


def evaluate_candidate(
    signals: list[dict[str, Any]],
    events: pd.DataFrame,
    row: dict[str, Any],
    *,
    partition: str,
    fold_start: str | None = None,
    fold_end: str | None = None,
    valid_bars: int = 0,
) -> dict[str, Any]:
    _patch_match_config()
    sig_df = pd.DataFrame(signals) if signals else pd.DataFrame()
    ev = events[events["partition"] == partition].copy()
    if fold_start and fold_end:
        fs, fe = parse_ts(fold_start), parse_ts(fold_end)
        ev = ev[(pd.to_datetime(ev["true_pivot_time"], utc=True) >= fs) & (pd.to_datetime(ev["true_pivot_time"], utc=True) < fe)]
        if not sig_df.empty:
            st = pd.to_datetime(sig_df["signal_time"], utc=True)
            sig_df = sig_df[(st >= fs) & (st < fe)]
    ev = ev[ev["source_wave_tf"] == row["decision_tf"]]
    if sig_df.empty:
        return {
            "candidate_id": row["candidate_id"],
            "partition": partition,
            "TOTAL_SIGNALS": 0,
            "PRECISION": None,
            "EVENT_RECALL": None,
            "FALSE_POSITIVE_RATE": None,
            "MEDIAN_DELAY_SECONDS": None,
            "MEDIAN_MAE_AFTER_SIGNAL": None,
            "sample_flag": "INSUFFICIENT",
        }
    matches = match_signals_to_events(sig_df, ev, decision_tf=row["decision_tf"])
    matches = enrich_matches_with_path_excursion(matches, ev)
    years = years_covered(fold_start or str(ev["true_pivot_time"].min()), fold_end or str(ev["true_pivot_time"].max()))
    m = compute_directional_metrics(
        matches,
        ev,
        candidate_id=row["candidate_id"],
        family=row["family"],
        role="DIRECTIONAL",
        decision_tf=row["decision_tf"],
        scanned_from=fold_start or "",
        scanned_to=fold_end or "",
        valid_decision_bars=valid_bars,
        partition=partition,
        years=years,
        source_wave_tf=row["decision_tf"],
        pivot_type="LOW" if row["direction"] == "UP" else "HIGH",
    )
    n = int(m.get("TOTAL_SIGNALS") or 0)
    if n >= 100:
        m["sample_flag"] = "NORMAL"
    elif n >= 30:
        m["sample_flag"] = "LOW_SAMPLE"
    else:
        m["sample_flag"] = "INSUFFICIENT"
    m["direction"] = row["direction"]
    m["event_primitive"] = row["event_primitive"]
    m["parameter_set_id"] = row["parameter_set_id"]
    m["is_reference"] = row.get("is_reference", False)
    return m


def price_baseline_metrics(
    baseline_signals: list[dict[str, Any]],
    events: pd.DataFrame,
    *,
    decision_tf: str,
    direction: str,
    partition: str,
) -> dict[str, float | None]:
    # Frozen primary baseline from REVERSAL-SIGNAL-EVENT-STUDY-1 semantics.
    cid = f"PRICE_ONE_BAR_DIRECTION_CHANGE_{decision_tf}"
    row = {
        "candidate_id": cid,
        "family": "PRICE_ONLY",
        "decision_tf": decision_tf,
        "direction": direction,
        "event_primitive": "ONE_BAR_DIRECTION_CHANGE",
        "parameter_set_id": "ONE_BAR_DIRECTION_CHANGE",
    }
    sigs = [s for s in baseline_signals if s["candidate_id"] == cid and s.get("signal_direction") == direction]
    m = evaluate_candidate(sigs, events, row, partition=partition)
    return {
        "PRECISION": m.get("PRECISION"),
        "EVENT_RECALL": m.get("EVENT_RECALL"),
        "FALSE_POSITIVE_RATE": m.get("FALSE_POSITIVE_RATE"),
        "MEDIAN_DELAY_SECONDS": m.get("MEDIAN_DELAY_SECONDS"),
        "PRE_C_SIGNAL_RATE": m.get("PRE_C_SIGNAL_RATE"),
    }


def add_baseline_deltas(metrics: dict[str, Any], baseline: dict[str, float | None]) -> dict[str, Any]:
    out = dict(metrics)
    for k in ("PRECISION", "EVENT_RECALL", "FALSE_POSITIVE_RATE", "MEDIAN_DELAY_SECONDS", "PRE_C_SIGNAL_RATE"):
        mv, bv = metrics.get(k), baseline.get(k)
        if mv is not None and bv is not None:
            if k == "MEDIAN_DELAY_SECONDS":
                out[f"{k}_DELTA"] = float(mv) - float(bv)
            elif k == "FALSE_POSITIVE_RATE":
                out["FPR_DELTA"] = float(mv) - float(bv)
            elif k == "PRECISION":
                out["PRECISION_DELTA"] = float(mv) - float(bv)
            elif k == "EVENT_RECALL":
                out["RECALL_DELTA"] = float(mv) - float(bv)
            elif k == "PRE_C_SIGNAL_RATE":
                out["PREMATURE_DELTA"] = float(mv) - float(bv)
    return out


def fold_stability_class(fold_deltas: list[float | None]) -> str:
    vals = [v for v in fold_deltas if v is not None]
    if len(vals) < 2:
        return "INSUFFICIENT"
    pos = sum(1 for v in vals if v > 0)
    neg = sum(1 for v in vals if v < 0)
    if pos >= 2 and neg == 0:
        return "STABLE_POSITIVE_FOLDS"
    if pos >= 2 and neg <= 1:
        return "MOSTLY_POSITIVE_FOLDS"
    return "UNSTABLE_DISCOVERY"


def jaccard_events(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    u = a | b
    if not u:
        return 1.0
    return len(a & b) / len(u)


def redundancy_clusters(candidates: list[dict[str, Any]], event_sets: dict[str, set[str]]) -> list[dict[str, Any]]:
    clusters = []
    used = set()
    ids = sorted(event_sets.keys())
    cluster_id = 0
    for i, a in enumerate(ids):
        if a in used:
            continue
        members = [a]
        used.add(a)
        for b in ids[i + 1 :]:
            if b in used:
                continue
            if jaccard_events(event_sets[a], event_sets[b]) >= REDUNDANCY_JACCARD:
                members.append(b)
                used.add(b)
        if len(members) > 1:
            clusters.append({"cluster_id": cluster_id, "members": members, "size": len(members)})
            cluster_id += 1
    return clusters


def select_discovery_shortlist(discovery_df: pd.DataFrame) -> pd.DataFrame:
    """Pareto-ish shortlist: top non-reference per TF/direction/family by precision delta."""
    if discovery_df.empty:
        return discovery_df
    df = discovery_df.copy()
    df = df[df["partition"] == "DISCOVERY"]
    shortlist = []
    for (tf, direction, family), g in df.groupby(["decision_tf", "direction", "family"]):
        refs = g[g["is_reference"] == True]  # noqa: E712
        shortlist.append(refs)
        nonref = g[g["is_reference"] != True].copy()  # noqa: E712
        nonref = nonref[nonref["sample_flag"] != "INSUFFICIENT"]
        nonref = nonref.sort_values("PRECISION_DELTA", ascending=False, na_position="last")
        shortlist.append(nonref.head(DISCOVERY_SHORTLIST_CAP_PER_FAMILY))
    out = pd.concat(shortlist, ignore_index=True) if shortlist else pd.DataFrame()
    return out.drop_duplicates(subset=["candidate_id", "partition"])


def validation_candidate_hash(candidate_ids: list[str]) -> str:
    payload = json.dumps(sorted(candidate_ids), separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def classify_validation_stability(disc: dict[str, Any], val: dict[str, Any]) -> str:
    if val.get("sample_flag") == "INSUFFICIENT":
        return "INSUFFICIENT_SAMPLE"
    pd_d = disc.get("PRECISION_DELTA")
    pd_v = val.get("PRECISION_DELTA")
    if pd_d is None or pd_v is None:
        return "INSUFFICIENT_SAMPLE"
    if pd_d > 0.02 and pd_v > 0:
        if abs(pd_d - pd_v) <= max(0.05, 0.5 * abs(pd_d)):
            return "STABLE_POSITIVE"
        return "WEAK_POSITIVE"
    if pd_v > 0:
        return "WEAK_POSITIVE"
    if pd_v <= 0:
        return "NEGATIVE"
    return "UNSTABLE"


def block_bootstrap_pvalue(deltas: np.ndarray, *, seed: int = BOOTSTRAP_SEED, n_boot: int = BOOTSTRAP_BLOCKS) -> float:
    arr = deltas[np.isfinite(deltas)]
    if arr.size < 10:
        return 1.0
    rng = np.random.default_rng(seed)
    obs = float(np.mean(arr))
    if obs <= 0:
        return 1.0
    count = 0
    for _ in range(n_boot):
        sample = rng.choice(arr, size=arr.size, replace=True)
        if np.mean(sample) <= 0:
            count += 1
    return count / n_boot
