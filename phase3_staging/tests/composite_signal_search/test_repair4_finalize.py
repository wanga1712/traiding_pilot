"""Unit tests for composite stream hash + finalization gate."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from crypto_trading_bot.research_v2.composite_signal_search.composite_stream_hash import (
    composite_stream_sha256,
    hash_composite_signals,
)
from crypto_trading_bot.research_v2.composite_signal_search.finalize import (
    FinalizationGateError,
    assert_finalization_allowed,
)
from crypto_trading_bot.research_v2.composite_signal_search.survivor_store import SurvivorStreamStore


def test_stream_hash_stable_and_order_sensitive():
    ns = np.asarray([10, 20, 30], dtype=np.int64)
    a = composite_stream_sha256(direction="UP", decision_tf="1H", available_at_ns=ns)
    b = composite_stream_sha256(direction="UP", decision_tf="1H", available_at_ns=ns)
    assert a == b
    c = composite_stream_sha256(direction="UP", decision_tf="1H", available_at_ns=ns[::-1])
    assert a != c


def test_hash_from_signal_dicts():
    sigs = [{"available_at": "2024-01-01T00:00:00+00:00"}, {"available_at": "2024-01-01T01:00:00+00:00"}]
    digest, ns = hash_composite_signals(sigs, direction="DOWN", decision_tf="15m")
    assert len(digest) == 64
    assert ns.dtype == np.int64
    assert ns.size == 2


def test_survivor_store_disk_backed(tmp_path: Path):
    store = SurvivorStreamStore(tmp_path)
    ns = np.arange(5, dtype=np.int64)
    store.persist(
        composite_id="COMP|T1|UP|abc",
        template_id="T1_DUAL_ANCHOR",
        decision_tf="1H",
        direction="UP",
        trigger_candidate_id="t",
        context_candidate_ids=["c"],
        available_at_ns=ns,
        stream_sha256="deadbeef",
        composite_class="INCREMENTAL_BALANCED",
    )
    store.flush_metadata()
    loaded = store.load_ns("COMP|T1|UP|abc")
    assert np.array_equal(loaded, ns)
    assert not (tmp_path / "composite_survivor_stream_manifest_v1.json").exists()
    parts = list((tmp_path / "composite_survivor_metadata_parts_v1").glob("part-*.jsonl"))
    assert parts
    doc = store.assemble_final_manifest()
    assert doc["SURVIVOR_FINAL_MANIFEST_ASSEMBLY"] == "PASS"
    assert (tmp_path / "composite_survivor_stream_manifest_v1.json").exists()
    assert doc["SURVIVOR_DUPLICATE_METADATA_COUNT"] == 0
    assert doc["SURVIVOR_MISSING_SHARD_COUNT"] == 0


def test_finalization_gate_fail_closed(tmp_path: Path):
    with pytest.raises(FinalizationGateError):
        assert_finalization_allowed(tmp_path, allow_partial_test=False)
    g = assert_finalization_allowed(tmp_path, allow_partial_test=True)
    assert g["FINALIZATION_ALLOWED"] == "YES"
    assert g["PARTIAL_FINALIZATION_FAIL_CLOSED"] == "YES"
