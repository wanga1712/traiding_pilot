"""Deterministic composite event-stream hashing (compact int64 AVAILABLE_AT)."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Sequence

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.bars import parse_ts


def _as_utc_ns(value: Any) -> int:
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1_000_000_000)
    dt = parse_ts(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1_000_000_000)


def available_at_ns_from_signals(signals: Sequence[dict[str, Any]]) -> np.ndarray:
    if not signals:
        return np.zeros(0, dtype=np.int64)
    return np.fromiter(
        (_as_utc_ns(s["available_at"]) for s in signals),
        dtype=np.int64,
        count=len(signals),
    )


def composite_stream_sha256(
    *,
    direction: str,
    decision_tf: str,
    available_at_ns: np.ndarray | Sequence[int],
) -> str:
    """
    COMPOSITE_STREAM_SHA256 from direction + decision_tf + ordered int64 timestamps.
    Does not alter evaluation — pure function of the emitted stream.
    """
    ns = np.asarray(available_at_ns, dtype=np.int64)
    h = hashlib.sha256()
    h.update(str(direction).encode("utf-8"))
    h.update(b"\0")
    h.update(str(decision_tf).encode("utf-8"))
    h.update(b"\0")
    h.update(ns.tobytes(order="C"))
    return h.hexdigest()


def hash_composite_signals(
    signals: Sequence[dict[str, Any]],
    *,
    direction: str,
    decision_tf: str,
) -> tuple[str, np.ndarray]:
    ns = available_at_ns_from_signals(signals)
    digest = composite_stream_sha256(direction=direction, decision_tf=decision_tf, available_at_ns=ns)
    return digest, ns
