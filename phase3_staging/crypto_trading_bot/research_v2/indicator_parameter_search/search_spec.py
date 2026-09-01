"""Frozen search specification writer."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .candidate_registry import build_candidate_registry, registry_summary
from .config import (
    ACTIVE_SPLITS,
    ARTIFACT_ROOT,
    BOOTSTRAP_BLOCKS,
    BOOTSTRAP_SEED,
    DISCOVERY_SHORTLIST_CAP_PER_FAMILY,
    DNO_ONE_FACTOR_AXES,
    EVENT_PRIMITIVES,
    FDR_ALPHA,
    FROZEN_PREDICTOR_REFERENCE,
    MAX_COMBINED_PREDICTOR_CONFIGS_PER_TF_DIR,
    MAX_DELAY_SECONDS,
    REDUNDANCY_CORR,
    REDUNDANCY_JACCARD,
    SEARCH_TFS,
    TF_BAR_SECONDS,
    discovery_fold_bounds,
    split_bounds,
)
from .version import (
    BASE_COMMIT,
    FORMULA_AUTHORITY_COMMIT,
    FULL_HISTORY_GAP_AUDIT_COMMIT,
    OSCILLATOR_PREDICTOR_AUTHORITY,
    STUDY_VERSION,
    WIP_ID,
)


def build_search_spec() -> dict[str, Any]:
    folds = discovery_fold_bounds()
    registry = build_candidate_registry()
    return {
        "wip_id": WIP_ID,
        "study_version": STUDY_VERSION,
        "base_commit": BASE_COMMIT,
        "formula_authority_commit": FORMULA_AUTHORITY_COMMIT,
        "full_history_gap_audit_commit": FULL_HISTORY_GAP_AUDIT_COMMIT,
        "oscillator_predictor_authority": OSCILLATOR_PREDICTOR_AUTHORITY,
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "parameter_optimization_scope": "DISCOVERY_ONLY",
        "signal_combination_search": False,
        "trading_pnl": False,
        "oos_opened": False,
        "splits": {
            "DISCOVERY": [split_bounds("DISCOVERY")[0].isoformat(), split_bounds("DISCOVERY")[1].isoformat()],
            "VALIDATION": [split_bounds("VALIDATION")[0].isoformat(), split_bounds("VALIDATION")[1].isoformat()],
            "OOS": "LOCKED",
        },
        "discovery_folds": [
            {"fold": i + 1, "start": f[0].isoformat(), "end": f[1].isoformat()} for i, f in enumerate(folds)
        ],
        "search_timeframes": list(SEARCH_TFS),
        "active_splits": list(ACTIVE_SPLITS),
        "event_primitives": EVENT_PRIMITIVES,
        "dno_one_factor_axes": DNO_ONE_FACTOR_AXES,
        "frozen_predictor_reference": {
            "period": FROZEN_PREDICTOR_REFERENCE.period,
            "peak_strength": FROZEN_PREDICTOR_REFERENCE.peak_strength,
            "lookback": FROZEN_PREDICTOR_REFERENCE.lookback,
            "samples": FROZEN_PREDICTOR_REFERENCE.samples,
            "ob_os_level_percent": FROZEN_PREDICTOR_REFERENCE.ob_os_level_percent,
        },
        "max_combined_predictor_configs_per_tf_direction": MAX_COMBINED_PREDICTOR_CONFIGS_PER_TF_DIR,
        "discovery_shortlist_cap_per_family": DISCOVERY_SHORTLIST_CAP_PER_FAMILY,
        "redundancy_jaccard_threshold": REDUNDANCY_JACCARD,
        "redundancy_correlation_threshold": REDUNDANCY_CORR,
        "fdr_alpha": FDR_ALPHA,
        "multiple_comparison_method": "BLOCK_BOOTSTRAP_BH_FDR",
        "bootstrap_seed": BOOTSTRAP_SEED,
        "bootstrap_blocks": BOOTSTRAP_BLOCKS,
        "max_delay_seconds": MAX_DELAY_SECONDS,
        "tf_bar_seconds": TF_BAR_SECONDS,
        "matching_authority": "REVERSAL_SIGNAL_EVENT_STUDY_V1",
        "label_authority": "REVERSAL_EVENT_DATASET_V1",
        "true_pivot_as_feature": "NO",
        "price_baseline_authority": "REVERSAL_SIGNAL_EVENT_STUDY_V1",
        "minimum_samples": {
            "discovery_total_preferred": 100,
            "discovery_fold_preferred": 30,
            "validation_normal": 100,
            "validation_low_sample": 30,
            "validation_insufficient": 30,
        },
        "selection_objectives": [
            "precision_delta_vs_price_baseline HIGHER",
            "recall HIGHER",
            "false_positive_rate LOWER",
            "median_delay LOWER",
            "premature_signal_rate LOWER",
            "median_mae_atr LOWER",
            "signal_coverage sufficient",
        ],
        "discovery_fold_stability_rule": "positive_primary_in_at_least_2_of_3_folds",
        "validation_stability_classes": [
            "STABLE_POSITIVE",
            "WEAK_POSITIVE",
            "UNSTABLE",
            "NEGATIVE",
            "INSUFFICIENT_SAMPLE",
        ],
        "candidate_registry_counts": registry_summary(registry),
        "total_candidate_rows": len(registry),
        "composite_search_forbidden": True,
    }


def write_search_spec(artifact_root: Path | None = None) -> Path:
    root = artifact_root or ARTIFACT_ROOT
    root.mkdir(parents=True, exist_ok=True)
    spec = build_search_spec()
    (root / "search_spec_v1.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    md = f"""# MULTITF-INDICATOR-PARAMETER-SEARCH-1 — Search Spec v1

WIP: {WIP_ID}
Study: {STUDY_VERSION}
Frozen: {spec['frozen_at']}

## Purpose
Per-timeframe indicator parameter discovery (NOT composite, NOT trading, NOT OOS).

## Authorities
- Formula: `{FORMULA_AUTHORITY_COMMIT}`
- Gap audit: `{FULL_HISTORY_GAP_AUDIT_COMMIT}`
- Oscillator predictor: `{OSCILLATOR_PREDICTOR_AUTHORITY}`

## Splits
- DISCOVERY: {spec['splits']['DISCOVERY'][0]} → {spec['splits']['DISCOVERY'][1]}
- VALIDATION: {spec['splits']['VALIDATION'][0]} → {spec['splits']['VALIDATION'][1]}
- OOS: LOCKED

## Discovery folds
{chr(10).join(f"- FOLD_{f['fold']}: {f['start']} → {f['end']}" for f in spec['discovery_folds'])}

## Candidate families
DMA, STOCHASTIC, MACD, DNO_PREDICTOR, OSC_PREDICTOR, INVERSE_PREDICTOR (executable only)

Total registry rows: {spec['total_candidate_rows']}

## DNO controlled sweeps (one-factor-at-a-time)
Axes: {list(DNO_ONE_FACTOR_AXES.keys())}

## Selection
- Pareto on precision delta, recall, FPR, delay, premature rate, MAE
- BH-FDR q={FDR_ALPHA}
- Redundancy Jaccard>={REDUNDANCY_JACCARD}
- Shortlist cap {DISCOVERY_SHORTLIST_CAP_PER_FAMILY} per TF/direction/family (non-reference)

No composite search. No monetary PnL.
"""
    (root / "search_spec_v1.md").write_text(md, encoding="utf-8")
    return root / "search_spec_v1.json"
