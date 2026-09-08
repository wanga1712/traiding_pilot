"""Unit tests for causal context-state engine."""
from __future__ import annotations

from datetime import datetime, timezone

from crypto_trading_bot.research_v2.composite_signal_search.context_state import (
    build_state_timeline,
    detect_gap_reset_times,
    pair_key_from_config,
    state_at,
)


def _sig(ts: str, direction: str) -> dict:
    return {"available_at": ts, "signal_direction": direction}


def test_state_follows_most_recent_available_at():
    up = [_sig("2020-01-01T00:00:00+00:00", "UP"), _sig("2020-01-01T04:00:00+00:00", "UP")]
    down = [_sig("2020-01-01T02:00:00+00:00", "DOWN")]
    tl = build_state_timeline(up, down)
    assert state_at(tl, "2020-01-01T01:00:00+00:00") == "UP"
    assert state_at(tl, "2020-01-01T03:00:00+00:00") == "DOWN"
    assert state_at(tl, "2020-01-01T05:00:00+00:00") == "UP"
    assert state_at(tl, "2019-12-31T00:00:00+00:00") == "UNKNOWN"


def test_same_timestamp_conflict_unknown():
    up = [_sig("2020-01-01T00:00:00+00:00", "UP")]
    down = [_sig("2020-01-01T00:00:00+00:00", "DOWN")]
    tl = build_state_timeline(up, down)
    assert state_at(tl, "2020-01-01T00:00:00+00:00") == "UNKNOWN"
    assert state_at(tl, "2020-01-01T01:00:00+00:00") == "UNKNOWN"


def test_gap_reset_clears_state():
    up = [_sig("2020-01-01T00:00:00+00:00", "UP")]
    down: list[dict] = []
    closes = [
        "2020-01-01T00:00:00+00:00",
        "2020-01-01T01:00:00+00:00",
        # gap
        "2020-01-01T05:00:00+00:00",
        "2020-01-01T06:00:00+00:00",
    ]
    resets = detect_gap_reset_times(closes, expected_bar_seconds=3600, gap_factor=1.5)
    assert resets == [datetime(2020, 1, 1, 5, tzinfo=timezone.utc)]
    tl = build_state_timeline(up, down, gap_reset_times=resets)
    assert state_at(tl, "2020-01-01T01:00:00+00:00") == "UP"
    assert state_at(tl, "2020-01-01T05:00:00+00:00") == "UNKNOWN"
    assert state_at(tl, "2020-01-01T06:00:00+00:00") == "UNKNOWN"


def test_pair_key_fields():
    row = {
        "family": "DMA",
        "parameter_set_id": "P1",
        "decision_tf": "1H",
        "up_primitive": "A",
        "down_primitive": "B",
        "direction": "UP",
    }
    assert pair_key_from_config(row) == ("DMA", "P1", "1H", "A", "B")
