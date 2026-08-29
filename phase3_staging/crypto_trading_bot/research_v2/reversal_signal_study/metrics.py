"""Aggregate directional + context metrics; FDR; leaderboards."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _median(x) -> float | None:
    x = pd.Series(x).dropna()
    return float(x.median()) if len(x) else None


def _pctl(x, q: float) -> float | None:
    x = pd.Series(x).dropna()
    return float(x.quantile(q)) if len(x) else None


def compute_directional_metrics(
    matches: pd.DataFrame,
    events: pd.DataFrame,
    *,
    candidate_id: str,
    family: str,
    role: str,
    decision_tf: str,
    scanned_from: str,
    scanned_to: str,
    valid_decision_bars: int,
    partition: str,
    years: float,
    source_wave_tf: str | None = None,
    pivot_type: str | None = None,
) -> dict[str, Any]:
    ev = events
    if source_wave_tf:
        ev = ev[ev["source_wave_tf"] == source_wave_tf]
    if pivot_type:
        ev = ev[ev["pivot_type"] == pivot_type]
    n_events = int(len(ev))

    m = matches[matches["candidate_id"] == candidate_id].copy()
    if source_wave_tf:
        m = m[(m["source_wave_tf"] == source_wave_tf) | (m["match_type"] == "UNMATCHED")]
        # unmatched have null source — keep all unmatched for FP; for matched filter
        matched_part = m[m["match_type"] != "UNMATCHED"]
        matched_part = matched_part[matched_part["source_wave_tf"] == source_wave_tf]
        unmatched = m[m["match_type"] == "UNMATCHED"]
        m = pd.concat([matched_part, unmatched], ignore_index=True)
    if pivot_type:
        keep = m["match_type"] == "UNMATCHED"
        m = pd.concat([m[keep], m[(~keep) & (m["pivot_type"] == pivot_type)]], ignore_index=True)

    total_signals = int(len(m))
    post = m[m["match_type"] == "MATCHED_POST_C"]
    pre = m[m["match_type"] == "PRE_C_WARNING"]
    unmatched = m[m["match_type"] == "UNMATCHED"]
    matched_post = int(len(post))
    pre_n = int(len(pre))
    unmatched_n = int(len(unmatched))

    precision = matched_post / total_signals if total_signals else None
    fpr = unmatched_n / total_signals if total_signals else None
    recall = matched_post / n_events if n_events else None

    return {
        "candidate_id": candidate_id,
        "family": family,
        "role": role,
        "decision_tf": decision_tf,
        "partition": partition,
        "source_wave_tf": source_wave_tf or "ALL",
        "pivot_type": pivot_type or "ALL",
        "n_events": n_events,
        "TOTAL_SIGNALS": total_signals,
        "MATCHED_POST_C_SIGNALS": matched_post,
        "PRE_C_WARNING_SIGNALS": pre_n,
        "UNMATCHED_SIGNALS": unmatched_n,
        "FALSE_POSITIVE_RATE": fpr,
        "PRECISION": precision,
        "EVENT_RECALL": recall,
        "SIGNALS_PER_YEAR": total_signals / years if years else None,
        "FALSE_SIGNALS_PER_YEAR": unmatched_n / years if years else None,
        "MEDIAN_DELAY_SECONDS": _median(post["delay_seconds"]),
        "P75_DELAY_SECONDS": _pctl(post["delay_seconds"], 0.75),
        "P90_DELAY_SECONDS": _pctl(post["delay_seconds"], 0.90),
        "MEDIAN_PRICE_DISTANCE_FROM_C_PCT": _median(post["price_distance_from_c_pct"]),
        "MEDIAN_PRICE_DISTANCE_FROM_C_ATR": _median(post["price_distance_from_c_atr"]),
        "MEDIAN_REMAINING_WAVE_FRACTION": _median(post["remaining_wave_fraction"]),
        "MEDIAN_MAE_AFTER_SIGNAL": _median(post["mae_after_signal_pct"]),
        "P90_MAE_AFTER_SIGNAL": _pctl(post["mae_after_signal_pct"], 0.90),
        "MEDIAN_MFE_AFTER_SIGNAL": _median(post["mfe_after_signal_pct"]),
        "MFE_MAE_RATIO": _median(post["mfe_mae_ratio"]),
        "PRE_C_SIGNAL_RATE": pre_n / total_signals if total_signals else None,
        "MEDIAN_PRE_C_LEAD": _median(pre["pre_c_lead_seconds"]),
        "MEDIAN_ADVERSE_EXTENSION_AFTER_PRE_C": _median(pre["adverse_extension_after_pre_c"]),
        "SCANNED_TIME_FROM": scanned_from,
        "SCANNED_TIME_TO": scanned_to,
        "VALID_DECISION_BARS": valid_decision_bars,
        "YEARS_COVERED": years,
    }


def benjamini_hochberg(p_values: list[float], alpha: float = 0.1) -> list[bool]:
    """Return reject flags for BH-FDR control."""
    n = len(p_values)
    if n == 0:
        return []
    order = np.argsort(p_values)
    ranked = np.array(p_values)[order]
    thresh = alpha * (np.arange(1, n + 1) / n)
    below = ranked <= thresh
    reject = np.zeros(n, dtype=bool)
    if below.any():
        kmax = np.max(np.where(below)[0])
        reject[order[: kmax + 1]] = True
    return reject.tolist()


def simple_lift_pvalue(hit_rate: float, base_rate: float, n: int) -> float:
    """Two-sided normal approx for rate difference; conservative."""
    if n <= 0 or base_rate <= 0 or base_rate >= 1:
        return 1.0
    se = np.sqrt(base_rate * (1 - base_rate) / n)
    if se <= 0:
        return 1.0
    z = abs(hit_rate - base_rate) / se
    # crude 2*(1-Phi)
    from math import erfc, sqrt

    return float(erfc(z / sqrt(2.0)))


def build_leaderboards(metrics: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Multi-criteria boards — validation partition, ALL source TF pooled with note."""
    m = metrics[(metrics["partition"] == "VALIDATION") & (metrics["source_wave_tf"] == "ALL") & (metrics["pivot_type"] == "ALL")]
    m = m[m["role"].isin(["DIRECTIONAL_TRIGGER", "PREDICTOR_THRESHOLD", "PRICE_BASELINE"])].copy()

    def top(df, col, ascending=True, n=25):
        d = df.dropna(subset=[col]).sort_values(col, ascending=ascending).head(n)
        return d

    boards = {
        "leaderboard_earliest_v1": top(m, "MEDIAN_DELAY_SECONDS", True),
        "leaderboard_precision_v1": top(m, "PRECISION", False),
        "leaderboard_false_positive_v1": top(m, "FALSE_POSITIVE_RATE", True),
        "leaderboard_low_mae_v1": top(m, "MEDIAN_MAE_AFTER_SIGNAL", True),
        "leaderboard_remaining_wave_v1": top(m, "MEDIAN_REMAINING_WAVE_FRACTION", False),
        "leaderboard_recall_v1": top(m, "EVENT_RECALL", False),
    }
    return boards


def pareto_front(metrics: pd.DataFrame) -> pd.DataFrame:
    """Non-dominated on delay↓, FPR↓, recall↑, remaining↑, MAE↓."""
    m = metrics[
        (metrics["partition"] == "VALIDATION")
        & (metrics["source_wave_tf"] == "ALL")
        & (metrics["pivot_type"] == "ALL")
        & (metrics["role"].isin(["DIRECTIONAL_TRIGGER", "PREDICTOR_THRESHOLD", "PRICE_BASELINE"]))
    ].copy()
    needed = [
        "MEDIAN_DELAY_SECONDS",
        "FALSE_POSITIVE_RATE",
        "EVENT_RECALL",
        "MEDIAN_REMAINING_WAVE_FRACTION",
        "MEDIAN_MAE_AFTER_SIGNAL",
    ]
    m = m.dropna(subset=needed)
    rows = m.to_dict("records")
    keep = []
    for i, a in enumerate(rows):
        dominated = False
        for j, b in enumerate(rows):
            if i == j:
                continue
            better_or_eq = (
                b["MEDIAN_DELAY_SECONDS"] <= a["MEDIAN_DELAY_SECONDS"]
                and b["FALSE_POSITIVE_RATE"] <= a["FALSE_POSITIVE_RATE"]
                and b["EVENT_RECALL"] >= a["EVENT_RECALL"]
                and b["MEDIAN_REMAINING_WAVE_FRACTION"] >= a["MEDIAN_REMAINING_WAVE_FRACTION"]
                and b["MEDIAN_MAE_AFTER_SIGNAL"] <= a["MEDIAN_MAE_AFTER_SIGNAL"]
            )
            strictly = (
                b["MEDIAN_DELAY_SECONDS"] < a["MEDIAN_DELAY_SECONDS"]
                or b["FALSE_POSITIVE_RATE"] < a["FALSE_POSITIVE_RATE"]
                or b["EVENT_RECALL"] > a["EVENT_RECALL"]
                or b["MEDIAN_REMAINING_WAVE_FRACTION"] > a["MEDIAN_REMAINING_WAVE_FRACTION"]
                or b["MEDIAN_MAE_AFTER_SIGNAL"] < a["MEDIAN_MAE_AFTER_SIGNAL"]
            )
            if better_or_eq and strictly:
                dominated = True
                break
        if not dominated:
            keep.append(a)
    return pd.DataFrame(keep)


def family_winners(metrics: pd.DataFrame) -> pd.DataFrame:
    m = metrics[
        (metrics["partition"] == "VALIDATION")
        & (metrics["source_wave_tf"] == "ALL")
        & (metrics["pivot_type"] == "ALL")
    ].copy()
    winners = []
    for fam, g in m.groupby("family"):
        # score: precision * recall / (1+delay_hours) / (1+fpr)
        g = g.copy()
        g["score"] = (
            g["PRECISION"].fillna(0)
            * g["EVENT_RECALL"].fillna(0)
            / (1.0 + g["MEDIAN_DELAY_SECONDS"].fillna(1e9) / 3600.0)
            / (1.0 + g["FALSE_POSITIVE_RATE"].fillna(1.0))
        )
        best = g.sort_values("score", ascending=False).iloc[0]
        winners.append(best.to_dict())
    return pd.DataFrame(winners)


def tf_balanced_pool_note() -> str:
    return (
        "Pooled ALL source_wave_tf metrics are unweighted event averages; "
        "1H is denser — prefer stratified boards and TF-balanced family comparisons."
    )
