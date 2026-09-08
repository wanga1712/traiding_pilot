"""Deterministic stratified smoke / parity candidate selection from frozen defs."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Iterator, Sequence


TEMPLATE_ORDER = (
    "T1_DUAL_ANCHOR",
    "T2_REGIME_ANCHOR",
    "T3_ANCHOR_TRANSITION",
    "T4_REGIME_ANCHOR_TRANSITION",
    "T5_ANCHOR_MICRO",
    "T6_CROSS_FAMILY_SAME_TF",
)


def _is_triple(comp: dict[str, Any]) -> bool:
    return len(comp.get("components") or []) >= 3 or len(comp.get("context_candidate_ids") or []) >= 2


def select_stratified_definitions(
    definitions: Iterable[dict[str, Any]],
    *,
    quotas: dict[str, int] | None = None,
    t5_5m: int = 30,
    t5_15m: int = 30,
    t4_triple: int = 30,
    min_total: int = 180,
) -> list[dict[str, Any]]:
    """
    Deterministic selection — NOT first-N of the global generator.

    Single pass over the frozen definition stream; keeps only selected rows in RAM.
    """
    quotas = quotas or {
        "T1_DUAL_ANCHOR": 25,
        "T2_REGIME_ANCHOR": 25,
        "T3_ANCHOR_TRANSITION": 25,
        "T4_REGIME_ANCHOR_TRANSITION": 30,
        "T5_ANCHOR_MICRO": 60,
        "T6_CROSS_FAMILY_SAME_TF": 25,
    }

    # Bucket only candidates we might still need (bounded by quotas + specialty).
    buckets: dict[str, list[dict[str, Any]]] = {tid: [] for tid in TEMPLATE_ORDER}
    t5_5m_buf: list[dict[str, Any]] = []
    t5_15m_buf: list[dict[str, Any]] = []
    t4_trip_buf: list[dict[str, Any]] = []

    for d in definitions:
        tid = str(d["template_id"])
        if tid not in buckets:
            continue
        # Specialty buffers
        if tid == "T5_ANCHOR_MICRO":
            if d.get("decision_tf") == "5m" and len(t5_5m_buf) < t5_5m:
                t5_5m_buf.append(d)
            elif d.get("decision_tf") == "15m" and len(t5_15m_buf) < t5_15m:
                t5_15m_buf.append(d)
            elif len(buckets[tid]) < quotas[tid] + 40:
                buckets[tid].append(d)
        elif tid == "T4_REGIME_ANCHOR_TRANSITION":
            if _is_triple(d) and len(t4_trip_buf) < t4_triple:
                t4_trip_buf.append(d)
            elif len(buckets[tid]) < quotas[tid] + 40:
                buckets[tid].append(d)
        else:
            if len(buckets[tid]) < quotas[tid] + 20:
                buckets[tid].append(d)

        # Early exit when all specialty + quotas are fillable
        if (
            len(t5_5m_buf) >= t5_5m
            and len(t5_15m_buf) >= t5_15m
            and len(t4_trip_buf) >= t4_triple
            and all(len(buckets[t]) >= quotas[t] for t in TEMPLATE_ORDER if t not in {"T4_REGIME_ANCHOR_TRANSITION", "T5_ANCHOR_MICRO"})
            and len(buckets["T4_REGIME_ANCHOR_TRANSITION"]) + len(t4_trip_buf) >= quotas["T4_REGIME_ANCHOR_TRANSITION"]
            and len(buckets["T5_ANCHOR_MICRO"]) + len(t5_5m_buf) + len(t5_15m_buf) >= quotas["T5_ANCHOR_MICRO"]
        ):
            # Still need enough T5/T4 filler — don't break too early if fillers short
            if len(buckets["T5_ANCHOR_MICRO"]) >= max(0, quotas["T5_ANCHOR_MICRO"] - t5_5m - t5_15m) and len(
                buckets["T4_REGIME_ANCHOR_TRANSITION"]
            ) >= max(0, quotas["T4_REGIME_ANCHOR_TRANSITION"] - t4_triple):
                break

    for tid in buckets:
        buckets[tid].sort(key=lambda x: (x["direction"], x["decision_tf"], x["composite_id"]))
    t5_5m_buf.sort(key=lambda x: (x["direction"], x["composite_id"]))
    t5_15m_buf.sort(key=lambda x: (x["direction"], x["composite_id"]))
    t4_trip_buf.sort(key=lambda x: (x["direction"], x["composite_id"]))

    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    def _take(cands: Sequence[dict[str, Any]], n: int) -> int:
        got = 0
        for c in cands:
            if got >= n:
                break
            cid = c["composite_id"]
            if cid in selected_ids:
                continue
            selected.append(c)
            selected_ids.add(cid)
            got += 1
        return got

    _take(t5_5m_buf, t5_5m)
    _take(t5_15m_buf, t5_15m)
    need_t5 = max(0, quotas["T5_ANCHOR_MICRO"] - sum(1 for c in selected if c["template_id"] == "T5_ANCHOR_MICRO"))
    _take(buckets["T5_ANCHOR_MICRO"], need_t5)

    _take(t4_trip_buf, t4_triple)
    need_t4 = max(
        0, quotas["T4_REGIME_ANCHOR_TRANSITION"] - sum(1 for c in selected if c["template_id"] == "T4_REGIME_ANCHOR_TRANSITION")
    )
    _take(buckets["T4_REGIME_ANCHOR_TRANSITION"], need_t4)

    for tid in TEMPLATE_ORDER:
        if tid in {"T4_REGIME_ANCHOR_TRANSITION", "T5_ANCHOR_MICRO"}:
            continue
        need = quotas[tid] - sum(1 for c in selected if c["template_id"] == tid)
        if need > 0:
            _take(buckets[tid], need)

    # Top up to min_total from remaining bucket tails
    if len(selected) < min_total:
        for tid in TEMPLATE_ORDER:
            if len(selected) >= min_total:
                break
            _take(buckets[tid], min_total - len(selected))

    selected.sort(
        key=lambda c: (TEMPLATE_ORDER.index(c["template_id"]) if c["template_id"] in TEMPLATE_ORDER else 99, c["composite_id"])
    )
    return selected


def coverage_stats(selected: Sequence[dict[str, Any]]) -> dict[str, Any]:
    by_t: dict[str, int] = defaultdict(int)
    n_5m = n_15m = n_t4_triple = 0
    for c in selected:
        by_t[str(c["template_id"])] += 1
        if c.get("decision_tf") == "5m":
            n_5m += 1
        if c.get("decision_tf") == "15m":
            n_15m += 1
        if c.get("template_id") == "T4_REGIME_ANCHOR_TRANSITION" and _is_triple(c):
            n_t4_triple += 1
    return {
        "MEMORY_SMOKE_BY_TEMPLATE": dict(by_t),
        "MEMORY_SMOKE_5M_COUNT": n_5m,
        "MEMORY_SMOKE_15M_COUNT": n_15m,
        "MEMORY_SMOKE_T4_TRIPLE_COUNT": n_t4_triple,
        "total": len(selected),
    }


def select_parity_definitions(
    definitions: Iterable[dict[str, Any]],
    *,
    per_template: int = 10,
    n_5m: int = 10,
    n_15m: int = 10,
    n_t4_triple: int = 10,
) -> list[dict[str, Any]]:
    quotas = {tid: per_template for tid in TEMPLATE_ORDER}
    quotas["T4_REGIME_ANCHOR_TRANSITION"] = max(per_template, n_t4_triple)
    quotas["T5_ANCHOR_MICRO"] = max(per_template, n_5m + n_15m)
    return select_stratified_definitions(
        definitions,
        quotas=quotas,
        t5_5m=n_5m,
        t5_15m=n_15m,
        t4_triple=n_t4_triple,
        min_total=60,
    )
