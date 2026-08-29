"""Incremental streaming state — must match batch for compression duration features."""
from __future__ import annotations

from typing import Any

from crypto_trading_bot.research_v2.indicator_engine.bars import bars_to_arrays

from .compute import compute_compression_expansion_duration
from .guards import sanitize_bars
from .types import FeatureSample


def stream_compression_expansion(
    bars: list[dict[str, Any]],
    *,
    source_timeframe: str,
    short_window: int = 10,
    long_window: int = 50,
    threshold: float = 0.5,
) -> list[FeatureSample]:
    """
    One-by-one streaming: at step i, recompute using only bars[:i+1].
    For stateful counters this matches batch because counters are causal functions
    of history prefixes. We assert equality in tests against full-batch result.
    """
    clean = sanitize_bars(bars)
    out: list[FeatureSample] = []
    for i in range(len(clean)):
        prefix = clean[: i + 1]
        arrays = bars_to_arrays(prefix, timeframe=source_timeframe)
        series = compute_compression_expansion_duration(arrays, short_window, long_window, threshold)
        out.append(series[-1])
    return out


def batch_compression_expansion(
    bars: list[dict[str, Any]],
    *,
    source_timeframe: str,
    short_window: int = 10,
    long_window: int = 50,
    threshold: float = 0.5,
) -> list[FeatureSample]:
    arrays = bars_to_arrays(sanitize_bars(bars), timeframe=source_timeframe)
    return compute_compression_expansion_duration(arrays, short_window, long_window, threshold)
