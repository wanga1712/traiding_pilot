"""Frozen search-spec and registry immutability checks."""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

# V1 historical authority (preserved, superseded)
SEARCH_SPEC_V1_FREEZE_COMMIT = "3540b2f57c121fe8e2f7001430f4907b5b07d922"
EXPECTED_SEARCH_SPEC_V1_SHA256 = "a50e6357b1b64c502ada9a76af23a636e3df7c16746054ff5ca77a6718420c3b"
EXPECTED_CANDIDATE_REGISTRY_V1_SHA256 = "93a89cb4dfd50d3dc85d615c7678431ffaf980e32b0f6ef77057c6f80fbfa159"

SEARCH_SPEC_V1_REL = "artifacts/MULTITF-INDICATOR-PARAMETER-SEARCH-1/search_spec_v1.json"
REGISTRY_V1_REL = "artifacts/MULTITF-INDICATOR-PARAMETER-SEARCH-1/candidate_registry_snapshot_v1.csv"

# V2 active authority — populated at freeze time
SEARCH_SPEC_V2_FREEZE_COMMIT = ""
EXPECTED_SEARCH_SPEC_V2_SHA256 = "08ea6ee5d857317594691fa668ec8f41f4e32fd2f5df61defc0d3dbc7b601fac"
EXPECTED_CANDIDATE_REGISTRY_V2_SHA256 = "3940fe68ab87d54bf171ee119d40f4b2d23a81f0adcfb403bb361a5ffb620d15"

SEARCH_SPEC_V2_REL = "artifacts/MULTITF-INDICATOR-PARAMETER-SEARCH-1/search_spec_v2.json"
REGISTRY_V2_REL = "artifacts/MULTITF-INDICATOR-PARAMETER-SEARCH-1/candidate_registry_snapshot_v2.csv"

# Backward-compatible aliases for v1 tests
SEARCH_SPEC_FREEZE_COMMIT = SEARCH_SPEC_V1_FREEZE_COMMIT
EXPECTED_SEARCH_SPEC_SHA256 = EXPECTED_SEARCH_SPEC_V1_SHA256
EXPECTED_CANDIDATE_REGISTRY_SHA256 = EXPECTED_CANDIDATE_REGISTRY_V1_SHA256
SEARCH_SPEC_REL = SEARCH_SPEC_V1_REL
REGISTRY_REL = REGISTRY_V1_REL


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


def _verify_pair(
    artifact_root: Path,
    *,
    spec_name: str,
    registry_name: str,
    freeze_commit: str,
    expected_spec_sha: str,
    expected_registry_sha: str,
    spec_rel: str,
    registry_rel: str,
) -> dict[str, str]:
    spec_path = artifact_root / spec_name
    registry_path = artifact_root / registry_name
    if not spec_path.is_file():
        raise FileNotFoundError(f"Missing frozen search spec: {spec_path}")
    if not registry_path.is_file():
        raise FileNotFoundError(f"Missing frozen candidate registry: {registry_path}")

    try:
        exp_spec = _git_blob_sha256(freeze_commit, spec_rel) if freeze_commit else expected_spec_sha
        exp_registry = _git_blob_sha256(freeze_commit, registry_rel) if freeze_commit else expected_registry_sha
    except (FileNotFoundError, subprocess.CalledProcessError):
        exp_spec = expected_spec_sha
        exp_registry = expected_registry_sha

    actual_spec = _sha256_file(spec_path)
    actual_registry = _sha256_file(registry_path)
    if exp_spec and actual_spec != exp_spec:
        raise ValueError(
            f"SEARCH_SPEC_IMMUTABLE=FAIL expected_sha256={exp_spec} actual_sha256={actual_spec}"
        )
    if exp_registry and actual_registry != exp_registry:
        raise ValueError(
            f"CANDIDATE_REGISTRY_IMMUTABLE=FAIL expected_sha256={exp_registry} actual_sha256={actual_registry}"
        )
    return {
        "SEARCH_SPEC_SHA256": actual_spec,
        "CANDIDATE_REGISTRY_SHA256": actual_registry,
        "SEARCH_SPEC_FREEZE_COMMIT": freeze_commit,
    }


def verify_frozen_artifacts(artifact_root: Path) -> dict[str, str]:
    """Verify v1 artifacts remain unchanged (historical authority)."""
    return _verify_pair(
        artifact_root,
        spec_name="search_spec_v1.json",
        registry_name="candidate_registry_snapshot_v1.csv",
        freeze_commit=SEARCH_SPEC_V1_FREEZE_COMMIT,
        expected_spec_sha=EXPECTED_SEARCH_SPEC_V1_SHA256,
        expected_registry_sha=EXPECTED_CANDIDATE_REGISTRY_V1_SHA256,
        spec_rel=SEARCH_SPEC_V1_REL,
        registry_rel=REGISTRY_V1_REL,
    )


def verify_frozen_v2_artifacts(artifact_root: Path) -> dict[str, str]:
    """Fail closed if on-disk v2 spec/registry diverge from SEARCH_SPEC_V2_FREEZE_COMMIT."""
    import crypto_trading_bot.research_v2.indicator_parameter_search.frozen_spec as mod

    freeze_commit = mod.SEARCH_SPEC_V2_FREEZE_COMMIT
    expected_spec = mod.EXPECTED_SEARCH_SPEC_V2_SHA256
    expected_registry = mod.EXPECTED_CANDIDATE_REGISTRY_V2_SHA256
    return _verify_pair(
        artifact_root,
        spec_name="search_spec_v2.json",
        registry_name="candidate_registry_snapshot_v2.csv",
        freeze_commit=freeze_commit,
        expected_spec_sha=expected_spec,
        expected_registry_sha=expected_registry,
        spec_rel=SEARCH_SPEC_V2_REL,
        registry_rel=REGISTRY_V2_REL,
    )
