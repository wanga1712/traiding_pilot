"""Bar loading / normalization for the WHEN study."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from crypto_trading_bot.research_v2.indicator_engine.bars import parse_ts
from crypto_trading_bot.research_v2.market_data import TimeframeBarService

from .config import CANONICAL_1M, MARKET_CACHE, SSH_HOST, SSH_KEY


def make_bar_service() -> TimeframeBarService:
    return TimeframeBarService(
        symbol="ETHUSDT",
        canonical_root=Path(CANONICAL_1M),
        cache_root=Path(MARKET_CACHE),
        ssh_host=SSH_HOST,
        ssh_key=Path(SSH_KEY),
    )


def normalize_bar(row: dict[str, Any]) -> dict[str, Any]:
    """Map market-data or event-bar rows to indicator-engine keys."""
    open_time = row.get("open_time") or row.get("open_time_utc")
    close_time = row.get("close_time") or row.get("close_time_utc")
    return {
        "open_time": open_time if isinstance(open_time, str) else parse_ts(open_time).isoformat(),
        "close_time": close_time if isinstance(close_time, str) else parse_ts(close_time).isoformat(),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": float(row.get("volume", 0.0)),
    }


def load_continuous_bars(
    service: TimeframeBarService,
    timeframe: str,
    start: datetime,
    end: datetime,
    *,
    warmup_bars: int = 400,
) -> list[dict[str, Any]]:
    """Load closed bars covering [start, end) with warmup lookback."""
    from datetime import timedelta

    from crypto_trading_bot.research_v2.resampling import TIMEFRAMES

    minutes = TIMEFRAMES[timeframe]
    warmup = timedelta(minutes=minutes * warmup_bars)
    after = start - warmup
    # generous limit
    span_bars = int((end - after).total_seconds() / (minutes * 60)) + warmup_bars + 50
    raw = service.get_bars(timeframe, after=after, before=end, limit=max(span_bars, 1000))
    bars = [normalize_bar(r) for r in raw]
    # keep only complete causal bars with close_time < end
    out = []
    for b in bars:
        ct = parse_ts(b["close_time"])
        if ct.tzinfo is None:
            ct = ct.replace(tzinfo=timezone.utc)
        if ct < end:
            out.append(b)
    return out


def filter_bars_in_range(
    bars: list[dict[str, Any]],
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    out = []
    for b in bars:
        ct = parse_ts(b["close_time"])
        if ct.tzinfo is None:
            ct = ct.replace(tzinfo=timezone.utc)
        if start <= ct < end:
            out.append(b)
    return out
