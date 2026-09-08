"""Composite timestamps must be a subset of trigger available_at times."""
from __future__ import annotations

import pytest

from crypto_trading_bot.research_v2.composite_signal_search.compose import (
    assert_timestamps_subset_of_trigger,
    compose_signals,
)
from crypto_trading_bot.research_v2.composite_signal_search.context_state import (
    StateEvent,
    build_state_timeline,
)


def test_composite_timestamp_equals_trigger_available_at():
    trigger = [
        {
            "available_at": "2020-01-01T02:00:00+00:00",
            "signal_time": "2020-01-01T02:00:00+00:00",
            "signal_price": 100.0,
            "signal_direction": "UP",
            "calculated_at": "2020-01-01T02:00:00+00:00",
        },
        {
            "available_at": "2020-01-01T04:00:00+00:00",
            "signal_time": "2020-01-01T04:00:00+00:00",
            "signal_price": 101.0,
            "signal_direction": "UP",
            "calculated_at": "2020-01-01T04:00:00+00:00",
        },
    ]
    # Context UP only from t=1 onward.
    tl = build_state_timeline(
        [{"available_at": "2020-01-01T01:00:00+00:00", "signal_direction": "UP"}],
        [{"available_at": "2020-01-01T03:00:00+00:00", "signal_direction": "DOWN"}],
    )
    sigs = compose_signals(
        composite_id="COMP|TEST|UP|x",
        trigger_signals=trigger,
        trigger_direction="UP",
        decision_tf="1H",
        context_timelines=[tl],
    )
    # First trigger at 02:00 — context UP → emit; second at 04:00 — context DOWN → skip.
    assert len(sigs) == 1
    assert sigs[0]["available_at"] == "2020-01-01T02:00:00+00:00"
    assert sigs[0]["signal_time"] == sigs[0]["available_at"]
    assert_timestamps_subset_of_trigger(sigs, trigger)


def test_assert_rejects_non_subset():
    trigger = [{"available_at": "2020-01-01T00:00:00+00:00"}]
    bad = [{"available_at": "2020-01-01T01:00:00+00:00", "signal_time": "2020-01-01T01:00:00+00:00"}]
    with pytest.raises(AssertionError):
        assert_timestamps_subset_of_trigger(bad, trigger)


def test_empty_context_unknown_blocks():
    trigger = [
        {
            "available_at": "2020-01-01T02:00:00+00:00",
            "signal_time": "2020-01-01T02:00:00+00:00",
            "signal_price": 1.0,
            "signal_direction": "UP",
            "calculated_at": "2020-01-01T02:00:00+00:00",
        }
    ]
    empty_tl: list[StateEvent] = []
    sigs = compose_signals(
        composite_id="COMP|TEST|UP|y",
        trigger_signals=trigger,
        trigger_direction="UP",
        decision_tf="1H",
        context_timelines=[empty_tl],
    )
    assert sigs == []
