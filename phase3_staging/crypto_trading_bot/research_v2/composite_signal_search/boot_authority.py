"""Boot/resume authority fail-closed gate for production compose."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .enumeration_authority import EnumerationAuthorityError
from .stream_store import verify_shard_integrity

EXPECTED_ENUM = "397533c24eb48bd7e0c1f18dedc4d94393c5965107cc6165eb59ecad592f7b3e"
EXPECTED_TOTAL = 200829
EXPECTED_SHAS = {
    "COMPOSITE_SEARCH_SPEC_SHA": (
        "composite_search_spec_v1.json",
        "d470350a0f3f44b8a64f4d681a8efa80241877d826ba76d96143b50c82c05323",
    ),
    "COMPOSITE_TEMPLATES_SHA": (
        "composite_templates_v1.json",
        "22b52c33f60b8668721e6aab744e6bb22ea1b8b84c91de4e6637cbac3f08583f",
    ),
    "COMPOSITE_ATOMIC_BANK_SHA": (
        "composite_atomic_bank_v1.json",
        "2e6a4ad0328e902d8eda2b67bafe4f7ca804ac29fe6cb095fedc4ee53fab440a",
    ),
    "DEVELOPMENT_CORPUS_SHA": (
        "development_corpus_manifest_v1.json",
        "505ecb91170b5286cb7a8da8f8dc24808cf18067317546e8246bfd2972201f95",
    ),
}

# Critical runtime modules — must match authority source digests when present.
RUNTIME_SOURCE_RELPATHS = (
    "crypto_trading_bot/research_v2/composite_signal_search/bounded_compose.py",
    "crypto_trading_bot/research_v2/composite_signal_search/boot_authority.py",
    "crypto_trading_bot/research_v2/composite_signal_search/durable_io.py",
    "crypto_trading_bot/research_v2/composite_signal_search/result_parts.py",
    "crypto_trading_bot/research_v2/composite_signal_search/survivor_store.py",
    "crypto_trading_bot/research_v2/composite_signal_search/run_search.py",
    "crypto_trading_bot/research_v2/composite_signal_search/finalize.py",
    "crypto_trading_bot/research_v2/composite_signal_search/classify.py",
    "crypto_trading_bot/research_v2/composite_signal_search/compose.py",
    "crypto_trading_bot/research_v2/composite_signal_search/memory_guard.py",
    "crypto_trading_bot/research_v2/composite_signal_search/enumeration_authority.py",
)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def assert_boot_resume_authority(artifact_root: Path) -> dict[str, Any]:
    """
    BOOT_RESUME_AUTHORITY_GATE — fail closed before processing candidates.
    """
    root = Path(artifact_root)
    errors: list[str] = []

    for key, (fname, expected) in EXPECTED_SHAS.items():
        path = root / fname
        if not path.exists():
            errors.append(f"missing {fname}")
            continue
        digest = _sha256_file(path)
        if digest != expected:
            errors.append(f"{key} mismatch")

    enum_path = root / "composite_enumeration_authority_v1.json"
    if not enum_path.exists():
        errors.append("enumeration authority missing")
    else:
        enum = json.loads(enum_path.read_text(encoding="utf-8"))
        if enum.get("COMPOSITE_ENUMERATION_SHA256") != EXPECTED_ENUM:
            errors.append("enumeration SHA mismatch")
        if int(enum.get("TOTAL_COMPOSITE_CANDIDATE_COUNT") or -1) != EXPECTED_TOTAL:
            errors.append("enumeration total mismatch")

    try:
        shard_gate = verify_shard_integrity(root, expected_n=582)
        if shard_gate.get("SHARD_INTEGRITY_GATE") != "PASS":
            errors.append("shard integrity gate fail")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"shard integrity error: {exc}")
        shard_gate = {"SHARD_INTEGRITY_GATE": "FAIL"}

    auth_path = root / "full_composite_execution_authority_v1.json"
    execution_commit = None
    if not auth_path.exists():
        errors.append("full_composite_execution_authority_v1.json missing")
    else:
        auth = json.loads(auth_path.read_text(encoding="utf-8"))
        execution_commit = auth.get("EXECUTION_AUTHORITY_COMMIT")
        if auth.get("AUTHORITY_READY") != "YES":
            errors.append("AUTHORITY_READY!=YES")
        if auth.get("S13_RUNTIME_SOURCE_MATCH") == "FAIL":
            errors.append("authority artifact marks runtime source mismatch")
        # Live re-check runtime sources against authority digests when provided.
        source_shas = auth.get("RUNTIME_SOURCE_SHAS") or {}
        pkg = Path(__file__).resolve().parents[3]  # .../phase3_staging
        # __file__ = .../composite_signal_search/boot_authority.py
        # parents[0]=composite_signal_search, [1]=research_v2, [2]=crypto_trading_bot, [3]=phase3_staging
        for rel in RUNTIME_SOURCE_RELPATHS:
            path = pkg / rel
            if not path.exists():
                errors.append(f"runtime source missing: {rel}")
                continue
            got = _sha256_file(path)
            expected = source_shas.get(rel) or source_shas.get(f"phase3_staging/{rel}")
            if expected and got != expected:
                errors.append(f"runtime source mismatch: {rel}")

    if errors:
        raise EnumerationAuthorityError("BOOT_RESUME_AUTHORITY_GATE=FAIL — " + "; ".join(errors))
    return {
        "BOOT_RESUME_AUTHORITY_GATE": "PASS",
        "EXECUTION_AUTHORITY_COMMIT": execution_commit,
        "SHARD_INTEGRITY_GATE": shard_gate.get("SHARD_INTEGRITY_GATE"),
        "COMPOSITE_ENUMERATION_SHA256": EXPECTED_ENUM,
        "TOTAL_COMPOSITE_CANDIDATE_COUNT": EXPECTED_TOTAL,
    }
