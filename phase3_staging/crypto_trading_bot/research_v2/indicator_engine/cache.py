"""Cache for batch indicator series (research performance)."""
from __future__ import annotations

from typing import Any, Hashable

from .types import IndicatorResult
from .version import INDICATOR_ENGINE_VERSION


class SeriesCache:
    def __init__(self) -> None:
        self._store: dict[Hashable, IndicatorResult] = {}

    @staticmethod
    def make_key(
        *,
        market_data_version: str,
        timeframe: str,
        indicator_id: str,
        parameter_set_id: str,
        bars_fingerprint: str,
    ) -> tuple:
        return (
            INDICATOR_ENGINE_VERSION,
            market_data_version,
            timeframe,
            indicator_id,
            parameter_set_id,
            bars_fingerprint,
        )

    def get(self, key: Hashable) -> IndicatorResult | None:
        return self._store.get(key)

    def put(self, key: Hashable, value: IndicatorResult) -> IndicatorResult:
        self._store[key] = value
        return value

    def clear(self) -> None:
        self._store.clear()


def fingerprint_bars(bars: list[dict[str, Any]]) -> str:
    if not bars:
        return "empty"
    first = bars[0].get("open_time")
    last = bars[-1].get("close_time")
    return f"{len(bars)}|{first}|{last}|{bars[0].get('close')}|{bars[-1].get('close')}"
