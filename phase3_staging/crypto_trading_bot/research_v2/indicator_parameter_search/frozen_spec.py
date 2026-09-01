"""Frozen search-spec and registry immutability checks (FIX 7)."""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

SEARCH_SPEC_FREEZE_COMMIT = "3540b2f57c121fe8e2f7001430f4907b5b07d922"
EXPECTED_SEARCH_SPEC_SHA256 = "a50e6357b1b64c502ada9a76af23a636e3df7c16746054ff5ca77a6718420c3b"
EXPECTED_CANDIDATE_REGISTRY_SHA256 = "93a89cb4dfd50d3dc85d615c7678431ffaf980e32b0f6ef77057c6f80fbfa159"

SEARCH_SPEC_REL = "artifacts/MULTITF-INDICATOR-PARAMETER-SEARCH-1/search_spec_v1.json"
REGISTRY_REL = "artifacts/MULTITF-INDICATOR-PARAMETER-SEARCH-1/candidate_registry_snapshot_v1.csv"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _git_blob_sha256(commit: str, rel_path: str) -> str:
    try:
        raw = subprocess.check_output(["git", "show", f"{commit}:{rel_path}"], stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError as exc:
        raise FileNotFoundError(f"Missing frozen artifact at {commit}:{rel_path}") from exc
    return _sha256_bytes(raw)


def verify_frozen_artifacts(artifact_root: Path) -> dict[str, str]:
    """Fail closed if on-disk spec/registry diverge from SEARCH_SPEC_FREEZE_COMMIT."""
    spec_path = artifact_root / "search_spec_v1.json"
    registry_path = artifact_root / "candidate_registry_snapshot_v1.csv"
    if not spec_path.is_file():
        raise FileNotFoundError(f"Missing frozen search spec: {spec_path}")
    if not registry_path.is_file():
        raise FileNotFoundError(f"Missing frozen candidate registry: {registry_path}")

    try:
        expected_spec = _git_blob_sha256(SEARCH_SPEC_FREEZE_COMMIT, SEARCH_SPEC_REL)
        expected_registry = _git_blob_sha256(SEARCH_SPEC_FREEZE_COMMIT, REGISTRY_REL)
    except (FileNotFoundError, subprocess.CalledProcessError):
        expected_spec = EXPECTED_SEARCH_SPEC_SHA256
        expected_registry = EXPECTED_CANDIDATE_REGISTRY_SHA256
    actual_spec = _sha256_file(spec_path)
    actual_registry = _sha256_file(registry_path)
    if actual_spec != expected_spec:
        raise ValueError(
            f"SEARCH_SPEC_IMMUTABLE=FAIL expected_sha256={expected_spec} actual_sha256={actual_spec}"
        )
    if actual_registry != expected_registry:
        raise ValueError(
            f"CANDIDATE_REGISTRY_IMMUTABLE=FAIL expected_sha256={expected_registry} actual_sha256={actual_registry}"
        )
    return {
        "SEARCH_SPEC_SHA256": actual_spec,
        "CANDIDATE_REGISTRY_SHA256": actual_registry,
        "SEARCH_SPEC_FREEZE_COMMIT": SEARCH_SPEC_FREEZE_COMMIT,
    }
