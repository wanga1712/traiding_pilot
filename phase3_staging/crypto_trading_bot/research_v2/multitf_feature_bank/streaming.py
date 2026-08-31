"""Incremental streaming updates — recomputes only on new closed bar."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .snapshot import FeatureBank, FeatureSnapshot


@dataclass
class StreamingFeatureBank:
    """Append-only bar buffers with cached last snapshot."""

    bank: FeatureBank
    _last_snapshot: FeatureSnapshot | None = field(default=None, init=False)
    _bar_counts: dict[str, int] = field(default_factory=dict, init=False)

    def on_bar_closed(self, timeframe: str, bar: dict[str, Any]) -> FeatureSnapshot:
        bars = self.bank.bars_by_tf.setdefault(timeframe, [])
        prev = self._bar_counts.get(timeframe, 0)
        if len(bars) > prev:
            bars[-1] = bar
        else:
            bars.append(bar)
        self._bar_counts[timeframe] = len(bars)
        self.bank._cache.clear()
        ct = bar.get("close_time")
        if isinstance(ct, str):
            from crypto_trading_bot.research_v2.indicator_engine.bars import parse_ts

            dt = parse_ts(ct)
        else:
            dt = ct
        self._last_snapshot = self.bank.snapshot(dt)
        return self._last_snapshot

    @property
    def last_snapshot(self) -> FeatureSnapshot | None:
        return self._last_snapshot
