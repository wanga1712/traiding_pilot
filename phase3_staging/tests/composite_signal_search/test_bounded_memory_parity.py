"""Parity tests for bounded-memory context/query and definition generator."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from crypto_trading_bot.research_v2.composite_signal_search.compose import (
    _composite_id,
    expand_template_composites,
    iter_template_definitions,
)
from crypto_trading_bot.research_v2.composite_signal_search.context_state import (
    build_compact_state_arrays,
    build_state_timeline,
    detect_gap_reset_times,
    state_at,
    state_at_ns,
)


def _sig(ts: str, direction: str) -> dict:
    return {"available_at": ts, "signal_direction": direction}


def _ns(ts: str) -> int:
    return int(datetime.fromisoformat(ts).timestamp() * 1_000_000_000)


def test_compact_state_matches_object_timeline():
    up = [_sig("2020-01-01T00:00:00+00:00", "UP"), _sig("2020-01-01T04:00:00+00:00", "UP")]
    down = [_sig("2020-01-01T02:00:00+00:00", "DOWN")]
    closes = [
        "2020-01-01T00:00:00+00:00",
        "2020-01-01T01:00:00+00:00",
        "2020-01-01T05:00:00+00:00",
        "2020-01-01T06:00:00+00:00",
    ]
    resets = detect_gap_reset_times(closes, expected_bar_seconds=3600, gap_factor=1.5)
    tl = build_state_timeline(up, down, gap_reset_times=resets)
    up_ns = np.array([_ns(s["available_at"]) for s in up], dtype=np.int64)
    down_ns = np.array([_ns(s["available_at"]) for s in down], dtype=np.int64)
    gap_ns = np.array([int(r.timestamp() * 1_000_000_000) for r in resets], dtype=np.int64)
    times, codes = build_compact_state_arrays(up_ns, down_ns, gap_reset_ns=gap_ns)
    probes = [
        "2019-12-31T00:00:00+00:00",
        "2020-01-01T01:00:00+00:00",
        "2020-01-01T03:00:00+00:00",
        "2020-01-01T05:00:00+00:00",
        "2020-01-01T06:00:00+00:00",
    ]
    for p in probes:
        assert state_at(tl, p) == state_at_ns(times, codes, _ns(p))


def test_conflict_parity_compact():
    up = [_sig("2020-01-01T00:00:00+00:00", "UP")]
    down = [_sig("2020-01-01T00:00:00+00:00", "DOWN")]
    tl = build_state_timeline(up, down)
    times, codes = build_compact_state_arrays(
        [_ns("2020-01-01T00:00:00+00:00")],
        [_ns("2020-01-01T00:00:00+00:00")],
    )
    assert state_at(tl, "2020-01-01T00:00:00+00:00") == "UNKNOWN"
    assert state_at_ns(times, codes, _ns("2020-01-01T00:00:00+00:00")) == "UNKNOWN"


def test_definition_generator_ids_match_expand():
    reps = []
    for fam, tf, direction, i in [
        ("DMA", "2H", "UP", 1),
        ("DMA", "2H", "DOWN", 1),
        ("DMA", "1H", "UP", 1),
        ("DMA", "1H", "DOWN", 1),
        ("STOCH", "1H", "UP", 1),
        ("STOCH", "1H", "DOWN", 1),
    ]:
        reps.append(
            {
                "candidate_id": f"{fam}|P{i}|{tf}|{direction}",
                "family": fam,
                "parameter_set_id": f"P{i}",
                "decision_tf": tf,
                "direction": direction,
                "up_primitive": "U",
                "down_primitive": "D",
                "is_reference": False,
            }
        )
    # Add mates for pairing completeness in expand timelines
    streams = {r["candidate_id"]: {"events": [], "available_at": []} for r in reps}
    template = {
        "template_id": "T1_DUAL_ANCHOR",
        "context_tfs": ["2H"],
        "trigger_tfs": ["1H"],
        "n_context": 1,
        "diagnostic": False,
    }
    expanded = expand_template_composites(
        template, representatives=reps, streams_by_id=streams, all_configs_for_pairs=reps
    )
    generated = list(iter_template_definitions(template, representatives=reps, all_configs_for_pairs=reps))
    assert [c["composite_id"] for c in expanded] == [c["composite_id"] for c in generated]
    assert len(generated) > 0
    # Stable ID helper
    comps = generated[0]["components"]
    assert generated[0]["composite_id"] == _composite_id("T1_DUAL_ANCHOR", generated[0]["direction"], comps)
