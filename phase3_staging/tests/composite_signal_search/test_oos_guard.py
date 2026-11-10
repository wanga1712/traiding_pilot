"""OOS hard-lock tests — fail closed."""
from __future__ import annotations

import pandas as pd
import pytest

from crypto_trading_bot.research_v2.composite_signal_search.oos_guard import (
    OOSLockedError,
    assert_no_oos_bounds,
    assert_events_exclude_oos,
    assert_oos_locked,
    guard_partition_iterable,
    refuse_oos_partition,
)


def test_assert_oos_locked_raises():
    with pytest.raises(OOSLockedError):
        assert_oos_locked(context="unit-test")


def test_refuse_oos_partition_name():
    with pytest.raises(OOSLockedError):
        refuse_oos_partition("OOS")
    refuse_oos_partition("DISCOVERY")  # must not raise


def test_guard_partition_iterable():
    assert guard_partition_iterable(("DISCOVERY", "VALIDATION")) == ("DISCOVERY", "VALIDATION")
    with pytest.raises(OOSLockedError):
        guard_partition_iterable(("DISCOVERY", "OOS"))


def test_events_with_oos_rows_raise():
    ev = pd.DataFrame({"partition": ["DISCOVERY", "OOS"]})
    with pytest.raises(OOSLockedError):
        assert_events_exclude_oos(ev)


def test_partial_overlap_with_oos_is_rejected():
    with pytest.raises(OOSLockedError):
        assert_no_oos_bounds("2023-01-01T00:00:00Z", "2023-07-01T00:00:00Z")


def test_window_ending_at_oos_start_is_allowed():
    assert_no_oos_bounds("2023-01-01T00:00:00Z", "2023-06-20T06:08:00Z")


def test_window_starting_at_oos_start_is_rejected():
    with pytest.raises(OOSLockedError):
        assert_no_oos_bounds("2023-06-20T06:08:00Z", "2023-06-21T00:00:00Z")
