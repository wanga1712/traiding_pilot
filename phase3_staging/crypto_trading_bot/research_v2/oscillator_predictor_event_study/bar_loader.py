"""Bar loading for historical event study — S7 canonical only via S13 disposable cache."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from crypto_trading_bot.research_v2.indicator_engine.bars import parse_ts
from crypto_trading_bot.research_v2.market_data.research_access import (
    CANONICAL_HOST,
    CANONICAL_SOURCE_PATH,
    COMPUTE_HOST,
    S13_RESEARCH_CACHE_PATH,
    make_research_bar_service,
)
from crypto_trading_bot.research_v2.reversal_signal_study.bar_io import filter_bars_in_range, normalize_bar
from crypto_trading_bot.research_v2.resampling import TIMEFRAMES

from .config import WARMUP_BARS


class CanonicalDataUnavailableError(RuntimeError):
    """Raised when required S7 canonical partitions are missing — do not download on S13."""


def load_continuous_bars(
    timeframe: str,
    start: datetime,
    end: datetime,
    *,
    warmup_bars: int = WARMUP_BARS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load bars from S7 canonical store into S13 disposable resample cache."""
    minutes = TIMEFRAMES[timeframe]
    warmup = timedelta(minutes=minutes * warmup_bars)
    load_start = start - warmup
    meta: dict[str, Any] = {
        "timeframe": timeframe,
        "source_host": CANONICAL_HOST,
        "source_path": CANONICAL_SOURCE_PATH,
        "compute_host": COMPUTE_HOST,
        "s13_cache_path": str(S13_RESEARCH_CACHE_PATH),
        "cache_disposable": True,
    }

    service = make_research_bar_service()
    span_bars = int((end - load_start).total_seconds() / (minutes * 60)) + warmup_bars + 50
    raw = service.get_bars(timeframe, after=load_start, before=end, limit=max(span_bars, 5000))
    if not raw:
        raise CanonicalDataUnavailableError(
            f"No bars returned from S7 for {timeframe} [{load_start.isoformat()}, {end.isoformat()})"
        )
    bars = [normalize_bar(r) for r in raw]
    for b in bars:
        b["timeframe"] = timeframe
    out = []
    for b in bars:
        ct = parse_ts(b["close_time"])
        if ct.tzinfo is None:
            ct = ct.replace(tzinfo=timezone.utc)
        if ct < end:
            out.append(b)
    if not out:
        raise CanonicalDataUnavailableError(f"No complete bars in range for {timeframe}")
    meta["source"] = "S7_canonical_via_S13_disposable_cache"
    meta["first_loaded"] = out[0]["close_time"]
    meta["last_loaded"] = out[-1]["close_time"]
    meta["row_count"] = len(out)
    return out, meta


def effective_scan_range(
    bars: list[dict[str, Any]],
    split_start: datetime,
    split_end: datetime,
) -> tuple[datetime | None, datetime | None, list[dict[str, Any]]]:
    scan = filter_bars_in_range(bars, split_start, split_end)
    if not scan:
        return None, None, scan
    first = parse_ts(scan[0]["close_time"])
    last = parse_ts(scan[-1]["close_time"])
    if first.tzinfo is None:
        first = first.replace(tzinfo=timezone.utc)
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return first, last, scan
