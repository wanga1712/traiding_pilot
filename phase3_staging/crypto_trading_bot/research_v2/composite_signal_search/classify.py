"""Canonical composite class naming + frozen threshold classification."""
from __future__ import annotations

from typing import Any, Sequence

from .config import REQUIRE_USABLE_FOLDS, USABLE_FOLD_MIN_SIGNALS

# Canonical frozen names (composite_search_spec_v1).
CANONICAL_SELECTIVE_CLASS = "INCREMENTAL_SELECTIVE"
SURVIVOR_CLASSES = frozenset({"INCREMENTAL_BALANCED", "INCREMENTAL_SELECTIVE"})
# Historical alias — do not emit in new final artifacts.
LEGACY_SELECTIVE_ALIAS = "SELECTIVE"


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

    INCREMENTAL_BALANCED / INCREMENTAL_SELECTIVE / WEAK_INCREMENTAL /
    NO_INCREMENTAL_EDGE / INSUFFICIENT

    SELECTIVE_THRESHOLD_CHANGED=NO — criteria unchanged; only the emitted name
    is canonical INCREMENTAL_SELECTIVE (was legacy alias SELECTIVE).
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

    # INCREMENTAL_SELECTIVE criteria from composite_search_spec_v1 (unchanged).
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

    # Prefer INCREMENTAL_SELECTIVE when both gates pass (stricter precision / FPR).
    if selective_ok:
        return CANONICAL_SELECTIVE_CLASS
    if balanced_ok:
        return "INCREMENTAL_BALANCED"
    if pd_trig > 0:
        return "WEAK_INCREMENTAL"
    return "NO_INCREMENTAL_EDGE"


def is_survivor_class(composite_class: str) -> bool:
    # Accept legacy alias for reading historical smoke/parity only.
    if composite_class == LEGACY_SELECTIVE_ALIAS:
        return True
    return composite_class in SURVIVOR_CLASSES


def normalize_class_name(composite_class: str) -> str:
    if composite_class == LEGACY_SELECTIVE_ALIAS:
        return CANONICAL_SELECTIVE_CLASS
    return composite_class


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
