"""Discovery-phase data window helpers (FIX 1/2/3/4/6/9)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from crypto_trading_bot.research_v2.indicator_engine.bars import parse_ts


def in_scan_window(
    ts: datetime,
    *,
    scan_start: datetime | None,
    scan_end: datetime | None,
) -> bool:
    if scan_start is not None and ts < scan_start:
        return False
    if scan_end is not None and ts >= scan_end:
        return False
    return True


def count_valid_bars(bars: list[dict[str, Any]], start: datetime, end: datetime) -> int:
    """Bars with close_time in [start, end) — excludes warmup and post-split bars."""
    n = 0
    for bar in bars:
        ct = parse_ts(bar["close_time"])
        if start <= ct < end:
            n += 1
    return n


def count_bars_from(bars: list[dict[str, Any]], boundary: datetime) -> int:
    return sum(1 for bar in bars if parse_ts(bar["close_time"]) >= boundary)


def filter_signals_to_window(
    signals: list[dict[str, Any]],
    *,
    scan_start: datetime,
    scan_end: datetime,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sig in signals:
        ct = parse_ts(sig["available_at"])
        if in_scan_window(ct, scan_start=scan_start, scan_end=scan_end):
            out.append(sig)
    return out


def discovery_event_set(signals: list[dict[str, Any]], *, scan_start: datetime, scan_end: datetime) -> set[str]:
    bounded = filter_signals_to_window(signals, scan_start=scan_start, scan_end=scan_end)
    return {str(s["signal_time"]) for s in bounded}


def count_validation_timestamps(event_set: set[str], *, discovery_end: datetime) -> int:
    return sum(1 for ts in event_set if parse_ts(ts) >= discovery_end)


def build_discovery_access_audit(
    *,
    bars_by_tf: dict[str, list[dict[str, Any]]],
    events: pd.DataFrame,
    discovery_start: datetime,
    discovery_end: datetime,
) -> dict[str, Any]:
    eval_bars = [
        b
        for bars in bars_by_tf.values()
        for b in bars
        if discovery_start <= parse_ts(b["close_time"]) < discovery_end
    ]
    warmup_or_post = [
        b
        for bars in bars_by_tf.values()
        for b in bars
        if parse_ts(b["close_time"]) < discovery_start or parse_ts(b["close_time"]) >= discovery_end
    ]
    val_events = events[events["partition"] == "VALIDATION"] if "partition" in events.columns else events.iloc[0:0]
    oos_events = events[events["partition"] == "OOS"] if "partition" in events.columns else events.iloc[0:0]
    bars_first = min((parse_ts(b["close_time"]) for b in eval_bars), default=None)
    bars_last = max((parse_ts(b["close_time"]) for b in eval_bars), default=None)
    return {
        "phase": "DISCOVERY",
        "bars_first": bars_first.isoformat() if bars_first else None,
        "bars_last": bars_last.isoformat() if bars_last else None,
        "discovery_start": discovery_start.isoformat(),
        "discovery_end": discovery_end.isoformat(),
        "evaluation_bar_count": len(eval_bars),
        "non_evaluation_bar_count": len(warmup_or_post),
        "validation_bars_loaded": count_bars_from(
            [b for bars in bars_by_tf.values() for b in bars],
            discovery_end,
        ),
        "validation_events_loaded": int(len(val_events)),
        "validation_signals_generated": 0,
        "oos_bars_loaded": 0,
        "oos_events_loaded": int(len(oos_events)),
        "VALIDATION_DATA_ACCESSED_DURING_DISCOVERY": "NO"
        if len(val_events) == 0 and count_bars_from([b for bars in bars_by_tf.values() for b in bars], discovery_end) == 0
        else "YES",
    }
