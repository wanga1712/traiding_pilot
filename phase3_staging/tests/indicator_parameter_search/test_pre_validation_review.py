"""Pre-Validation authority, hash, window, and final-bank field tests."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from crypto_trading_bot.research_v2.indicator_parameter_search.config import split_bounds
from crypto_trading_bot.research_v2.indicator_parameter_search.evaluation import (
    block_bootstrap_pvalue,
    classify_validation_stability,
    select_discovery_shortlist,
    validation_candidate_hash,
)
from crypto_trading_bot.research_v2.indicator_parameter_search.validation_authority import (
    EXPECTED_VALIDATION_CANDIDATE_COUNT,
    EXPECTED_VALIDATION_CANDIDATE_SET_HASH,
    build_final_selected_config,
    verify_frozen_candidate_pool,
    verify_validation_entry_authority,
)
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
ART = REPO_ROOT / "artifacts" / "MULTITF-INDICATOR-PARAMETER-SEARCH-1"


def test_discovery_freeze_authority_gate_pass():
    out = verify_validation_entry_authority(ART)
    assert out["VALIDATION_ENTRY_AUTHORITY_GATE"] == "PASS"
    assert out["FROZEN_VALIDATION_CANDIDATE_COUNT"] == 620
    assert out["VALIDATION_CANDIDATE_SET_HASH"] == EXPECTED_VALIDATION_CANDIDATE_SET_HASH


def test_validation_candidate_hash_exact():
    payload = json.loads((ART / "frozen_validation_candidates_v1.json").read_text(encoding="utf-8"))
    h = validation_candidate_hash(payload["candidate_ids"])
    assert len(payload["candidate_ids"]) == EXPECTED_VALIDATION_CANDIDATE_COUNT
    assert h == EXPECTED_VALIDATION_CANDIDATE_SET_HASH
    pool = verify_frozen_candidate_pool(ART)
    assert pool["DUPLICATE_CANDIDATE_ID_COUNT"] == 0
    assert pool["UNKNOWN_REGISTRY_CANDIDATE_COUNT"] == 0


def test_validation_entry_fail_closed_tampering(tmp_path: Path):
    # Copy required authority artifacts into temp root
    for name in (
        "discovery_freeze_authority_v2.json",
        "validation_protocol_v1.json",
        "frozen_validation_candidates_v1.json",
        "search_spec_v2.json",
        "candidate_registry_snapshot_v2.csv",
    ):
        shutil.copy(ART / name, tmp_path / name)

    assert verify_validation_entry_authority(tmp_path)["VALIDATION_ENTRY_AUTHORITY_GATE"] == "PASS"

    # candidate removed
    frozen = json.loads((tmp_path / "frozen_validation_candidates_v1.json").read_text(encoding="utf-8"))
    removed = dict(frozen)
    removed["candidate_ids"] = frozen["candidate_ids"][1:]
    (tmp_path / "frozen_validation_candidates_v1.json").write_text(json.dumps(removed), encoding="utf-8")
    with pytest.raises(RuntimeError):
        verify_validation_entry_authority(tmp_path)

    # restore and add
    (tmp_path / "frozen_validation_candidates_v1.json").write_text(json.dumps(frozen), encoding="utf-8")
    added = dict(frozen)
    added["candidate_ids"] = frozen["candidate_ids"] + ["TAMPERED_ID"]
    (tmp_path / "frozen_validation_candidates_v1.json").write_text(json.dumps(added), encoding="utf-8")
    with pytest.raises(RuntimeError):
        verify_validation_entry_authority(tmp_path)

    # restore and change one id
    (tmp_path / "frozen_validation_candidates_v1.json").write_text(json.dumps(frozen), encoding="utf-8")
    changed = dict(frozen)
    changed["candidate_ids"] = list(frozen["candidate_ids"])
    changed["candidate_ids"][0] = "TAMPERED_ID"
    (tmp_path / "frozen_validation_candidates_v1.json").write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(RuntimeError):
        verify_validation_entry_authority(tmp_path)

    # restore and corrupt authority hash
    (tmp_path / "frozen_validation_candidates_v1.json").write_text(json.dumps(frozen), encoding="utf-8")
    auth = json.loads((tmp_path / "discovery_freeze_authority_v2.json").read_text(encoding="utf-8"))
    auth["VALIDATION_CANDIDATE_SET_HASH"] = "0" * 64
    (tmp_path / "discovery_freeze_authority_v2.json").write_text(json.dumps(auth), encoding="utf-8")
    with pytest.raises(RuntimeError):
        verify_validation_entry_authority(tmp_path)

    # restore authority, corrupt search spec
    shutil.copy(ART / "discovery_freeze_authority_v2.json", tmp_path / "discovery_freeze_authority_v2.json")
    (tmp_path / "search_spec_v2.json").write_text((tmp_path / "search_spec_v2.json").read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        verify_validation_entry_authority(tmp_path)

    # restore search spec, corrupt registry
    shutil.copy(ART / "search_spec_v2.json", tmp_path / "search_spec_v2.json")
    reg = (tmp_path / "candidate_registry_snapshot_v2.csv").read_text(encoding="utf-8")
    (tmp_path / "candidate_registry_snapshot_v2.csv").write_text(reg + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        verify_validation_entry_authority(tmp_path)


def test_validation_window_boundary_constants():
    start, end = split_bounds("VALIDATION")
    assert start.isoformat() == "2022-06-10T04:36:00+00:00"
    assert end.isoformat() == "2023-06-20T06:08:00+00:00"
    protocol = json.loads((ART / "validation_protocol_v1.json").read_text(encoding="utf-8"))
    assert protocol["VALIDATION_START"] == start.isoformat()
    assert protocol["VALIDATION_END"] == end.isoformat()


def test_final_bank_discovery_validation_fields_distinct():
    row = build_final_selected_config(
        reg_row={"candidate_id": "X", "family": "DMA"},
        disc_row={"PRECISION_DELTA": 0.4, "TOTAL_SIGNALS": 10, "discovery_fold_stability": "STABLE_POSITIVE_FOLDS", "sample_flag": "NORMAL"},
        val_row={"PRECISION_DELTA": 0.1, "TOTAL_SIGNALS": 7, "validation_stability": "WEAK_POSITIVE", "sample_flag": "LOW_SAMPLE"},
    )
    assert row["discovery_precision_delta"] == 0.4
    assert row["validation_precision_delta"] == 0.1
    assert row["discovery_precision_delta"] != row["validation_precision_delta"]
    assert row["discovery_signals"] == 10
    assert row["validation_signals"] == 7
    assert row["discovery_fold_class"] == "STABLE_POSITIVE_FOLDS"
    assert row["validation_stability_class"] == "WEAK_POSITIVE"


def test_fdr_three_fold_forces_p1():
    p = block_bootstrap_pvalue(np.array([0.1, 0.2, 0.05]))
    assert p == 1.0


def test_classifier_thresholds_frozen():
    assert classify_validation_stability({"PRECISION_DELTA": 0.03}, {"PRECISION_DELTA": 0.02, "sample_flag": "NORMAL"}) == "STABLE_POSITIVE"
    assert classify_validation_stability({"PRECISION_DELTA": 0.03}, {"PRECISION_DELTA": 0.2, "sample_flag": "NORMAL"}) == "WEAK_POSITIVE"
    assert classify_validation_stability({"PRECISION_DELTA": 0.01}, {"PRECISION_DELTA": 0.02, "sample_flag": "NORMAL"}) == "WEAK_POSITIVE"
    assert classify_validation_stability({"PRECISION_DELTA": 0.03}, {"PRECISION_DELTA": -0.01, "sample_flag": "NORMAL"}) == "NEGATIVE"


def test_shortlist_semantics_top2_plus_refs():
    rows = []
    for i in range(5):
        rows.append(
            {
                "candidate_id": f"NR{i}",
                "partition": "DISCOVERY",
                "decision_tf": "1H",
                "direction": "UP",
                "family": "DMA",
                "is_reference": False,
                "sample_flag": "NORMAL",
                "PRECISION_DELTA": float(i),
            }
        )
    rows.append(
        {
            "candidate_id": "REF",
            "partition": "DISCOVERY",
            "decision_tf": "1H",
            "direction": "UP",
            "family": "DMA",
            "is_reference": True,
            "sample_flag": "NORMAL",
            "PRECISION_DELTA": -1.0,
        }
    )
    out = select_discovery_shortlist(pd.DataFrame(rows))
    ids = set(out["candidate_id"])
    assert "REF" in ids
    assert "NR4" in ids and "NR3" in ids
    assert "NR0" not in ids
    assert len(ids) == 3
