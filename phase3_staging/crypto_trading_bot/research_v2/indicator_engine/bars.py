"""Bar extraction and gap detection for causal indicators."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Sequence

import numpy as np


def parse_ts(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    text = str(value).replace("Z", "+00:00")
    if text.endswith("+00"):
        text += ":00"
    return datetime.fromisoformat(text)


TF_MINUTES = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1H": 60,
    "2H": 120,
    "4H": 240,
    "6H": 360,
    "8H": 480,
    "12H": 720,
    "1D": 1440,
}


@dataclass(frozen=True)
class BarArrays:
    open_time: list[datetime]
    close_time: list[datetime]
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    gap_flags: np.ndarray  # True if gap AFTER previous bar (index i means gap before bar i)


def bars_to_arrays(bars: Sequence[dict[str, Any]], *, timeframe: str | None = None) -> BarArrays:
    if not bars:
        empty = np.array([], dtype=float)
        return BarArrays([], [], empty, empty, empty, empty, empty, np.array([], dtype=bool))

    open_time = [parse_ts(b["open_time"]) for b in bars]
    close_time = [parse_ts(b["close_time"]) for b in bars]
    o = np.array([float(b["open"]) for b in bars], dtype=float)
    h = np.array([float(b["high"]) for b in bars], dtype=float)
    l = np.array([float(b["low"]) for b in bars], dtype=float)
    c = np.array([float(b["close"]) for b in bars], dtype=float)
    v = np.array([float(b.get("volume", 0.0)) for b in bars], dtype=float)

    gap = np.zeros(len(bars), dtype=bool)
    expected = None
    if timeframe and timeframe in TF_MINUTES:
        expected = timedelta(minutes=TF_MINUTES[timeframe])
    for i in range(1, len(bars)):
        delta = open_time[i] - open_time[i - 1]
        if expected is not None:
            # tolerate 1s float; flag if open spacing differs from TF by > half bar
            if abs(delta.total_seconds() - expected.total_seconds()) > expected.total_seconds() * 0.51:
                gap[i] = True
        else:
            # without TF: gap if open_time of i != close_time of i-1 (loose)
            if open_time[i] > close_time[i - 1] + timedelta(seconds=1):
                gap[i] = True
    return BarArrays(open_time, close_time, o, h, l, c, v, gap)


def contiguous_ok(gap_flags: np.ndarray, start: int, end: int) -> bool:
    """True if bars [start, end] inclusive have no internal gaps (gap flags on start+1..end)."""
    if end < start:
        return False
    if start < 0 or end >= len(gap_flags):
        return False
    if end == start:
        return True
    return not bool(np.any(gap_flags[start + 1 : end + 1]))


def displayed_at_for(
    close_times: list[datetime],
    open_times: list[datetime],
    calc_index: int,
    display_shift: int,
) -> datetime | None:
    """DISPLAYED_AT = open of bar at calc_index + display_shift when present."""
    if display_shift <= 0:
        return close_times[calc_index]
    j = calc_index + display_shift
    if j >= len(open_times):
        return None
    return open_times[j]
