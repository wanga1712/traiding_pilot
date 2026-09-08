"""OOS hard-lock tests — fail closed."""
from __future__ import annotations

import pandas as pd
import pytest

from crypto_trading_bot.research_v2.composite_signal_search.oos_guard import (
    OOSLockedError,
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
