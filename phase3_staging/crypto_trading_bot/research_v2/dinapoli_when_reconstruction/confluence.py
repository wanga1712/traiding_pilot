"""Directional confluence — WHEN = available_at of final confirming component."""
from __future__ import annotations

import hashlib
from typing import Any

import numpy as np
import pandas as pd

from crypto_trading_bot.research_v2.indicator_engine.bars import parse_ts


def _sid(candidate_id: str, signal_time: str, direction: str) -> str:
    h = hashlib.sha1(f"{candidate_id}|{signal_time}|{direction}".encode()).hexdigest()[:20]
    return f"sig_{h}"


def build_confluence(
    *,
    dma: list[dict[str, Any]],
    stoch: list[dict[str, Any]],
    macd: list[dict[str, Any]],
    mode: str,
    window_bars: int,
    bar_close_times: list[str],
    candidate_id: str,
    decision_tf: str,
    expiration_bars: int,
) -> list[dict[str, Any]]:
    """
    Fast path: index family events by bar; scan decision bars once.
    """
    time_to_idx: dict[str, int] = {}
    for i, t in enumerate(bar_close_times):
        time_to_idx[t] = i
        time_to_idx[parse_ts(t).isoformat()] = i

    if mode == "DMA_ONLY":
        required, need_k = ("DMA",), 1
    elif mode == "DMA_STOCH":
        required, need_k = ("DMA", "STOCH"), 2
    elif mode == "DMA_MACD":
        required, need_k = ("DMA", "MACD"), 2
    elif mode == "STOCH_MACD":
        required, need_k = ("STOCH", "MACD"), 2
    elif mode == "DMA_STOCH_MACD":
        required, need_k = ("DMA", "STOCH", "MACD"), 3
    elif mode == "2OF3":
        required, need_k = ("DMA", "STOCH", "MACD"), 2
    else:
        raise ValueError(mode)

    # per family: list of (bar_idx, direction, price, available_at_iso)
    fam_events: dict[str, list[tuple[int, str, float, str]]] = {f: [] for f in ("DMA", "STOCH", "MACD")}
    for fam, sigs in (("DMA", dma), ("STOCH", stoch), ("MACD", macd)):
        for s in sigs:
            st = s["signal_time"]
            idx = time_to_idx.get(st)
            if idx is None:
                idx = time_to_idx.get(parse_ts(st).isoformat())
            if idx is None:
                continue
            aa = s.get("available_at", st)
            aa_iso = aa if isinstance(aa, str) else parse_ts(aa).isoformat()
            fam_events[fam].append((int(idx), s["signal_direction"], float(s["signal_price"]), aa_iso))

    # pointers for streaming latest-in-window
    ptr = {f: 0 for f in fam_events}
    # last confirmation bar per (family, direction) within window — rebuild via scan
    # Collect all candidate completion bars = union of event bars for required families
    all_idx = sorted({e[0] for f in required for e in fam_events[f]})
    if not all_idx:
        return []

    # Index events by bar for O(1) lookup
    by_bar: dict[int, list[tuple[str, str, float, str]]] = {}
    for fam in required:
        for idx, direction, price, aa in fam_events[fam]:
            by_bar.setdefault(idx, []).append((fam, direction, price, aa))

    out: list[dict[str, Any]] = []
    last_emit_idx: int | None = None
    last_dir: str | None = None

    # Maintain deques of recent confirmations per family+dir
    from collections import defaultdict, deque

    hist: dict[tuple[str, str], deque] = defaultdict(deque)  # (fam,dir) -> deque of (idx, price, aa)

    min_i, max_i = all_idx[0], all_idx[-1]
    for i in range(min_i, max_i + 1):
        # expire old
        start = i - int(window_bars)
        for key, dq in hist.items():
            while dq and dq[0][0] < start:
                dq.popleft()
        # add events at i
        for fam, direction, price, aa in by_bar.get(i, []):
            hist[(fam, direction)].append((i, price, aa))

        for direction in ("UP", "DOWN"):
            present = []
            last_aa = None
            last_price = None
            last_bar = -1
            for fam in required:
                dq = hist.get((fam, direction))
                if dq:
                    present.append(fam)
                    if dq[-1][0] >= last_bar:
                        last_bar = dq[-1][0]
                        last_price = dq[-1][1]
                        last_aa = dq[-1][2]
            if mode == "2OF3":
                ok = len(present) >= need_k
            else:
                ok = len(present) == len(required)
            if not ok:
                continue
            # only emit when a new confirmation arrives at bar i
            arrived = any(e[1] == direction for e in by_bar.get(i, []))
            if not arrived:
                continue
            if last_emit_idx is not None and last_dir == direction and (i - last_emit_idx) < expiration_bars:
                continue
            when_iso = last_aa
            out.append(
                {
                    "signal_id": _sid(candidate_id, when_iso, direction),
                    "candidate_id": candidate_id,
                    "signal_time": when_iso,
                    "signal_price": float(last_price),
                    "signal_direction": direction,
                    "decision_tf": decision_tf,
                    "calculated_at": when_iso,
                    "available_at": when_iso,
                    "family": f"CONF_{mode}",
                    "confirming_families": "|".join(sorted(present)),
                }
            )
            last_emit_idx = i
            last_dir = direction
    return out
