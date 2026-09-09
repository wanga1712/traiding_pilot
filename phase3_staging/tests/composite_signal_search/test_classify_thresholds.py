"""Frozen composite classification threshold tests."""
from __future__ import annotations

from crypto_trading_bot.research_v2.composite_signal_search.classify import (
    CANONICAL_SELECTIVE_CLASS,
    classify_composite,
    fold_is_usable,
    is_survivor_class,
)


def test_fold_usable_threshold():
    assert fold_is_usable(5) is True
    assert fold_is_usable(4) is False


def test_insufficient_on_sample_or_folds():
    assert (
        classify_composite(
            aggregate_sample_flag="INSUFFICIENT",
            precision_delta_vs_trigger=0.1,
            recall_retention_vs_trigger=0.9,
            fpr_delta_vs_trigger=-0.01,
            fold_precision_deltas=[0.1, 0.1, 0.1, 0.1],
            fold_signal_counts=[10, 10, 10, 10],
        )
        == "INSUFFICIENT"
    )
    assert (
        classify_composite(
            aggregate_sample_flag="NORMAL",
            precision_delta_vs_trigger=0.1,
            recall_retention_vs_trigger=0.9,
            fpr_delta_vs_trigger=-0.01,
            fold_precision_deltas=[0.1, 0.1, None, None],
            fold_signal_counts=[10, 10, 2, 2],  # only 2 usable folds
        )
        == "INSUFFICIENT"
    )


def test_selective_and_balanced():
    folds_d = [0.06, 0.07, 0.08, 0.01]
    folds_n = [10, 10, 10, 10]
    assert (
        classify_composite(
            aggregate_sample_flag="NORMAL",
            precision_delta_vs_trigger=0.06,
            recall_retention_vs_trigger=0.25,
            fpr_delta_vs_trigger=-0.01,
            fold_precision_deltas=folds_d,
            fold_signal_counts=folds_n,
        )
        == CANONICAL_SELECTIVE_CLASS
    )
    assert (
        classify_composite(
            aggregate_sample_flag="LOW_SAMPLE",
            precision_delta_vs_trigger=0.02,
            recall_retention_vs_trigger=0.55,
            fpr_delta_vs_trigger=0.0,
            fold_precision_deltas=folds_d,
            fold_signal_counts=folds_n,
        )
        == "INCREMENTAL_BALANCED"
    )


def test_selective_boundary_thresholds_unchanged():
    """SELECTIVE_THRESHOLD_CHANGED=NO — exact frozen boundaries."""
    folds_d = [0.01, 0.02, 0.03, 0.04]
    folds_n = [10, 10, 10, 10]
    # Exact lower bounds for INCREMENTAL_SELECTIVE
    assert (
        classify_composite(
            aggregate_sample_flag="NORMAL",
            precision_delta_vs_trigger=0.05,
            recall_retention_vs_trigger=0.20,
            fpr_delta_vs_trigger=-1e-12,
            fold_precision_deltas=folds_d,
            fold_signal_counts=folds_n,
        )
        == "INCREMENTAL_SELECTIVE"
    )
    # Just below precision delta → not selective
    assert (
        classify_composite(
            aggregate_sample_flag="NORMAL",
            precision_delta_vs_trigger=0.049999,
            recall_retention_vs_trigger=0.20,
            fpr_delta_vs_trigger=-0.01,
            fold_precision_deltas=folds_d,
            fold_signal_counts=folds_n,
        )
        != "INCREMENTAL_SELECTIVE"
    )
    # FPR_DELTA must be strictly < 0
    assert (
        classify_composite(
            aggregate_sample_flag="NORMAL",
            precision_delta_vs_trigger=0.05,
            recall_retention_vs_trigger=0.20,
            fpr_delta_vs_trigger=0.0,
            fold_precision_deltas=folds_d,
            fold_signal_counts=folds_n,
        )
        != "INCREMENTAL_SELECTIVE"
    )
    # Recall retention exact 0.20 ok; 0.199 not
    assert (
        classify_composite(
            aggregate_sample_flag="NORMAL",
            precision_delta_vs_trigger=0.05,
            recall_retention_vs_trigger=0.199,
            fpr_delta_vs_trigger=-0.01,
            fold_precision_deltas=folds_d,
            fold_signal_counts=folds_n,
        )
        != "INCREMENTAL_SELECTIVE"
    )


def test_weak_and_no_edge():
    folds_d = [0.01, 0.02, -0.01, 0.03]
    folds_n = [10, 10, 10, 10]
    assert (
        classify_composite(
            aggregate_sample_flag="NORMAL",
            precision_delta_vs_trigger=0.01,
            recall_retention_vs_trigger=0.1,
            fpr_delta_vs_trigger=0.01,
            fold_precision_deltas=folds_d,
            fold_signal_counts=folds_n,
        )
        == "WEAK_INCREMENTAL"
    )
    assert (
        classify_composite(
            aggregate_sample_flag="NORMAL",
            precision_delta_vs_trigger=0.0,
            recall_retention_vs_trigger=0.9,
            fpr_delta_vs_trigger=-0.01,
            fold_precision_deltas=folds_d,
            fold_signal_counts=folds_n,
        )
        == "NO_INCREMENTAL_EDGE"
    )


def test_survivor_classes():
    assert is_survivor_class("INCREMENTAL_BALANCED")
    assert is_survivor_class("INCREMENTAL_SELECTIVE")
    assert is_survivor_class("SELECTIVE")  # legacy alias read-only
    assert not is_survivor_class("WEAK_INCREMENTAL")
