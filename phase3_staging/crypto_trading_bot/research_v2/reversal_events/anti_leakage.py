"""Causal history API — future bars must never be returned."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable


def _parse_ts(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    text = str(value).replace("Z", "+00:00")
    if text.endswith("+00"):
        text += ":00"
    return datetime.fromisoformat(text)


def filter_history_available_at(
    bars: Iterable[dict[str, Any]],
    decision_time: str | datetime,
    *,
    time_key: str = "close_time",
    require_closed: bool = True,
) -> list[dict[str, Any]]:
    """
    Return only bars causally available at decision_time.

    For closed-candle features (default):
      bar.close_time <= decision_time

    If require_closed is False, open_time <= decision_time is used instead
    (explicit partial-bar mode — must be opted into by future WIPs).
    """
    t = _parse_ts(decision_time)
    out = []
    for bar in bars:
        if require_closed:
            bt = _parse_ts(bar["close_time"])
        else:
            bt = _parse_ts(bar["open_time"])
        if bt <= t:
            out.append(bar)
    return out


def get_event_history(
    event_bars: Iterable[dict[str, Any]],
    *,
    event_id: str,
    timeframe: str,
    decision_time: str | datetime,
    require_closed: bool = True,
) -> list[dict[str, Any]]:
    """Reusable research API: history for one event/TF at decision_time."""
    scoped = [
        b
        for b in event_bars
        if b.get("event_id") == event_id and b.get("timeframe") == timeframe
    ]
    scoped.sort(key=lambda b: _parse_ts(b["open_time"]))
    return filter_history_available_at(
        scoped,
        decision_time,
        require_closed=require_closed,
    )


def assert_no_future_bars(
    history: list[dict[str, Any]],
    decision_time: str | datetime,
    *,
    require_closed: bool = True,
) -> None:
    t = _parse_ts(decision_time)
    for bar in history:
        if require_closed:
            if _parse_ts(bar["close_time"]) > t:
                raise AssertionError(
                    f"future bar leaked: close_time={bar['close_time']} > decision_time={t.isoformat()}"
                )
        else:
            if _parse_ts(bar["open_time"]) > t:
                raise AssertionError(
                    f"future bar leaked: open_time={bar['open_time']} > decision_time={t.isoformat()}"
                )


def higher_tf_unfinished_bar_excluded(
    higher_tf_bars: list[dict[str, Any]],
    decision_time: str | datetime,
) -> bool:
    """
    True if there exists a higher-TF bar that has opened but not closed at
    decision_time, and that bar is NOT returned by closed-candle filtering.
    """
    t = _parse_ts(decision_time)
    unfinished = [
        b
        for b in higher_tf_bars
        if _parse_ts(b["open_time"]) <= t < _parse_ts(b["close_time"])
    ]
    if not unfinished:
        return True  # vacuously ok
    hist = filter_history_available_at(higher_tf_bars, t, require_closed=True)
    hist_opens = {_parse_ts(b["open_time"]) for b in hist}
    for b in unfinished:
        if _parse_ts(b["open_time"]) in hist_opens:
            return False
    return True
