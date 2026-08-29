"""Shared synthetic bar fixtures for indicator tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def make_bars(
    closes: list[float],
    *,
    start: datetime | None = None,
    minutes: int = 60,
    volume: float = 100.0,
) -> list[dict]:
    start = start or datetime(2020, 1, 1, tzinfo=timezone.utc)
    bars = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c
        h = max(o, c) + 0.5
        l = min(o, c) - 0.5
        ot = start + timedelta(minutes=minutes * i)
        ct = ot + timedelta(minutes=minutes) - timedelta(seconds=0)  # close at next open for simplicity
        # use exclusive close = open + minutes
        ct = ot + timedelta(minutes=minutes)
        bars.append(
            {
                "open_time": ot.isoformat(),
                "close_time": ct.isoformat(),
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "volume": float(volume + i),
            }
        )
    return bars


def make_ohlc_bars(
    rows: list[tuple[float, float, float, float]],
    *,
    start: datetime | None = None,
    minutes: int = 60,
) -> list[dict]:
    start = start or datetime(2020, 1, 1, tzinfo=timezone.utc)
    bars = []
    for i, (o, h, l, c) in enumerate(rows):
        ot = start + timedelta(minutes=minutes * i)
        ct = ot + timedelta(minutes=minutes)
        bars.append(
            {
                "open_time": ot.isoformat(),
                "close_time": ct.isoformat(),
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "volume": 100.0 + i,
            }
        )
    return bars
