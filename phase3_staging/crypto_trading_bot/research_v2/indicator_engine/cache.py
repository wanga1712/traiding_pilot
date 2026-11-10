"""Cache for batch indicator series (research performance)."""
from __future__ import annotations

import hashlib
import json
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
    digest = hashlib.sha256()
    for bar in bars:
        payload = (
            bar.get("open_time"),
            bar.get("close_time"),
            bar.get("open"),
            bar.get("high"),
            bar.get("low"),
            bar.get("close"),
            bar.get("volume", 0.0),
        )
        digest.update(json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()
