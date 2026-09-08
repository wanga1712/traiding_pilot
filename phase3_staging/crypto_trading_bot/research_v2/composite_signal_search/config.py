"""Frozen composite search configuration — corpus, folds, TF roles, constants."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from crypto_trading_bot.research_v2.indicator_parameter_search.config import (
    EVENT_DIR,
    MAX_DELAY_SECONDS,
    TF_BAR_SECONDS,
)

__all__ = [
    "ARTIFACT_ROOT",
    "PARENT_ARTIFACT_ROOT",
    "EVENT_DIR",
    "REPO_ROOT",
    "DEVELOPMENT_START",
    "DEVELOPMENT_END",
    "DEVELOPMENT_FOLDS",
    "VALIDATION_PARITY_START",
    "VALIDATION_PARITY_END",
    "TF_ROLES",
    "SEARCH_TFS",
    "MAX_DELAY_SECONDS",
    "TF_BAR_SECONDS",
    "NEAR_REDUNDANCY_JACCARD",
    "ATOMIC_REPRESENTATIVE_CAP",
    "USABLE_FOLD_MIN_SIGNALS",
    "REQUIRE_USABLE_FOLDS",
    "SAMPLE_NORMAL_MIN",
    "SAMPLE_LOW_MIN",
    "COMPOSITE_FDR_STATUS",
    "OOS_OPENED",
    "ATOMIC_INDICATOR_RECOMPUTE_PER_COMPOSITE",
    "MAX_COMPOSITE_COMPONENTS",
    "load_json",
    "load_search_spec",
    "load_templates",
    "load_atomic_bank",
    "load_development_corpus_manifest",
]

_pkg_root = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(os.environ.get("TRAIDING_PILOT_REPO_ROOT", str(_pkg_root.parent)))

ARTIFACT_ROOT = Path(
    os.environ.get(
        "COMPOSITE_SIGNAL_SEARCH_ARTIFACT_ROOT",
        str(REPO_ROOT / "artifacts" / "MULTITF-COMPOSITE-SIGNAL-SEARCH-1"),
    )
)
PARENT_ARTIFACT_ROOT = Path(
    os.environ.get(
        "INDICATOR_PARAM_SEARCH_ARTIFACT_ROOT",
        str(REPO_ROOT / "artifacts" / "MULTITF-INDICATOR-PARAMETER-SEARCH-1"),
    )
)

DEVELOPMENT_START = datetime(2019, 5, 12, 0, 0, 0, tzinfo=timezone.utc)
DEVELOPMENT_END = datetime(2023, 6, 20, 6, 8, 0, tzinfo=timezone.utc)

DEVELOPMENT_FOLDS: list[tuple[str, datetime, datetime]] = [
    (
        "FOLD_1",
        datetime(2019, 5, 12, 0, 0, 0, tzinfo=timezone.utc),
        datetime(2020, 5, 21, 1, 32, 0, tzinfo=timezone.utc),
    ),
    (
        "FOLD_2",
        datetime(2020, 5, 21, 1, 32, 0, tzinfo=timezone.utc),
        datetime(2021, 5, 31, 3, 4, 0, tzinfo=timezone.utc),
    ),
    (
        "FOLD_3",
        datetime(2021, 5, 31, 3, 4, 0, tzinfo=timezone.utc),
        datetime(2022, 6, 10, 4, 36, 0, tzinfo=timezone.utc),
    ),
    (
        "FOLD_4",
        datetime(2022, 6, 10, 4, 36, 0, tzinfo=timezone.utc),
        datetime(2023, 6, 20, 6, 8, 0, tzinfo=timezone.utc),
    ),
]

# Parent Validation window — parity only (still inside DEVELOPMENT corpus).
VALIDATION_PARITY_START = datetime(2022, 6, 10, 4, 36, 0, tzinfo=timezone.utc)
VALIDATION_PARITY_END = datetime(2023, 6, 20, 6, 8, 0, tzinfo=timezone.utc)

TF_ROLES: dict[str, str] = {
    "4H": "REGIME_CONTEXT",
    "6H": "REGIME_CONTEXT",
    "8H": "REGIME_CONTEXT",
    "12H": "REGIME_CONTEXT",
    "1H": "DIRECTION_ANCHOR",
    "2H": "DIRECTION_ANCHOR",
    "30m": "TRANSITION_TRIGGER",
    "15m": "MICRO_TRIGGER",
    "5m": "MICRO_TRIGGER",
    "1D": "DIAGNOSTIC_ONLY",
}

SEARCH_TFS: tuple[str, ...] = (
    "5m",
    "15m",
    "30m",
    "1H",
    "2H",
    "4H",
    "6H",
    "8H",
    "12H",
    "1D",
)

NEAR_REDUNDANCY_JACCARD = 0.95
ATOMIC_REPRESENTATIVE_CAP = 2
USABLE_FOLD_MIN_SIGNALS = 5
REQUIRE_USABLE_FOLDS = 3
SAMPLE_NORMAL_MIN = 100
SAMPLE_LOW_MIN = 30

COMPOSITE_FDR_STATUS = "NOT_USED"
OOS_OPENED = "NO"
ATOMIC_INDICATOR_RECOMPUTE_PER_COMPOSITE = "NO"
MAX_COMPOSITE_COMPONENTS = 3


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_search_spec(*, root: Path | None = None) -> dict[str, Any]:
    return load_json((root or ARTIFACT_ROOT) / "composite_search_spec_v1.json")


def load_templates(*, root: Path | None = None) -> dict[str, Any]:
    return load_json((root or ARTIFACT_ROOT) / "composite_templates_v1.json")


def load_atomic_bank(*, root: Path | None = None) -> dict[str, Any]:
    return load_json((root or ARTIFACT_ROOT) / "composite_atomic_bank_v1.json")


def load_development_corpus_manifest(*, root: Path | None = None) -> dict[str, Any]:
    return load_json((root or ARTIFACT_ROOT) / "development_corpus_manifest_v1.json")
