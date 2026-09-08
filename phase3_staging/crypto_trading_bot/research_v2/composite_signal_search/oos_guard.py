"""Hard OOS lock — fail closed; never load partition OOS."""
from __future__ import annotations

from typing import Any, Iterable

import pandas as pd

from .config import OOS_OPENED

_OOS_LABELS = frozenset({"OOS", "oos", "OUT_OF_SAMPLE", "out_of_sample"})


class OOSLockedError(RuntimeError):
    """Raised when any code path attempts OOS partition access."""


def assert_oos_locked(*, context: str = "") -> None:
    """Refuse any attempt to open or evaluate the OOS partition."""
    suffix = f" ({context})" if context else ""
    raise OOSLockedError(
        f"OOS partition access refused{suffix}: OOS_OPENED={OOS_OPENED}; "
        "fail-closed — DEVELOPMENT corpus only."
    )


def refuse_oos_partition(name: str | None, *, context: str = "") -> None:
    if name is None:
        return
    if str(name).strip().upper() in {"OOS"} or str(name) in _OOS_LABELS:
        assert_oos_locked(context=context or f"partition={name}")


def assert_events_exclude_oos(events: pd.DataFrame, *, context: str = "") -> None:
    if events is None or events.empty or "partition" not in events.columns:
        return
    labels = {str(x) for x in events["partition"].dropna().unique()}
    if labels & {"OOS", "oos"}:
        assert_oos_locked(context=context or "events contain OOS rows")


def assert_no_oos_bounds(start: Any, end: Any, *, context: str = "") -> None:
    """Reject explicit OOS calendar window requests."""
    from crypto_trading_bot.research_v2.reversal_signal_study.config import PARTITION_BOUNDS
    from crypto_trading_bot.research_v2.indicator_engine.bars import parse_ts

    oos_start, oos_end = PARTITION_BOUNDS["OOS"]
    try:
        s = parse_ts(start) if not hasattr(start, "timestamp") else start
        e = parse_ts(end) if not hasattr(end, "timestamp") else end
    except Exception:  # noqa: BLE001
        return
    # Any requested window that starts at/after OOS start is refused.
    if s >= oos_start:
        assert_oos_locked(context=context or f"window_start={s.isoformat()} overlaps OOS")
    if e > oos_end and s >= oos_start:
        assert_oos_locked(context=context or "window fully inside/after OOS")


def guard_partition_iterable(partitions: Iterable[str] | None, *, context: str = "") -> tuple[str, ...]:
    if partitions is None:
        return ()
    out: list[str] = []
    for p in partitions:
        refuse_oos_partition(p, context=context)
        out.append(str(p))
    return tuple(out)
