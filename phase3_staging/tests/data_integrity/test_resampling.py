from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pyarrow as pa
import pytest

from crypto_trading_bot.research_v2.resampling import resample_table


def _table(count: int, start_minute: int = 0) -> pa.Table:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=start_minute)
    return pa.table(
        {
            "open_time_utc": [start + timedelta(minutes=i) for i in range(count)],
            "open": pa.array([Decimal(i + 1) for i in range(count)], type=pa.decimal128(18, 8)),
            "high": pa.array([Decimal(i + 2) for i in range(count)], type=pa.decimal128(18, 8)),
            "low": pa.array([Decimal(i) for i in range(count)], type=pa.decimal128(18, 8)),
            "close": pa.array([Decimal(i + 1) for i in range(count)], type=pa.decimal128(18, 8)),
            "volume": pa.array([Decimal(1) for _ in range(count)], type=pa.decimal128(18, 8)),
            "trade_count": list(range(1, count + 1)),
        }
    )


def test_resampling_marks_complete_and_incomplete_buckets() -> None:
    complete = resample_table(_table(5), "5m")
    assert len(complete) == 1
    assert complete[0].complete is True
    assert complete[0].source_rows == 5
    incomplete = resample_table(_table(3), "5m")
    assert incomplete[0].complete is False
    assert incomplete[0].source_rows == 3


def test_resampling_rejects_duplicate_or_unsorted_timestamps() -> None:
    table = _table(2)
    duplicate = table.set_column(0, "open_time_utc", pa.array([table[0][0].as_py()] * 2, type=table["open_time_utc"].type))
    with pytest.raises(ValueError, match="strictly increasing"):
        resample_table(duplicate, "5m")
