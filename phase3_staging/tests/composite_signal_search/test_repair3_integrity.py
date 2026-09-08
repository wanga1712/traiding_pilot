"""Repair-3 regression: streaming defs, crash-safe parts, isolation."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import pandas as pd
import pytest

from crypto_trading_bot.research_v2.composite_signal_search import bounded_compose as bc
from crypto_trading_bot.research_v2.composite_signal_search.result_parts import (
    AppendOnlyPartWriter,
    reconcile_orphan_parts,
)


def test_flush_does_not_read_previous_parts(tmp_path: Path):
    w = AppendOnlyPartWriter(tmp_path, dirname="parts", next_part=0)
    reads = {"n": 0}
    orig_read = pd.read_parquet

    def guarded_read(*args, **kwargs):
        reads["n"] += 1
        return orig_read(*args, **kwargs)

    pd.read_parquet = guarded_read  # type: ignore[assignment]
    try:
        for i in range(5):
            w.flush([{"i": i, "v": i * 10}])
            assert (tmp_path / "parts" / f"part-{i:06d}.parquet").exists()
        assert reads["n"] == 0
        assert w.next_part == 5
    finally:
        pd.read_parquet = orig_read  # type: ignore[assignment]


def test_orphan_reconcile_before_resume(tmp_path: Path):
    parts = tmp_path / "parts"
    w = AppendOnlyPartWriter(tmp_path, dirname="parts", next_part=0)
    w.flush([{"composite_id": "a", "v": 1}])  # committed index 0
    w.flush([{"composite_id": "b", "v": 2}])  # orphan if committed_next=1
    # Simulate crash after writing part-000001 but checkpoint still at next_part=1
    moved = reconcile_orphan_parts(parts, committed_next_part=1, quarantine_dir=tmp_path / "q")
    assert moved == ["part-000001.parquet"]
    assert (parts / "part-000000.parquet").exists()
    assert not (parts / "part-000001.parquet").exists()
    # Resume writer at committed next_part=1 must succeed exactly-once
    w2 = AppendOnlyPartWriter(tmp_path, dirname="parts", next_part=1)
    w2.flush([{"composite_id": "b", "v": 2}])
    rows = pd.read_parquet(parts / "part-000001.parquet")
    assert list(rows["composite_id"]) == ["b"]
    # No duplicate part-000000
    assert len(list(parts.glob("part-*.parquet"))) == 2


def test_full_path_streams_definitions_without_exhausting_first(monkeypatch, tmp_path: Path):
    """Prove full path begins evaluating before exhausting a one-pass generator."""
    state = {"eval_started": False, "exhausted_before_eval": False, "yielded": 0, "n": 8}

    class OnePass:
        def __init__(self, items: list[dict[str, Any]]):
            self._it = iter(items)
            self._done = False

        def __iter__(self) -> Iterator[dict[str, Any]]:
            return self

        def __next__(self) -> dict[str, Any]:
            try:
                item = next(self._it)
            except StopIteration:
                self._done = True
                raise
            state["yielded"] += 1
            if state["eval_started"] is False and self._done:
                state["exhausted_before_eval"] = True
            return item

        def __len__(self) -> int:  # noqa: D401
            raise TypeError("one-pass iterator has no len()")

    defs = []
    for i in range(state["n"]):
        defs.append(
            {
                "composite_id": f"COMP|T1|UP|{i:04d}",
                "template_id": "T1_DUAL_ANCHOR",
                "direction": "UP",
                "decision_tf": "1H",
                "trigger_candidate_id": "trig",
                "context_candidate_ids": ["ctx"],
                "components": [],
                "diagnostic": False,
            }
        )
    one_pass = OnePass(defs)

    def fake_iter(**kwargs):
        return one_pass

    monkeypatch.setattr(bc, "iter_all_template_definitions", fake_iter)
    monkeypatch.setattr(bc, "verify_shard_integrity", lambda *a, **k: {"SHARD_INTEGRITY_GATE": "SKIPPED"})
    monkeypatch.setattr(bc, "load_enumeration_authority", lambda root: {
        "COMPOSITE_ENUMERATION_SHA256": "deadbeef",
        "TOTAL_COMPOSITE_CANDIDATE_COUNT": state["n"],
        "GLOBAL_ENUMERATION_AUTHORITY": "PASS",
    })

    class FakeStore:
        def __init__(self, *a, **k):
            pass

        def __len__(self):
            return 582

        @property
        def active_count(self):
            return 0

        def get(self, cid):
            import numpy as np

            class S:
                available_at_ns = np.zeros(0, dtype=np.int64)
                signal_price = np.zeros(0, dtype=np.float64)

                def to_signal_dicts(self, **kwargs):
                    return []

            return S()

        def release(self, *a, **k):
            return None

    monkeypatch.setattr(bc, "AtomicStreamStore", FakeStore)
    monkeypatch.setattr(bc, "_load_events", lambda: pd.DataFrame({"partition": [], "partition_usable": []}))
    monkeypatch.setattr(
        bc,
        "run_data_location_preflight",
        lambda **k: {},
    )

    # Minimal frozen-ish files for authorities + banks
    (tmp_path / "composite_search_spec_v1.json").write_text("{}", encoding="utf-8")
    (tmp_path / "composite_templates_v1.json").write_text('{"templates":[]}', encoding="utf-8")
    (tmp_path / "composite_atomic_bank_v1.json").write_text(
        '{"configs":[{"candidate_id":"trig"},{"candidate_id":"ctx"}]}', encoding="utf-8"
    )
    (tmp_path / "development_corpus_manifest_v1.json").write_text("{}", encoding="utf-8")
    (tmp_path / "atomic_representative_bank_v1.json").write_text(
        '{"configs":[{"candidate_id":"trig","decision_tf":"1H","direction":"UP","family":"X"},'
        '{"candidate_id":"ctx","decision_tf":"1H","direction":"UP","family":"Y"}]}',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        bc,
        "load_atomic_bank",
        lambda root=None: {
            "configs": [
                {
                    "candidate_id": "trig",
                    "decision_tf": "1H",
                    "direction": "UP",
                    "family": "X",
                    "parameter_set_id": "p1",
                    "feature_id": "f1",
                },
                {
                    "candidate_id": "ctx",
                    "decision_tf": "1H",
                    "direction": "UP",
                    "family": "Y",
                    "parameter_set_id": "p2",
                    "feature_id": "f2",
                },
            ]
        },
    )
    monkeypatch.setattr(bc, "load_templates", lambda root=None: {"templates": []})
    monkeypatch.setattr(bc, "pair_key_from_config", lambda cfg: ("1H", "Y", "p2", "f2", "up", "dn"))
    monkeypatch.setattr(
        bc,
        "pair_configs_by_stream",
        lambda configs: {
            ("1H", "Y", "p2", "f2", "up", "dn"): {
                "UP": {"candidate_id": "ctx"},
                "DOWN": {"candidate_id": "ctx"},
            }
        },
    )

    class FakeBars:
        def __init__(self, *a, **k):
            pass

        def get(self, tf):
            return []

        def gap_ns(self, tf):
            import numpy as np

            return np.zeros(0, dtype=np.int64)

        def baselines(self, tf):
            return []

    monkeypatch.setattr(bc, "LazyBars", FakeBars)

    def fake_compose(**kwargs):
        state["eval_started"] = True
        # Must start before generator exhausted
        assert state["yielded"] < state["n"]
        assert one_pass._done is False
        return []

    monkeypatch.setattr(bc, "compose_signals_from_compact", fake_compose)
    monkeypatch.setattr(
        bc,
        "_evaluate_bundle",
        lambda *a, **k: {
            "TOTAL_SIGNALS": 0,
            "PRECISION": None,
            "EVENT_RECALL": None,
            "FALSE_POSITIVE_RATE": None,
            "MEDIAN_DELAY_SECONDS": None,
            "MEDIAN_MFE_AFTER_SIGNAL": None,
            "MEDIAN_MAE_AFTER_SIGNAL": None,
            "PRE_C_SIGNAL_RATE": None,
            "sample_flag": "INSUFFICIENT",
        },
    )
    monkeypatch.setattr(bc, "build_compact_state_arrays", lambda *a, **k: (__import__("numpy").zeros(0, dtype="int64"), __import__("numpy").zeros(0, dtype="int8")))

    out = bc.run_bounded_compose(
        artifact_root=tmp_path,
        max_candidates=3,
        resume=False,
        require_shards=False,
        runtime_subdir="_test_runtime",
    )
    assert out["FULL_COMPOSE_DEFINITION_STREAMING"] == "YES"
    assert out["ALL_COMPOSITE_DEFINITIONS_IN_RAM"] == "NO"
    assert out["COMPOSITE_DEFINITION_GENERATOR"] == "YES"
    assert state["eval_started"] is True
    assert state["exhausted_before_eval"] is False
    assert state["yielded"] >= 1
    # one-pass must not support len/list materialization helpers
    with pytest.raises(TypeError):
        len(one_pass)
    assert out["n_evaluated"] == 3
    # Isolated runtime — production checkpoint absent
    assert not (tmp_path / "composite_execution_checkpoint_v1.json").exists()
    assert (tmp_path / "_test_runtime" / "composite_execution_checkpoint_v1.json").exists()
    ck = __import__("json").loads(
        (tmp_path / "_test_runtime" / "composite_execution_checkpoint_v1.json").read_text(encoding="utf-8")
    )
    assert "completed_composite_ids" not in ck
    assert ck["CHECKPOINT_MEMORY_COMPLEXITY"] == "O(1)"
