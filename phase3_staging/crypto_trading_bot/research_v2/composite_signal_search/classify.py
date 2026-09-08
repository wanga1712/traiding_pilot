"""Frozen composite classification thresholds (pre-results)."""
from __future__ import annotations

from typing import Any, Sequence

from .config import REQUIRE_USABLE_FOLDS, USABLE_FOLD_MIN_SIGNALS


def fold_is_usable(total_signals: int | None) -> bool:
    return int(total_signals or 0) >= USABLE_FOLD_MIN_SIGNALS


def count_usable_folds(fold_signal_counts: Sequence[int | None]) -> int:
    return sum(1 for n in fold_signal_counts if fold_is_usable(n))


def count_positive_precision_delta_folds(
    fold_precision_deltas: Sequence[float | None],
    fold_signal_counts: Sequence[int | None],
) -> int:
    n = 0
    for delta, count in zip(fold_precision_deltas, fold_signal_counts):
        if not fold_is_usable(count):
            continue
        if delta is not None and float(delta) > 0:
            n += 1
    return n


def classify_composite(
    *,
    aggregate_sample_flag: str,
    precision_delta_vs_trigger: float | None,
    recall_retention_vs_trigger: float | None,
    fpr_delta_vs_trigger: float | None,
    fold_precision_deltas: Sequence[float | None],
    fold_signal_counts: Sequence[int | None],
    require_usable_folds: int = REQUIRE_USABLE_FOLDS,
) -> str:
    """
    Frozen classes (methodology locked before results):

    INCREMENTAL_BALANCED / SELECTIVE / WEAK_INCREMENTAL /
    NO_INCREMENTAL_EDGE / INSUFFICIENT
    """
    usable = count_usable_folds(fold_signal_counts)
    if aggregate_sample_flag == "INSUFFICIENT" or usable < require_usable_folds:
        return "INSUFFICIENT"

    if precision_delta_vs_trigger is None:
        return "INSUFFICIENT"

    pd_trig = float(precision_delta_vs_trigger)
    pos_folds = count_positive_precision_delta_folds(fold_precision_deltas, fold_signal_counts)
    recall = None if recall_retention_vs_trigger is None else float(recall_retention_vs_trigger)
    fpr_d = None if fpr_delta_vs_trigger is None else float(fpr_delta_vs_trigger)

    # SELECTIVE ≡ INCREMENTAL_SELECTIVE criteria from composite_search_spec_v1.
    selective_ok = (
        pd_trig >= 0.05
        and pos_folds >= require_usable_folds
        and recall is not None
        and recall >= 0.20
        and fpr_d is not None
        and fpr_d < 0
    )
    balanced_ok = (
        pd_trig > 0
        and pos_folds >= require_usable_folds
        and recall is not None
        and recall >= 0.50
        and fpr_d is not None
        and fpr_d <= 0
    )

    # Prefer SELECTIVE when both gates pass (stricter precision / FPR).
    if selective_ok:
        return "SELECTIVE"
    if balanced_ok:
        return "INCREMENTAL_BALANCED"
    if pd_trig > 0:
        return "WEAK_INCREMENTAL"
    return "NO_INCREMENTAL_EDGE"


def is_survivor_class(composite_class: str) -> bool:
    return composite_class in {"INCREMENTAL_BALANCED", "SELECTIVE"}


def classification_payload(
    *,
    composite_class: str,
    usable_folds: int,
    positive_delta_folds: int,
) -> dict[str, Any]:
    return {
        "composite_class": composite_class,
        "usable_folds": usable_folds,
        "positive_delta_folds": positive_delta_folds,
        "is_survivor": is_survivor_class(composite_class),
    }
