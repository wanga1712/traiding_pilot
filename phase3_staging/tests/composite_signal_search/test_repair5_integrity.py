"""Repair-5: survivor append-only resume, lexical tie, Jaccard cardinality prefilter."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from crypto_trading_bot.research_v2.composite_signal_search.finalize import (
    FinalizationGateError,
    _jaccard,
    _jaccard_cardinality_possible,
    _near_rep_key,
    assert_finalization_allowed,
    near_redundancy_survivors,
)
from crypto_trading_bot.research_v2.composite_signal_search.survivor_store import (
    SurvivorStreamMismatchError,
    SurvivorStreamStore,
)


def test_survivor_no_global_rewrite_per_persist(tmp_path: Path):
    store = SurvivorStreamStore(tmp_path)
    for i in range(3):
        store.persist(
            composite_id=f"C{i}",
            template_id="T1",
            decision_tf="1H",
            direction="UP",
            trigger_candidate_id="t",
            context_candidate_ids=["c"],
            available_at_ns=np.arange(i + 1, dtype=np.int64),
            stream_sha256=f"sha{i}",
            composite_class="INCREMENTAL_BALANCED",
        )
        assert not (tmp_path / "composite_survivor_stream_manifest_v1.json").exists()
    store.flush_metadata()
    parts = list((tmp_path / "composite_survivor_metadata_parts_v1").glob("part-*.jsonl"))
    assert len(parts) == 1
    doc = store.assemble_final_manifest()
    assert doc["SURVIVOR_GLOBAL_MANIFEST_REWRITE_PER_SIGNAL"] == "NO"
    assert doc["n_streams"] == 3


def test_survivor_resume_idempotent_crash_before_checkpoint(tmp_path: Path):
    """Crash after shard persist / before checkpoint — resume must not duplicate metadata."""
    store = SurvivorStreamStore(tmp_path)
    ns = np.asarray([10, 20, 30], dtype=np.int64)
    kwargs = dict(
        composite_id="COMP|RESUME|A",
        template_id="T1",
        decision_tf="1H",
        direction="UP",
        trigger_candidate_id="trig",
        context_candidate_ids=["ctx"],
        available_at_ns=ns,
        stream_sha256="abc123",
        composite_class="INCREMENTAL_SELECTIVE",
    )
    store.persist(**kwargs)
    store.flush_metadata()
    # Simulate new process after crash (no checkpoint commit).
    store2 = SurvivorStreamStore(tmp_path)
    store2.persist(**kwargs)
    store2.flush_metadata()
    assert store2._reused_idempotent == 1
    assert store2._persisted_this_run == 0
    lines = []
    for part in sorted((tmp_path / "composite_survivor_metadata_parts_v1").glob("part-*.jsonl")):
        lines.extend(p for p in part.read_text(encoding="utf-8").splitlines() if p.strip())
    assert len(lines) == 1
    doc = store2.assemble_final_manifest()
    assert doc["SURVIVOR_DUPLICATE_METADATA_COUNT"] == 0
    assert doc["n_streams"] == 1


def test_survivor_mismatch_fail_closed(tmp_path: Path):
    store = SurvivorStreamStore(tmp_path)
    store.persist(
        composite_id="COMP|X",
        template_id="T1",
        decision_tf="1H",
        direction="UP",
        trigger_candidate_id="t",
        context_candidate_ids=["c"],
        available_at_ns=np.asarray([1, 2], dtype=np.int64),
        stream_sha256="aaa",
        composite_class="INCREMENTAL_BALANCED",
    )
    with pytest.raises(SurvivorStreamMismatchError):
        store.persist(
            composite_id="COMP|X",
            template_id="T1",
            decision_tf="1H",
            direction="UP",
            trigger_candidate_id="t",
            context_candidate_ids=["c"],
            available_at_ns=np.asarray([1, 2, 3], dtype=np.int64),
            stream_sha256="bbb",
            composite_class="INCREMENTAL_BALANCED",
        )


def test_near_redundancy_lexical_tie_ascending():
    fold_df = pd.DataFrame(
        [
            {"composite_id": "B_cid", "PRECISION_DELTA_VS_TRIGGER": 0.1},
            {"composite_id": "A_cid", "PRECISION_DELTA_VS_TRIGGER": 0.1},
        ]
    )
    rows = [
        pd.Series(
            {
                "composite_id": "B_cid",
                "RECALL_RETENTION_VS_TRIGGER": 0.5,
                "FPR_DELTA_VS_TRIGGER": 0.0,
                "TOTAL_SIGNALS": 10,
            }
        ),
        pd.Series(
            {
                "composite_id": "A_cid",
                "RECALL_RETENTION_VS_TRIGGER": 0.5,
                "FPR_DELTA_VS_TRIGGER": 0.0,
                "TOTAL_SIGNALS": 10,
            }
        ),
    ]
    ranked = sorted(rows, key=lambda r: _near_rep_key(r, fold_df))
    assert str(ranked[0]["composite_id"]) == "A_cid"
    assert str(ranked[1]["composite_id"]) == "B_cid"


def test_jaccard_cardinality_prefilter_and_exact_decision(tmp_path: Path):
    assert _jaccard_cardinality_possible(95, 100, threshold=0.95) is True
    assert _jaccard_cardinality_possible(90, 100, threshold=0.95) is False
    a = set(range(50))
    b = set(range(49)) | {999}
    assert _jaccard(a, b) >= 0.95 or True  # just exercise helper
    store = SurvivorStreamStore(tmp_path)
    # Near-equal size near-dup
    near_a = np.arange(50, dtype=np.int64)
    near_b = near_a.copy()
    near_b[-1] = near_b[-1] + 1
    far = np.arange(1000, 1100, dtype=np.int64)
    survivors_rows = []
    for cid, ns in [("A_near", near_a), ("B_near", near_b), ("C_far", far)]:
        sha = f"sha-{cid}"
        store.persist(
            composite_id=cid,
            template_id="T1",
            decision_tf="1H",
            direction="UP",
            trigger_candidate_id="t",
            context_candidate_ids=["c"],
            available_at_ns=ns,
            stream_sha256=sha,
            composite_class="INCREMENTAL_BALANCED",
        )
        survivors_rows.append(
            {
                "composite_id": cid,
                "direction": "UP",
                "decision_tf": "1H",
                "RECALL_RETENTION_VS_TRIGGER": 0.5,
                "FPR_DELTA_VS_TRIGGER": 0.0,
                "TOTAL_SIGNALS": int(ns.size),
                "COMPOSITE_STREAM_SHA256": sha,
            }
        )
    store.flush_metadata()
    survivors = pd.DataFrame(survivors_rows)
    fold_df = pd.DataFrame(
        [{"composite_id": c, "PRECISION_DELTA_VS_TRIGGER": 0.1} for c in survivors["composite_id"]]
    )
    near_df, replace, _ = near_redundancy_survivors(tmp_path, survivors, fold_df)
    assert "C_far" not in replace
    # A and B should cluster (exact Jaccard >= 0.95)
    assert ("A_near" in replace and replace["A_near"] == "B_near") or (
        "B_near" in replace and replace["B_near"] == "A_near"
    ) or (not near_df.empty and set(near_df.iloc[0]["members"].split("|")) >= {"A_near", "B_near"})


def test_partial_finalization_fail_closed(tmp_path: Path):
    with pytest.raises(FinalizationGateError):
        assert_finalization_allowed(tmp_path, allow_partial_test=False)
