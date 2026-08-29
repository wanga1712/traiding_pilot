"""Causal input guards and rolling helpers."""
from __future__ import annotations

from typing import Any, Sequence

import numpy as np

from .version import FORBIDDEN_INPUT_KEYS


def assert_no_forbidden_fields(bars: Sequence[dict[str, Any]]) -> None:
    if not bars:
        return
    keys = set()
    for b in bars[:50]:  # sample
        keys.update(b.keys())
    bad = keys & FORBIDDEN_INPUT_KEYS
    if bad:
        raise ValueError(f"forbidden retrospective/outcome fields in causal inputs: {sorted(bad)}")


def sanitize_bars(bars: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop forbidden keys if present (defense in depth) and assert they were not relied upon."""
    assert_no_forbidden_fields(bars)
    allowed = {
        "open_time",
        "close_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "event_id",
        "timeframe",
        "bar_index_relative_to_pivot",  # alignment only — not used in formulas
    }
    out = []
    for b in bars:
        out.append({k: b[k] for k in b if k in allowed or k in ("open_time", "close_time", "open", "high", "low", "close", "volume")})
    return out


def rolling_median(x: np.ndarray, window: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    for i in range(window - 1, len(x)):
        out[i] = float(np.median(x[i - window + 1 : i + 1]))
    return out


def percentile_rank(x: np.ndarray, window: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    for i in range(window - 1, len(x)):
        w = x[i - window + 1 : i + 1]
        out[i] = float(np.sum(w <= x[i]) / window * 100.0)
    return out


def overlap_ratio(h0: float, l0: float, h1: float, l1: float) -> float:
    top = min(h0, h1)
    bot = max(l0, l1)
    overlap = max(0.0, top - bot)
    denom = max(h0 - l0, h1 - l1, 1e-12)
    return overlap / denom
