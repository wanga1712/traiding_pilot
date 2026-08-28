from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pyarrow as pa


TIMEFRAMES = {"5m": 5, "1H": 60, "2H": 120, "4H": 240, "6H": 360, "8H": 480, "12H": 720, "1D": 1440}
UI_TIMEFRAMES = ("1H", "2H", "4H", "6H", "8H", "12H", "1D")


@dataclass(frozen=True, slots=True)
class ResampledCandle:
    open_time_utc: datetime
    close_time_utc: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    trade_count: int
    source_rows: int
    expected_rows: int
    complete: bool


def _bucket_start(value: datetime, minutes: int) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError("timestamps must be timezone-aware UTC")
    epoch_minutes = int(value.timestamp()) // 60
    return datetime.fromtimestamp((epoch_minutes // minutes) * minutes * 60, tz=timezone.utc)


def resample_table(table: pa.Table, timeframe: str) -> list[ResampledCandle]:
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    minutes = TIMEFRAMES[timeframe]
    data = table.to_pydict()
    rows = zip(data["open_time_utc"], data["open"], data["high"], data["low"], data["close"], data["volume"], data["trade_count"])
    buckets: list[ResampledCandle] = []
    current_start = None
    values = []
    for row in rows:
        start = _bucket_start(row[0], minutes)
        if current_start is not None and start != current_start:
            buckets.append(_aggregate(current_start, minutes, values))
            values = []
        current_start = start
        values.append(row)
    if values:
        buckets.append(_aggregate(current_start, minutes, values))
    return buckets


def _aggregate(start: datetime, minutes: int, rows: list[tuple]) -> ResampledCandle:
    observed = {row[0] for row in rows}
    complete = len(rows) == minutes and all(start + timedelta(minutes=i) in observed for i in range(minutes))
    return ResampledCandle(
        open_time_utc=start,
        close_time_utc=start + timedelta(minutes=minutes) - timedelta(microseconds=1),
        open=rows[0][1],
        high=max(row[2] for row in rows),
        low=min(row[3] for row in rows),
        close=rows[-1][4],
        volume=sum((row[5] for row in rows), Decimal(0)),
        trade_count=sum(row[6] for row in rows),
        source_rows=len(rows),
        expected_rows=minutes,
        complete=complete,
    )
