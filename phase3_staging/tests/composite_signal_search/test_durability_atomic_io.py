"""Unit tests for durable atomic part/checkpoint writers."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from crypto_trading_bot.research_v2.composite_signal_search.durable_io import save_json_durable
from crypto_trading_bot.research_v2.composite_signal_search.result_parts import (
    AppendOnlyPartWriter,
    reconcile_orphan_parts,
)
from crypto_trading_bot.research_v2.composite_signal_search.survivor_store import (
    SurvivorStreamStore,
    reconcile_orphan_survivor_meta_parts,
)


def test_result_part_atomic_commit_no_tmp_left(tmp_path: Path):
    w = AppendOnlyPartWriter(tmp_path, dirname="parts", next_part=0)
    path = w.flush([{"composite_id": "a", "v": 1}])
    assert path is not None
    assert path.exists()
    assert not path.with_name(path.name + ".tmp").exists()
    assert list(path.parent.glob("*.tmp")) == []


def test_orphan_result_parts_quarantined(tmp_path: Path):
    parts = tmp_path / "parts"
    parts.mkdir()
    (parts / "part-000000.parquet").write_bytes(b"ok")
    (parts / "part-000001.parquet").write_bytes(b"orphan")
    (parts / "part-000002.parquet.tmp").write_bytes(b"half")
    q = tmp_path / "q"
    moved = reconcile_orphan_parts(parts, committed_next_part=1, quarantine_dir=q)
    assert "part-000001.parquet" in moved
    assert "part-000002.parquet.tmp" in moved
    assert (parts / "part-000000.parquet").exists()
    assert not (parts / "part-000001.parquet").exists()


def test_checkpoint_atomic_replace(tmp_path: Path):
    ckpt = tmp_path / "ckpt.json"
    save_json_durable(ckpt, {"next_candidate_index": 10, "completed_count": 10})
    assert ckpt.exists()
    assert not (tmp_path / "ckpt.json.tmp").exists()
    doc = json.loads(ckpt.read_text(encoding="utf-8"))
    assert doc["next_candidate_index"] == 10


def test_survivor_meta_atomic_and_orphan(tmp_path: Path):
    store = SurvivorStreamStore(tmp_path, next_meta_part=0)
    store._batch = [{"composite_id": "x", "n_signals": 1}]
    part = store.flush_metadata()
    assert part is not None
    assert part.exists()
    assert not part.with_suffix(part.suffix + ".tmp").exists()
    # Fabricate orphan beyond committed index 0... wait, after flush next is 1, committed should be 1
    orphan = tmp_path / "composite_survivor_metadata_parts_v1" / "part-000001.jsonl"
    orphan.write_text("{}\n", encoding="utf-8")
    moved = reconcile_orphan_survivor_meta_parts(
        tmp_path / "composite_survivor_metadata_parts_v1",
        committed_next_part=1,
        quarantine_dir=tmp_path / "q",
    )
    assert "part-000001.jsonl" in moved
    assert (tmp_path / "composite_survivor_metadata_parts_v1" / "part-000000.jsonl").exists()
