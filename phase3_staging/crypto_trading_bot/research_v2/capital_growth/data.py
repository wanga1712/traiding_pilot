from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq


BINANCE_FAPI = "https://fapi.binance.com"
SIX_HOURS_MS = 8 * 60 * 60 * 1000


def _utc_ms(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp() * 1000)


def _atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        frame.to_parquet(temporary, index=False, compression="zstd")
        pq.read_table(temporary)
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _get_json(path: str, params: dict[str, Any], *, timeout: int = 30) -> Any:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{BINANCE_FAPI}{path}?{query}",
        headers={"User-Agent": "TradingPilotCapitalGrowth/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def download_klines(
    *,
    endpoint: str,
    start: datetime,
    end: datetime,
    path: Path,
    interval: str = "1m",
) -> pd.DataFrame:
    cursor = _utc_ms(start)
    end_ms = _utc_ms(end)
    rows: list[list[Any]] = []
    while cursor < end_ms:
        payload = _get_json(
            endpoint,
            {
                "symbol": "ETHUSDT",
                "interval": interval,
                "startTime": cursor,
                "endTime": end_ms - 1,
                "limit": 1500,
            },
        )
        if not payload:
            break
        rows.extend(payload)
        next_cursor = int(payload[-1][0]) + 60_000
        if next_cursor <= cursor:
            raise RuntimeError(f"non-advancing kline cursor: {cursor}")
        cursor = next_cursor
        time.sleep(0.12)
    frame = pd.DataFrame(
        rows,
        columns=[
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_volume",
            "trade_count",
            "taker_buy_volume",
            "taker_buy_quote_volume",
            "ignore",
        ],
    )
    if frame.empty:
        raise RuntimeError(f"no kline data returned for {endpoint}")
    frame["open_time"] = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
    frame["close_time"] = pd.to_datetime(frame["close_time"], unit="ms", utc=True)
    for col in ("open", "high", "low", "close", "volume", "quote_volume"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.drop(columns=["ignore"]).sort_values("open_time").drop_duplicates("open_time")
    frame = frame[(frame["open_time"] >= pd.Timestamp(start)) & (frame["open_time"] < pd.Timestamp(end))]
    _atomic_parquet(frame, path)
    return frame


def download_funding(start: datetime, end: datetime, path: Path) -> pd.DataFrame:
    cursor = _utc_ms(start)
    end_ms = _utc_ms(end)
    rows: list[dict[str, Any]] = []
    while cursor < end_ms:
        payload = _get_json(
            "/fapi/v1/fundingRate",
            {
                "symbol": "ETHUSDT",
                "startTime": cursor,
                "endTime": end_ms - 1,
                "limit": 1000,
            },
        )
        if not payload:
            break
        rows.extend(payload)
        next_cursor = int(payload[-1]["fundingTime"]) + 1
        if next_cursor <= cursor:
            raise RuntimeError(f"non-advancing funding cursor: {cursor}")
        cursor = next_cursor
        time.sleep(0.12)
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise RuntimeError("no funding data returned")
    frame["funding_time"] = pd.to_datetime(frame["fundingTime"], unit="ms", utc=True)
    frame["funding_rate"] = pd.to_numeric(frame["fundingRate"], errors="coerce")
    frame["mark_price"] = pd.to_numeric(frame["markPrice"], errors="coerce")
    frame = frame[["funding_time", "funding_rate", "mark_price", "rateType"]].sort_values("funding_time")
    frame = frame.drop_duplicates("funding_time")
    frame = frame[(frame["funding_time"] >= pd.Timestamp(start)) & (frame["funding_time"] <= pd.Timestamp(end))]
    _atomic_parquet(frame, path)
    return frame


def load_spot_from_cache(cache_root: Path, start: datetime, end: datetime) -> pd.DataFrame:
    start = pd.Timestamp(start)
    end = pd.Timestamp(end)
    rows: list[pd.DataFrame] = []
    cursor = pd.Timestamp(start.year, start.month, 1, tz="UTC")
    last = pd.Timestamp(end.year, end.month, 1, tz="UTC")
    while cursor <= last:
        path = cache_root / "1m" / f"ETHUSDT-1m-{cursor.year:04d}-{cursor.month:02d}.parquet"
        if not path.is_file():
            raise FileNotFoundError(f"missing spot partition: {path}")
        frame = pd.read_parquet(path, columns=["open_time_utc", "open", "high", "low", "close", "volume"])
        rows.append(frame)
        cursor += pd.offsets.MonthBegin(1)
    spot = pd.concat(rows, ignore_index=True).rename(columns={"open_time_utc": "open_time"})
    spot["open_time"] = pd.to_datetime(spot["open_time"], utc=True)
    spot = spot[(spot["open_time"] >= start) & (spot["open_time"] < end)]
    return spot.sort_values("open_time").drop_duplicates("open_time").reset_index(drop=True)


def prepare_dataset(
    *,
    spot_cache_root: Path,
    data_root: Path,
    start: datetime,
    end: datetime,
    download: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    data_root.mkdir(parents=True, exist_ok=True)
    futures_path = data_root / "futures_ETHUSDT_1m.parquet"
    mark_path = data_root / "mark_ETHUSDT_1m.parquet"
    funding_path = data_root / "funding_ETHUSDT.parquet"
    combined_path = data_root / "ETHUSDT_1m_combined.parquet"

    spot = load_spot_from_cache(spot_cache_root, start, end)
    if download:
        futures = download_klines(endpoint="/fapi/v1/klines", start=start, end=end, path=futures_path)
        mark = download_klines(endpoint="/fapi/v1/markPriceKlines", start=start, end=end, path=mark_path)
        funding = download_funding(start, end, funding_path)
    else:
        futures = pd.read_parquet(futures_path)
        mark = pd.read_parquet(mark_path)
        funding = pd.read_parquet(funding_path)

    futures = futures[["open_time", "open", "high", "low", "close"]].rename(
        columns={c: f"futures_{c}" for c in ("open", "high", "low", "close")}
    )
    mark = mark[["open_time", "open", "high", "low", "close"]].rename(
        columns={c: f"mark_{c}" for c in ("open", "high", "low", "close")}
    )
    merged = spot.merge(futures, on="open_time", how="inner", validate="one_to_one")
    merged = merged.merge(mark, on="open_time", how="inner", validate="one_to_one").sort_values("open_time")
    _atomic_parquet(merged, combined_path)

    preflight = data_preflight(
        spot=spot,
        futures=futures,
        mark=mark,
        funding=funding,
        merged=merged,
        start=start,
        end=end,
    )
    preflight["files"] = {
        str(path): {"bytes": path.stat().st_size} for path in (futures_path, mark_path, funding_path, combined_path)
    }
    return merged, funding, preflight


def _gap_stats(times: pd.Series) -> dict[str, Any]:
    ordered = pd.DatetimeIndex(pd.to_datetime(times, utc=True)).sort_values()
    if len(ordered) < 2:
        return {"duplicate_count": 0, "gap_count": 0, "max_gap_minutes": None}
    delta = ordered.to_series().diff().dropna()
    gaps = delta > pd.Timedelta(minutes=1)
    return {
        "duplicate_count": int(ordered.duplicated().sum()),
        "gap_count": int(gaps.sum()),
        "max_gap_minutes": float(delta.loc[gaps].max().total_seconds() / 60.0) if gaps.any() else 0.0,
    }


def data_preflight(
    *,
    spot: pd.DataFrame,
    futures: pd.DataFrame,
    mark: pd.DataFrame,
    funding: pd.DataFrame,
    merged: pd.DataFrame,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    expected_minutes = int((pd.Timestamp(end) - pd.Timestamp(start)).total_seconds() // 60)
    coverage = {
        "spot": len(spot) / expected_minutes,
        "futures": len(futures) / expected_minutes,
        "mark": len(mark) / expected_minutes,
        "combined": len(merged) / expected_minutes,
    }
    spot_stats = _gap_stats(spot["open_time"])
    futures_stats = _gap_stats(futures["open_time"])
    mark_stats = _gap_stats(mark["open_time"])
    funding_times = pd.DatetimeIndex(pd.to_datetime(funding["funding_time"], utc=True)).sort_values()
    expected_funding = max(1, int((pd.Timestamp(end) - pd.Timestamp(start)).total_seconds() // (8 * 3600)))
    funding_coverage = len(funding_times) / expected_funding
    blockers = []
    if min(coverage.values()) < 0.995:
        blockers.append(f"minute_coverage_below_99.5pct:{min(coverage.values()):.6f}")
    if funding_coverage < 0.98:
        blockers.append(f"funding_coverage_below_98pct:{funding_coverage:.6f}")
    if len(funding_times) and funding_times[0] > pd.Timestamp(start) + pd.Timedelta(hours=8):
        blockers.append(f"funding_starts_late:{funding_times[0].isoformat()}")
    if len(funding_times) and funding_times[-1] < pd.Timestamp(end) - pd.Timedelta(hours=16):
        blockers.append(f"funding_ends_early:{funding_times[-1].isoformat()}")
    if spot_stats["duplicate_count"] or futures_stats["duplicate_count"] or mark_stats["duplicate_count"]:
        blockers.append("duplicate_market_timestamps")
    return {
        "status": "PASS" if not blockers else "BLOCKED",
        "start": pd.Timestamp(start).isoformat(),
        "end": pd.Timestamp(end).isoformat(),
        "expected_minutes": expected_minutes,
        "coverage": coverage,
        "spot_gaps": spot_stats,
        "futures_gaps": futures_stats,
        "mark_gaps": mark_stats,
        "funding_rows": len(funding),
        "funding_expected": expected_funding,
        "funding_coverage": funding_coverage,
        "funding_first": funding_times[0].isoformat() if len(funding_times) else None,
        "funding_last": funding_times[-1].isoformat() if len(funding_times) else None,
        "limitations": [
            "Maintenance margin uses a fixed low-notional tier rate.",
            "Intrabar liquidation uses mark OHLC, not order-book depth.",
            "Historical fee changes and mark/index spread microstructure are approximated.",
        ],
        "blockers": blockers,
    }
