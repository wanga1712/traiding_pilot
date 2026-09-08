"""Atomic replay checkpoint / resume tests."""
from __future__ import annotations

from pathlib import Path

from crypto_trading_bot.research_v2.composite_signal_search.atomic_replay import (
    load_atomic_checkpoint,
    save_atomic_checkpoint,
    stream_hash,
)


def test_checkpoint_roundtrip(tmp_path: Path):
    streams = {
        "A|5m|UP": {
            "candidate_id": "A|5m|UP",
            "decision_tf": "5m",
            "direction": "UP",
            "n_signals": 2,
            "available_at": ["2020-01-01T00:00:00+00:00", "2020-01-01T01:00:00+00:00"],
            "events": [],
            "stream_hash": stream_hash(
                tf="5m",
                direction="UP",
                available_at_isos=["2020-01-01T00:00:00+00:00", "2020-01-01T01:00:00+00:00"],
            ),
        }
    }
    save_atomic_checkpoint(
        streams,
        artifact_root=tmp_path,
        completed=1,
        total=10,
        last_candidate_id="A|5m|UP",
        start_iso="2019-05-12T00:00:00+00:00",
        end_iso="2023-06-20T06:08:00+00:00",
    )
    loaded = load_atomic_checkpoint(artifact_root=tmp_path)
    assert "A|5m|UP" in loaded
    assert loaded["A|5m|UP"]["n_signals"] == 2
    meta = (tmp_path / "atomic_replay_progress_v1.json").read_text(encoding="utf-8")
    assert "resumable" in meta
    assert '"completed": 1' in meta


def test_empty_checkpoint_missing(tmp_path: Path):
    assert load_atomic_checkpoint(artifact_root=tmp_path) == {}
