"""Tests for append-only result writer and shard integrity gate."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from crypto_trading_bot.research_v2.composite_signal_search.result_parts import AppendOnlyPartWriter
from crypto_trading_bot.research_v2.composite_signal_search.stream_store import (
    ShardIntegrityError,
    verify_shard_integrity,
)


def test_flush_does_not_read_previous_parts(tmp_path: Path):
    w = AppendOnlyPartWriter(tmp_path, dirname="parts", next_part=0)
    # Monkeypatch: if flush ever called part_paths / read_parquet on prior, fail.
    reads = {"n": 0}
    orig_read = pd.read_parquet

    def guarded_read(*args, **kwargs):
        reads["n"] += 1
        return orig_read(*args, **kwargs)

    pd.read_parquet = guarded_read  # type: ignore[assignment]
    try:
        for i in range(5):
            w.flush([{"i": i, "v": i * 10}])
            # Prove prior parts exist but were not read
            assert (tmp_path / "parts" / f"part-{i:06d}.parquet").exists()
        assert reads["n"] == 0
        assert w.next_part == 5
        # Offline helper may read; flush path must not.
        assert len(w.part_paths()) == 5
    finally:
        pd.read_parquet = orig_read  # type: ignore[assignment]


def test_flush_refuses_overwrite(tmp_path: Path):
    w = AppendOnlyPartWriter(tmp_path, dirname="parts", next_part=0)
    w.flush([{"a": 1}])
    w2 = AppendOnlyPartWriter(tmp_path, dirname="parts", next_part=0)
    with pytest.raises(FileExistsError):
        w2.flush([{"a": 2}])


def test_shard_integrity_fail_closed(tmp_path: Path):
    with pytest.raises(ShardIntegrityError):
        verify_shard_integrity(tmp_path, expected_n=582)
