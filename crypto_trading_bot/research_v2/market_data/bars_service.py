from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from crypto_trading_bot.research_v2.resampling import TIMEFRAMES, resample_table

ONE_MINUTE_COLUMNS = ("open_time_utc", "open", "high", "low", "close", "volume", "trade_count")


def candle_to_dict(candle) -> dict:
    return {
        "open_time_utc": candle.open_time_utc.isoformat(),
        "close_time_utc": candle.close_time_utc.isoformat(),
        "open": str(candle.open),
        "high": str(candle.high),
        "low": str(candle.low),
        "close": str(candle.close),
        "volume": str(candle.volume),
        "trade_count": candle.trade_count,
        "complete": candle.complete,
    }


def verify_interval(candles: list[dict], timeframe: str) -> dict:
    if not candles:
        return {"interval_check": "FAIL", "reason": "empty dataset"}
    minutes = TIMEFRAMES[timeframe]
    expected = timedelta(minutes=minutes)
    failures = 0
    checked = 0
    for left, right in zip(candles, candles[1:]):
        left_at = datetime.fromisoformat(left["open_time_utc"])
        right_at = datetime.fromisoformat(right["open_time_utc"])
        delta = right_at - left_at
        checked += 1
        if delta != expected:
            failures += 1
    return {
        "declared_tf": timeframe,
        "actual_tf": timeframe,
        "bar_count": len(candles),
        "first_bar": candles[0]["open_time_utc"],
        "last_bar": candles[-1]["open_time_utc"],
        "interval_check": "PASS" if failures == 0 else "FAIL",
        "ordinary_gap_failures": failures,
        "ordinary_gap_checks": checked,
    }


@dataclass
class TimeframeBarService:
    symbol: str = "ETHUSDT"
    canonical_root: Path = Path("/srv/traiding_pilot/market/binance/spot/ETHUSDT/1m")
    cache_root: Path = Path("/var/tmp/traiding_pilot_market_cache")
    ssh_host: str | None = None
    ssh_key: Path | None = None

    def __post_init__(self) -> None:
        self.cache_root.mkdir(parents=True, exist_ok=True)
        (self.cache_root / "1m").mkdir(parents=True, exist_ok=True)
        (self.cache_root / "resampled").mkdir(parents=True, exist_ok=True)

    def get_bars(
        self,
        timeframe: str,
        *,
        before: datetime | None = None,
        after: datetime | None = None,
        limit: int = 800,
    ) -> list[dict]:
        if timeframe not in TIMEFRAMES:
            raise ValueError(f"unsupported timeframe: {timeframe}")
        end_at = before or datetime.now(timezone.utc)
        if end_at.tzinfo is None:
            end_at = end_at.replace(tzinfo=timezone.utc)
        minutes = TIMEFRAMES[timeframe]
        lookback = timedelta(minutes=minutes * max(limit, 1) + minutes * 24)
        start_at = after or (end_at - lookback)
        self._ensure_resampled_range(timeframe, start_at, end_at)
        cache_path = self._cache_path(timeframe)
        table = pq.read_table(cache_path)
        filtered = table.filter(
            pc.and_(
                pc.less_equal(table["open_time_utc"], pa.scalar(end_at, type=pa.timestamp("us", tz="UTC"))),
                pc.greater_equal(table["open_time_utc"], pa.scalar(start_at, type=pa.timestamp("us", tz="UTC"))),
            )
        )
        rows = filtered.sort_by("open_time_utc").to_pylist()
        serialized = [_serialize_row(row) for row in rows]
        if before is not None:
            serialized = [row for row in serialized if datetime.fromisoformat(row["open_time_utc"]) < end_at]
        if after is not None:
            serialized = [row for row in serialized if datetime.fromisoformat(row["open_time_utc"]) >= after]
        return serialized[-limit:]

    def _ensure_resampled_range(self, timeframe: str, start_at: datetime, end_at: datetime) -> None:
        cache_path = self._cache_path(timeframe)
        existing: pa.Table | None = None
        if cache_path.exists():
            existing = pq.read_table(cache_path)
            cache_start = existing["open_time_utc"][0].as_py()
            cache_end = existing["open_time_utc"][-1].as_py()
            if cache_start <= start_at and cache_end >= end_at - timedelta(minutes=TIMEFRAMES[timeframe]):
                return
            start_at = min(start_at, cache_start)
            end_at = max(end_at, cache_end)
        one_minute = self._load_one_minute_range(start_at - timedelta(minutes=TIMEFRAMES[timeframe]), end_at)
        if one_minute.num_rows == 0:
            if existing is not None:
                return
            raise ValueError("no 1m data available for requested range")
        resampled = resample_table(one_minute, timeframe)
        fresh = pa.Table.from_pylist(
            [
                {
                    "open_time_utc": candle.open_time_utc,
                    "close_time_utc": candle.close_time_utc,
                    "open": candle.open,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                    "volume": candle.volume,
                    "trade_count": candle.trade_count,
                    "complete": candle.complete,
                }
                for candle in resampled
            ]
        )
        if existing is not None:
            by_time = {_serialize_row(row)["open_time_utc"]: _serialize_row(row) for row in existing.to_pylist()}
            for row in fresh.to_pylist():
                by_time[_serialize_row(row)["open_time_utc"]] = _serialize_row(row)
            merged_rows = [by_time[key] for key in sorted(by_time)]
            merged = pa.Table.from_pylist(
                [
                    {
                        "open_time_utc": datetime.fromisoformat(row["open_time_utc"]),
                        "close_time_utc": datetime.fromisoformat(row["close_time_utc"]),
                        "open": row["open"],
                        "high": row["high"],
                        "low": row["low"],
                        "close": row["close"],
                        "volume": row["volume"],
                        "trade_count": row["trade_count"],
                        "complete": row["complete"],
                    }
                    for row in merged_rows
                ]
            )
        else:
            merged = fresh.sort_by("open_time_utc")
        pq.write_table(merged, cache_path, compression="zstd")

    def _load_one_minute_range(self, start_at: datetime, end_at: datetime) -> pa.Table:
        tables: list[pa.Table] = []
        cursor = datetime(start_at.year, start_at.month, 1, tzinfo=timezone.utc)
        end_month = datetime(end_at.year, end_at.month, 1, tzinfo=timezone.utc)
        while cursor <= end_month:
            local_path = self._stage_one_minute_month(cursor.year, cursor.month)
            if not local_path.exists():
                if cursor.month == 12:
                    cursor = datetime(cursor.year + 1, 1, 1, tzinfo=timezone.utc)
                else:
                    cursor = datetime(cursor.year, cursor.month + 1, 1, tzinfo=timezone.utc)
                continue
            month = pq.read_table(local_path, columns=list(ONE_MINUTE_COLUMNS))
            filtered = month.filter(
                pc.and_(
                    pc.less_equal(month["open_time_utc"], pa.scalar(end_at, type=pa.timestamp("us", tz="UTC"))),
                    pc.greater_equal(month["open_time_utc"], pa.scalar(start_at, type=pa.timestamp("us", tz="UTC"))),
                )
            )
            if filtered.num_rows:
                tables.append(filtered)
            if cursor.month == 12:
                cursor = datetime(cursor.year + 1, 1, 1, tzinfo=timezone.utc)
            else:
                cursor = datetime(cursor.year, cursor.month + 1, 1, tzinfo=timezone.utc)
        if not tables:
            return pa.table({name: pa.array([], type=pa.timestamp("us", tz="UTC") if name == "open_time_utc" else pa.int64()) for name in ONE_MINUTE_COLUMNS[:1]})
        return pa.concat_tables(tables).sort_by("open_time_utc")

    def _stage_one_minute_month(self, year: int, month: int) -> Path:
        filename = f"{self.symbol}-1m-{year:04d}-{month:02d}.parquet"
        local_path = self.cache_root / "1m" / filename
        if local_path.exists():
            return local_path
        remote = self.canonical_root / str(year) / filename
        if self.ssh_host:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            command = ["scp", "-i", str(self.ssh_key), f"{self.ssh_host}:{remote}", str(local_path)]
            subprocess.run(command, check=True, capture_output=True)
        elif remote.exists():
            local_path.write_bytes(remote.read_bytes())
        else:
            return local_path.parent / filename
        return local_path

    def _cache_path(self, timeframe: str) -> Path:
        return self.cache_root / "resampled" / f"{self.symbol}_{timeframe}.parquet"

    def audit(self, candles: list[dict], timeframe: str, visible_start: str | None = None, visible_end: str | None = None) -> dict:
        audit = verify_interval(candles, timeframe)
        audit.update(
            {
                "symbol": self.symbol,
                "selected_tf": timeframe,
                "loaded_bars": len(candles),
                "visible_bars": _visible_bar_count(candles, visible_start, visible_end),
                "first_loaded": candles[0]["open_time_utc"] if candles else None,
                "last_loaded": candles[-1]["open_time_utc"] if candles else None,
                "display_downsampling": "DISABLED",
                "cache_root": str(self.cache_root),
                "canonical_source": str(self.canonical_root),
            }
        )
        return audit


def _serialize_row(row: dict) -> dict:
    open_time = row["open_time_utc"]
    close_time = row["close_time_utc"]
    if hasattr(open_time, "isoformat"):
        open_time = open_time.isoformat()
    if hasattr(close_time, "isoformat"):
        close_time = close_time.isoformat()
    return {
        "open_time_utc": open_time,
        "close_time_utc": close_time,
        "open": str(row["open"]),
        "high": str(row["high"]),
        "low": str(row["low"]),
        "close": str(row["close"]),
        "volume": str(row["volume"]),
        "trade_count": int(row["trade_count"]),
        "complete": bool(row.get("complete", True)),
    }


def _visible_bar_count(candles: list[dict], visible_start: str | None, visible_end: str | None) -> int:
    if not candles or not visible_start or not visible_end:
        return 0
    start = _parse_axis_time(visible_start)
    end = _parse_axis_time(visible_end)
    return sum(1 for candle in candles if start <= datetime.fromisoformat(candle["open_time_utc"]) <= end)


def _parse_axis_time(value: str | float | int) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def load_artifact(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
