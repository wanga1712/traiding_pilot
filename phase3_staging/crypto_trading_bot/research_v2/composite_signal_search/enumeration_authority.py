"""Deterministic global composite enumeration authority (streaming SHA256)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterator

from .compose import iter_all_template_definitions
from .config import load_atomic_bank, load_templates
from .memory_guard import save_json

ENUMERATION_AUTHORITY = "composite_enumeration_authority_v1.json"
SPEC_FREEZE_COMMIT = "476927817e21ef6869261a0114b27864fdf2d789"


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stream_composite_ids(
    *,
    artifact_root: Path,
    representatives: list[dict[str, Any]] | None = None,
    all_configs: list[dict[str, Any]] | None = None,
    templates_doc: dict[str, Any] | None = None,
) -> Iterator[str]:
    root = Path(artifact_root)
    if representatives is None:
        reps_bank = json.loads((root / "atomic_representative_bank_v1.json").read_text(encoding="utf-8"))
        representatives = list(reps_bank["configs"])
    if all_configs is None:
        all_configs = list(load_atomic_bank(root=root)["configs"])
    if templates_doc is None:
        templates_doc = load_templates(root=root)
    for comp in iter_all_template_definitions(
        representatives=representatives,
        all_configs_for_pairs=all_configs,
        templates_doc=templates_doc,
    ):
        yield str(comp["composite_id"])


def build_enumeration_authority(
    *,
    artifact_root: Path,
    force: bool = False,
) -> dict[str, Any]:
    """
    Stream composite IDs once; update SHA256 incrementally.
    Do NOT materialize the full ID list in RAM.
    """
    root = Path(artifact_root)
    out_path = root / ENUMERATION_AUTHORITY
    if out_path.exists() and not force:
        return json.loads(out_path.read_text(encoding="utf-8"))

    tmpl_path = root / "composite_templates_v1.json"
    bank_path = root / "composite_atomic_bank_v1.json"
    reps_path = root / "atomic_representative_bank_v1.json"
    templates_sha = _file_sha256(tmpl_path)
    atomic_sha = _file_sha256(bank_path)
    reps_sha = _file_sha256(reps_path)

    h = hashlib.sha256()
    count = 0
    for cid in stream_composite_ids(artifact_root=root):
        h.update(cid.encode("utf-8"))
        h.update(b"\n")
        count += 1

    doc = {
        "artifact": "composite_enumeration_authority_v1",
        "WIP": "MULTITF-COMPOSITE-SIGNAL-SEARCH-1",
        "SPEC_FREEZE_COMMIT": SPEC_FREEZE_COMMIT,
        "representative_bank_sha256": reps_sha,
        "COMPOSITE_TEMPLATES_SHA": templates_sha,
        "COMPOSITE_ATOMIC_BANK_SHA": atomic_sha,
        "TOTAL_COMPOSITE_CANDIDATE_COUNT": count,
        "COMPOSITE_ENUMERATION_SHA256": h.hexdigest(),
        "GLOBAL_ENUMERATION_AUTHORITY": "PASS",
        "note": "SHA256 over ordered composite_id lines (utf-8 + newline), streamed once.",
    }
    save_json(out_path, doc)
    return doc


def load_enumeration_authority(artifact_root: Path) -> dict[str, Any]:
    path = Path(artifact_root) / ENUMERATION_AUTHORITY
    if not path.exists():
        return build_enumeration_authority(artifact_root=artifact_root, force=False)
    return json.loads(path.read_text(encoding="utf-8"))


class EnumerationAuthorityError(RuntimeError):
    """Checkpoint enumeration authority does not match frozen stream."""
