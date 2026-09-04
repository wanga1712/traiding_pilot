"""Pre-Validation authority gates — fail closed before any Validation data access."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .candidate_registry import load_frozen_registry
from .config import ARTIFACT_ROOT, split_bounds
from .evaluation import validation_candidate_hash
from .frozen_spec import (
    EXPECTED_CANDIDATE_REGISTRY_V2_SHA256,
    EXPECTED_SEARCH_SPEC_V2_SHA256,
    SEARCH_SPEC_V2_FREEZE_COMMIT,
)

EXPECTED_DISCOVERY_FREEZE_COMMIT = "58b47aa5a3df1f381c6a7e9900e24358b5a714d6"
EXPECTED_DISCOVERY_RUNTIME_COMMIT = "7eff0e741107a87cbcb436202dff095edbea625c"
EXPECTED_VALIDATION_CANDIDATE_COUNT = 620
EXPECTED_VALIDATION_CANDIDATE_SET_HASH = "99f50699587c0d2a189bef0346f8d74b5224c99fafda4fe16201773ce0c2d95c"

AUTHORITY_V2_NAME = "discovery_freeze_authority_v2.json"
PROTOCOL_NAME = "validation_protocol_v1.json"
FROZEN_CANDIDATES_NAME = "frozen_validation_candidates_v1.json"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_authority_v2(artifact_root: Path | None = None) -> dict[str, Any]:
    root = artifact_root or ARTIFACT_ROOT
    path = root / AUTHORITY_V2_NAME
    if not path.is_file():
        raise RuntimeError(f"VALIDATION_BEFORE_DISCOVERY_FREEZE_BLOCKED: missing {AUTHORITY_V2_NAME}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_frozen_candidate_ids(artifact_root: Path | None = None) -> list[str]:
    root = artifact_root or ARTIFACT_ROOT
    path = root / FROZEN_CANDIDATES_NAME
    if not path.is_file():
        raise FileNotFoundError(f"Missing frozen Validation candidate pool: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    ids = payload.get("candidate_ids")
    if not isinstance(ids, list) or not ids:
        raise RuntimeError("VALIDATION_CANDIDATE_POOL_INVALID: candidate_ids missing/empty")
    return [str(x) for x in ids]


def verify_frozen_candidate_pool(artifact_root: Path | None = None) -> dict[str, Any]:
    root = artifact_root or ARTIFACT_ROOT
    ids = load_frozen_candidate_ids(root)
    dedup = sorted(set(ids))
    if len(dedup) != len(ids):
        raise RuntimeError(f"DUPLICATE_CANDIDATE_ID_COUNT={len(ids) - len(dedup)}")
    h = validation_candidate_hash(ids)
    if len(ids) != EXPECTED_VALIDATION_CANDIDATE_COUNT:
        raise RuntimeError(
            f"FROZEN_VALIDATION_CANDIDATE_COUNT_MISMATCH expected={EXPECTED_VALIDATION_CANDIDATE_COUNT} actual={len(ids)}"
        )
    if h != EXPECTED_VALIDATION_CANDIDATE_SET_HASH:
        raise RuntimeError(
            f"VALIDATION_CANDIDATE_SET_HASH_MISMATCH expected={EXPECTED_VALIDATION_CANDIDATE_SET_HASH} actual={h}"
        )
    registry = load_frozen_registry(root / "candidate_registry_snapshot_v2.csv")
    reg_ids = {r["candidate_id"] for r in registry}
    unknown = sorted(set(ids) - reg_ids)
    if unknown:
        raise RuntimeError(f"UNKNOWN_REGISTRY_CANDIDATE_COUNT={len(unknown)} sample={unknown[:5]}")
    return {
        "FROZEN_VALIDATION_CANDIDATE_COUNT": len(ids),
        "VALIDATION_CANDIDATE_SET_HASH": h,
        "VALIDATION_CANDIDATE_SET_HASH_MATCH": "PASS",
        "DUPLICATE_CANDIDATE_ID_COUNT": 0,
        "UNKNOWN_REGISTRY_CANDIDATE_COUNT": 0,
        "candidate_ids": ids,
    }


def verify_validation_entry_authority(artifact_root: Path | None = None) -> dict[str, Any]:
    """Fail closed before any Validation market/event access."""
    root = artifact_root or ARTIFACT_ROOT
    authority = load_authority_v2(root)
    pool = verify_frozen_candidate_pool(root)

    spec_path = root / "search_spec_v2.json"
    reg_path = root / "candidate_registry_snapshot_v2.csv"
    actual_spec = _sha256_file(spec_path)
    actual_reg = _sha256_file(reg_path)
    # Use frozen expected on-disk hashes (Discovery authority), not git-blob LF variants.
    if actual_spec != EXPECTED_SEARCH_SPEC_V2_SHA256:
        raise RuntimeError(f"SEARCH_SPEC_SHA256_MISMATCH expected={EXPECTED_SEARCH_SPEC_V2_SHA256} actual={actual_spec}")
    if actual_reg != EXPECTED_CANDIDATE_REGISTRY_V2_SHA256:
        raise RuntimeError(f"CANDIDATE_REGISTRY_SHA256_MISMATCH expected={EXPECTED_CANDIDATE_REGISTRY_V2_SHA256} actual={actual_reg}")

    if authority.get("DISCOVERY_FREEZE_COMMIT") != EXPECTED_DISCOVERY_FREEZE_COMMIT:
        raise RuntimeError(
            "DISCOVERY_FREEZE_COMMIT_MISMATCH "
            f"expected={EXPECTED_DISCOVERY_FREEZE_COMMIT} actual={authority.get('DISCOVERY_FREEZE_COMMIT')}"
        )
    if authority.get("SEARCH_SPEC_V2_FREEZE_COMMIT") != SEARCH_SPEC_V2_FREEZE_COMMIT:
        raise RuntimeError("SEARCH_SPEC_V2_FREEZE_COMMIT_MISMATCH")
    if authority.get("DISCOVERY_RUNTIME_COMMIT") != EXPECTED_DISCOVERY_RUNTIME_COMMIT:
        raise RuntimeError("DISCOVERY_RUNTIME_COMMIT_MISMATCH")
    if int(authority.get("FROZEN_VALIDATION_CANDIDATE_COUNT", -1)) != EXPECTED_VALIDATION_CANDIDATE_COUNT:
        raise RuntimeError("AUTHORITY_CANDIDATE_COUNT_MISMATCH")
    if authority.get("VALIDATION_CANDIDATE_SET_HASH") != EXPECTED_VALIDATION_CANDIDATE_SET_HASH:
        raise RuntimeError("AUTHORITY_CANDIDATE_HASH_MISMATCH")
    if authority.get("OOS_ACCESS_COUNT", 0) != 0 or authority.get("OOS_OPENED", "NO") != "NO":
        raise RuntimeError("OOS_MUST_REMAIN_LOCKED")

    if authority.get("SEARCH_SPEC_SHA256") and authority["SEARCH_SPEC_SHA256"] != actual_spec:
        raise RuntimeError("AUTHORITY_SEARCH_SPEC_SHA_MISMATCH")
    if authority.get("CANDIDATE_REGISTRY_SHA256") and authority["CANDIDATE_REGISTRY_SHA256"] != actual_reg:
        raise RuntimeError("AUTHORITY_REGISTRY_SHA_MISMATCH")

    protocol_path = root / PROTOCOL_NAME
    if not protocol_path.is_file():
        raise RuntimeError(f"VALIDATION_PROTOCOL_MISSING: {PROTOCOL_NAME}")

    val_start, val_end = split_bounds("VALIDATION")
    return {
        **pool,
        "VALIDATION_ENTRY_AUTHORITY_GATE": "PASS",
        "DISCOVERY_FREEZE_COMMIT": authority["DISCOVERY_FREEZE_COMMIT"],
        "SEARCH_SPEC_V2_FREEZE_COMMIT": authority["SEARCH_SPEC_V2_FREEZE_COMMIT"],
        "DISCOVERY_RUNTIME_COMMIT": authority["DISCOVERY_RUNTIME_COMMIT"],
        "SEARCH_SPEC_SHA256": actual_spec,
        "CANDIDATE_REGISTRY_SHA256": actual_reg,
        "VALIDATION_START": val_start.isoformat(),
        "VALIDATION_END": val_end.isoformat(),
        "OOS_OPENED": "NO",
        "OOS_ACCESS_COUNT": 0,
        "authority": authority,
    }


def build_final_selected_config(
    *,
    reg_row: dict[str, Any],
    disc_row: dict[str, Any],
    val_row: dict[str, Any],
) -> dict[str, Any]:
    """Keep Discovery and Validation metrics in distinct fields."""
    return {
        **reg_row,
        "discovery_precision_delta": disc_row.get("PRECISION_DELTA"),
        "validation_precision_delta": val_row.get("PRECISION_DELTA"),
        "discovery_signals": int(disc_row.get("TOTAL_SIGNALS") or 0),
        "validation_signals": int(val_row.get("TOTAL_SIGNALS") or 0),
        "discovery_fold_class": disc_row.get("discovery_fold_stability"),
        "validation_stability_class": val_row.get("validation_stability"),
        "discovery_sample_flag": disc_row.get("sample_flag"),
        "validation_sample_flag": val_row.get("sample_flag"),
        "stability_class": val_row.get("validation_stability"),
    }
