from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pyarrow as pa

from crypto_trading_bot.research_v2.market_data.bars_service import TimeframeBarService, verify_interval
from crypto_trading_bot.research_v2.resampling import resample_table


def _one_minute_table(start: datetime, rows: int) -> pa.Table:
    opens = [start + timedelta(minutes=i) for i in range(rows)]
    return pa.Table.from_pydict(
        {
            "open_time_utc": opens,
            "open": [Decimal("100")] * rows,
            "high": [Decimal("101")] * rows,
            "low": [Decimal("99")] * rows,
            "close": [Decimal("100.5")] * rows,
            "volume": [Decimal("1")] * rows,
            "trade_count": [1] * rows,
        }
    )


def test_resample_produces_true_four_hour_spacing(tmp_path):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    candles = resample_table(_one_minute_table(start, 60 * 24 * 30), "4H")
    assert len(candles) == 6 * 30
    serialized = [
        {"open_time_utc": c.open_time_utc.isoformat(), "close_time_utc": c.close_time_utc.isoformat(), "open": "1", "high": "1", "low": "1", "close": "1", "volume": "1", "trade_count": 1}
        for c in candles
    ]
    audit = verify_interval(serialized, "4H")
    assert audit["interval_check"] == "PASS"


def test_four_hour_and_one_day_counts_differ_for_same_window(tmp_path, monkeypatch):
    service = TimeframeBarService(symbol="ETHUSDT", canonical_root=tmp_path / "1m", cache_root=tmp_path / "cache")
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    month_dir = tmp_path / "1m" / "2024"
    month_dir.mkdir(parents=True)
    table = _one_minute_table(start, 60 * 24 * 40)
    import pyarrow.parquet as pq

    pq.write_table(table, month_dir / "ETHUSDT-1m-2024-01.parquet")
    end = start + timedelta(days=30)
    four_h = service.get_bars("4H", before=end, after=start, limit=1000)
    one_d = service.get_bars("1D", before=end, after=start, limit=1000)
    assert 170 <= len(four_h) <= 190
    assert 28 <= len(one_d) <= 32
    assert len(four_h) != len(one_d)
