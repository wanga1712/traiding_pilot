"""Chronological one-to-one matching of ZigZag pivots to expert points."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from statistics import median
from typing import Any


def _parse_ts(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    text = str(value).replace("Z", "+00:00")
    # Postgres CSV often emits "+00" without minutes.
    if text.endswith("+00"):
        text = text + ":00"
    return datetime.fromisoformat(text)


def _price_error_pct(expert_price: float, zig_price: float) -> float:
    if expert_price == 0:
        return abs(zig_price - expert_price)
    return abs(zig_price - expert_price) / abs(expert_price) * 100.0


@dataclass
class MatchResult:
    matched: int = 0
    missed: int = 0
    extra: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    median_bar_error: float | None = None
    median_price_error_pct: float | None = None
    median_time_error_hours: float | None = None
    bar_errors: list[int] = field(default_factory=list)
    price_errors_pct: list[float] = field(default_factory=list)
    time_errors_hours: list[float] = field(default_factory=list)
    pairs: list[dict[str, Any]] = field(default_factory=list)
    missed_experts: list[dict[str, Any]] = field(default_factory=list)
    extra_zigs: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "matched": self.matched,
            "missed": self.missed,
            "extra": self.extra,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "median_bar_error": self.median_bar_error,
            "median_price_error_pct": self.median_price_error_pct,
            "median_time_error_hours": self.median_time_error_hours,
            "pair_count": len(self.pairs),
        }


def align_chronological(
    expert_points: list[dict],
    zigzag_pivots: list[Any],
    *,
    max_bar_error: int = 3,
    max_price_error_pct: float = 1.5,
    require_kind_hint: bool = False,
) -> MatchResult:
    """
    Greedy chronological 1:1 alignment.

    For each expert point in order, take the earliest unused ZigZag pivot within
    (max_bar_error, max_price_error_pct). Remaining ZigZag pivots are EXTRA;
    unmatched experts are MISSED.
    """
    result = MatchResult()
    if not expert_points:
        result.extra = len(zigzag_pivots)
        result.extra_zigs = [_zig_as_dict(z) for z in zigzag_pivots]
        return result

    used: set[int] = set()
    zig_list = list(zigzag_pivots)

    for expert in expert_points:
        e_idx = int(expert["bar_index"])
        e_price = float(expert["price"])
        e_ts = _parse_ts(expert["timestamp"])
        best_j = None
        best_score = None
        for j, z in enumerate(zig_list):
            if j in used:
                continue
            z_idx = int(z.index if hasattr(z, "index") else z["index"])
            # Chronology: do not match a zig that is far before previous match window
            # beyond tolerance (already enforced by greedy earliest-acceptable).
            bar_err = abs(z_idx - e_idx)
            if bar_err > max_bar_error:
                # Allow slightly early scan to continue; skip far ones.
                if z_idx < e_idx - max_bar_error:
                    continue
                if z_idx > e_idx + max_bar_error:
                    break
                continue
            z_price = float(z.price if hasattr(z, "price") else z["price"])
            p_err = _price_error_pct(e_price, z_price)
            if p_err > max_price_error_pct:
                continue
            # Prefer smaller bar error, then price error.
            score = (bar_err, p_err)
            if best_score is None or score < best_score:
                best_score = score
                best_j = j
        if best_j is None:
            result.missed_experts.append(
                {
                    "point_index": expert.get("point_index"),
                    "timestamp": expert["timestamp"],
                    "price": e_price,
                    "bar_index": e_idx,
                }
            )
            continue
        used.add(best_j)
        z = zig_list[best_j]
        z_idx = int(z.index if hasattr(z, "index") else z["index"])
        z_price = float(z.price if hasattr(z, "price") else z["price"])
        z_ts = _parse_ts(z.timestamp if hasattr(z, "timestamp") else z["timestamp"])
        bar_err = abs(z_idx - e_idx)
        p_err = _price_error_pct(e_price, z_price)
        t_err = abs((z_ts - e_ts).total_seconds()) / 3600.0
        result.bar_errors.append(bar_err)
        result.price_errors_pct.append(p_err)
        result.time_errors_hours.append(t_err)
        result.pairs.append(
            {
                "expert_point_index": expert.get("point_index"),
                "expert_timestamp": expert["timestamp"],
                "expert_price": e_price,
                "expert_bar_index": e_idx,
                "zig_index": z_idx,
                "zig_timestamp": z.timestamp if hasattr(z, "timestamp") else z["timestamp"],
                "zig_price": z_price,
                "zig_kind": z.kind if hasattr(z, "kind") else z.get("kind"),
                "confirmation_timestamp": (
                    z.confirmation_timestamp
                    if hasattr(z, "confirmation_timestamp")
                    else z.get("confirmation_timestamp")
                ),
                "bar_error": bar_err,
                "price_error_pct": p_err,
                "time_error_hours": t_err,
            }
        )

    result.matched = len(result.pairs)
    result.missed = len(result.missed_experts)
    for j, z in enumerate(zig_list):
        if j not in used:
            result.extra_zigs.append(_zig_as_dict(z))
    result.extra = len(result.extra_zigs)

    prec_den = result.matched + result.extra
    rec_den = result.matched + result.missed
    result.precision = (result.matched / prec_den) if prec_den else 0.0
    result.recall = (result.matched / rec_den) if rec_den else 0.0
    if result.precision + result.recall > 0:
        result.f1 = 2 * result.precision * result.recall / (result.precision + result.recall)
    if result.bar_errors:
        result.median_bar_error = float(median(result.bar_errors))
    if result.price_errors_pct:
        result.median_price_error_pct = float(median(result.price_errors_pct))
    if result.time_errors_hours:
        result.median_time_error_hours = float(median(result.time_errors_hours))
    return result


def _zig_as_dict(z: Any) -> dict[str, Any]:
    if hasattr(z, "index"):
        return {
            "index": z.index,
            "timestamp": z.timestamp,
            "price": z.price,
            "kind": z.kind,
            "confirmation_timestamp": z.confirmation_timestamp,
        }
    return dict(z)


def score_tuple(result: MatchResult, zigzag_count: int, expert_count: int) -> tuple:
    """Primary ranking key: higher F1, lower median errors, fewer extras."""
    extra_ratio = (result.extra / max(expert_count, 1))
    return (
        -result.f1,
        result.median_bar_error if result.median_bar_error is not None else 999.0,
        result.median_price_error_pct if result.median_price_error_pct is not None else 999.0,
        extra_ratio,
        zigzag_count,
    )
