"""Causal context-state engine for paired UP/DOWN atomic streams."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Literal, Sequence

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.bars import parse_ts

Direction = Literal["UP", "DOWN"]
State = Literal["UP", "DOWN", "UNKNOWN"]
# Compact state codes for searchsorted timelines (hot path, no object dtype).
STATE_CODE = {"UNKNOWN": 0, "UP": 1, "DOWN": 2}
CODE_STATE = {0: "UNKNOWN", 1: "UP", 2: "DOWN"}

PAIR_KEY_FIELDS = (
    "family",
    "parameter_set_id",
    "decision_tf",
    "up_primitive",
    "down_primitive",
)


@dataclass(frozen=True, order=True)
class StateEvent:
    """Ordered state-change marker (AVAILABLE_AT causality)."""

    available_at: datetime
    state: State
    source: str = ""  # signal|conflict|gap_reset


def pair_key_from_config(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(row["family"]),
        str(row["parameter_set_id"]),
        str(row["decision_tf"]),
        str(row["up_primitive"]),
        str(row["down_primitive"]),
    )


def _as_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            from datetime import timezone

            return value.replace(tzinfo=timezone.utc)
        return value
    return parse_ts(value)


def normalize_available_at(value: Any) -> str:
    return _as_dt(value).isoformat()


def merge_directional_signals(
    up_signals: Sequence[dict[str, Any]],
    down_signals: Sequence[dict[str, Any]],
) -> list[tuple[datetime, Direction]]:
    """Merge UP/DOWN streams into a causal timeline of (available_at, direction)."""
    rows: list[tuple[datetime, Direction]] = []
    for sig in up_signals:
        rows.append((_as_dt(sig["available_at"]), "UP"))
    for sig in down_signals:
        rows.append((_as_dt(sig["available_at"]), "DOWN"))
    rows.sort(key=lambda x: (x[0], 0 if x[1] == "UP" else 1))
    return rows


def detect_gap_reset_times(
    bar_close_times: Sequence[Any],
    *,
    expected_bar_seconds: float,
    gap_factor: float = 1.5,
) -> list[datetime]:
    """
    Return timestamps at which state must reset to UNKNOWN due to missing bars.

    A gap is detected when consecutive close_time deltas exceed
    expected_bar_seconds * gap_factor. The reset applies at the first bar
    after the gap (so state known before the gap does not carry across).
    """
    if expected_bar_seconds <= 0 or len(bar_close_times) < 2:
        return []
    times = sorted(_as_dt(t) for t in bar_close_times)
    threshold = timedelta(seconds=float(expected_bar_seconds) * gap_factor)
    resets: list[datetime] = []
    for prev, cur in zip(times, times[1:]):
        if cur - prev > threshold:
            resets.append(cur)
    return resets


def build_state_timeline(
    up_signals: Sequence[dict[str, Any]],
    down_signals: Sequence[dict[str, Any]],
    *,
    gap_reset_times: Sequence[Any] | None = None,
) -> list[StateEvent]:
    """
    Build causal state change events.

    Rules:
    - STATE at T = direction of most recent available_at <= T (after applying resets)
    - same-timestamp UP+DOWN conflict → UNKNOWN
    - gap reset → UNKNOWN (until a later signal)
    """
    merged = merge_directional_signals(up_signals, down_signals)
    by_ts: dict[datetime, set[Direction]] = {}
    for ts, direction in merged:
        by_ts.setdefault(ts, set()).add(direction)

    events: list[StateEvent] = []
    for ts in sorted(by_ts):
        dirs = by_ts[ts]
        if len(dirs) > 1:
            events.append(StateEvent(available_at=ts, state="UNKNOWN", source="conflict"))
        else:
            only = next(iter(dirs))
            events.append(StateEvent(available_at=ts, state=only, source="signal"))

    for gap_ts in gap_reset_times or ():
        g = _as_dt(gap_ts)
        events.append(StateEvent(available_at=g, state="UNKNOWN", source="gap_reset"))

    events.sort()
    # Collapse duplicate timestamps: conflict/gap_reset wins over signal.
    collapsed: dict[datetime, StateEvent] = {}
    priority = {"conflict": 3, "gap_reset": 2, "signal": 1}
    for ev in events:
        prev = collapsed.get(ev.available_at)
        if prev is None or priority.get(ev.source, 0) >= priority.get(prev.source, 0):
            if prev is not None and prev.source != ev.source:
                # Prefer UNKNOWN if either event forces it.
                if ev.state == "UNKNOWN" or prev.state == "UNKNOWN":
                    collapsed[ev.available_at] = StateEvent(
                        available_at=ev.available_at,
                        state="UNKNOWN",
                        source=ev.source if ev.state == "UNKNOWN" else prev.source,
                    )
                    continue
            collapsed[ev.available_at] = ev
    return [collapsed[k] for k in sorted(collapsed)]


def state_at(
    timeline: Sequence[StateEvent],
    t: Any,
    *,
    default: State = "UNKNOWN",
) -> State:
    """STATE at T = direction/state of most recent timeline event with available_at <= T."""
    target = _as_dt(t)
    last: StateEvent | None = None
    for ev in timeline:
        if ev.available_at <= target:
            last = ev
        else:
            break
    if last is None:
        return default
    return last.state


def context_aligned(
    timeline: Sequence[StateEvent],
    trigger_available_at: Any,
    trigger_direction: Direction,
) -> bool:
    """True iff context state at trigger time equals the trigger direction."""
    return state_at(timeline, trigger_available_at) == trigger_direction


def pair_configs_by_stream(
    configs: Iterable[dict[str, Any]],
) -> dict[tuple[str, str, str, str, str], dict[str, dict[str, Any]]]:
    """
    Group configs into pair keys → {UP: row, DOWN: row}.

    Incomplete pairs (missing one side) are still returned; callers decide.
    """
    out: dict[tuple[str, str, str, str, str], dict[str, dict[str, Any]]] = {}
    for row in configs:
        key = pair_key_from_config(row)
        bucket = out.setdefault(key, {})
        bucket[str(row["direction"])] = row
    return out


def _to_ns(value: Any) -> int:
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1_000_000_000)
    dt = parse_ts(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1_000_000_000)


def build_compact_state_arrays(
    up_ns: np.ndarray | Sequence[int],
    down_ns: np.ndarray | Sequence[int],
    *,
    gap_reset_ns: Sequence[int] | np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Compact causal state timeline as parallel int64 ns + uint8 state codes.

    Semantics identical to build_state_timeline + state_at, without object dtype.
    CONTEXT_STATE_QUERY_MODE=TRIGGER_TIMESTAMP_SEARCHSORTED
    FULL_CONTEXT_BAR_MATRIX_CREATED=NO
    """
    up_arr = np.asarray(list(up_ns), dtype=np.int64)
    down_arr = np.asarray(list(down_ns), dtype=np.int64)
    by_ts: dict[int, set[str]] = {}
    for ts in up_arr.tolist():
        by_ts.setdefault(int(ts), set()).add("UP")
    for ts in down_arr.tolist():
        by_ts.setdefault(int(ts), set()).add("DOWN")

    events: list[tuple[int, int, int]] = []  # ns, state_code, priority
    # priority: conflict=3, gap=2, signal=1
    for ts, dirs in by_ts.items():
        if len(dirs) > 1:
            events.append((ts, STATE_CODE["UNKNOWN"], 3))
        else:
            only = next(iter(dirs))
            events.append((ts, STATE_CODE[only], 1))
    for gap_ts in list(gap_reset_ns) if gap_reset_ns is not None else []:
        events.append((int(gap_ts), STATE_CODE["UNKNOWN"], 2))

    events.sort(key=lambda x: (x[0], -x[2]))
    collapsed: dict[int, tuple[int, int]] = {}
    for ts, code, prio in events:
        prev = collapsed.get(ts)
        if prev is None:
            collapsed[ts] = (code, prio)
            continue
        prev_code, prev_prio = prev
        if prio >= prev_prio:
            if code == STATE_CODE["UNKNOWN"] or prev_code == STATE_CODE["UNKNOWN"]:
                collapsed[ts] = (STATE_CODE["UNKNOWN"], max(prio, prev_prio))
            else:
                collapsed[ts] = (code, prio)
    keys = sorted(collapsed)
    times = np.fromiter(keys, dtype=np.int64, count=len(keys))
    states = np.fromiter((collapsed[k][0] for k in keys), dtype=np.uint8, count=len(keys))
    return times, states


def state_at_ns(
    times_ns: np.ndarray,
    state_codes: np.ndarray,
    t_ns: int,
    *,
    default: State = "UNKNOWN",
) -> State:
    """STATE at T via searchsorted on compact timeline (available_at <= T)."""
    if times_ns.size == 0:
        return default
    idx = int(np.searchsorted(times_ns, int(t_ns), side="right") - 1)
    if idx < 0:
        return default
    return CODE_STATE[int(state_codes[idx])]  # type: ignore[return-value]


def context_aligned_ns(
    times_ns: np.ndarray,
    state_codes: np.ndarray,
    trigger_ns: int,
    trigger_direction: Direction,
) -> bool:
    return state_at_ns(times_ns, state_codes, trigger_ns) == trigger_direction


def last_directional_before_or_at(
    up_ns_sorted: np.ndarray,
    down_ns_sorted: np.ndarray,
    t_ns: int,
) -> tuple[int | None, int | None]:
    """
    Causal searchsorted helpers required by the bounded-memory WIP.

    Returns last UP and DOWN timestamps <= T (or None).
    Exact same-timestamp UP+DOWN conflict is handled in build_compact_state_arrays.
    """
    up = np.asarray(up_ns_sorted, dtype=np.int64)
    down = np.asarray(down_ns_sorted, dtype=np.int64)
    t = int(t_ns)
    last_up = None
    last_down = None
    if up.size:
        i = int(np.searchsorted(up, t, side="right") - 1)
        if i >= 0:
            last_up = int(up[i])
    if down.size:
        j = int(np.searchsorted(down, t, side="right") - 1)
        if j >= 0:
            last_down = int(down[j])
    return last_up, last_down
