"""Disk-backed survivor composite stream store (no full survivor residency)."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import numpy as np

SURVIVOR_STREAM_DIR = "composite_survivor_streams_v1"
SURVIVOR_MANIFEST = "composite_survivor_stream_manifest_v1.json"


def _safe_name(composite_id: str) -> str:
    digest = hashlib.sha1(composite_id.encode("utf-8")).hexdigest()[:20]
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", composite_id)[:80]
    return f"{digest}__{slug}.npz"


class SurvivorStreamStore:
    """
    SURVIVOR_STREAM_STORAGE=DISK_BACKED
    ALL_SURVIVOR_STREAMS_IN_RAM=NO
    """

    def __init__(self, root: Path, *, dirname: str = SURVIVOR_STREAM_DIR) -> None:
        self.root = Path(root)
        self.dir = self.root / dirname
        self.dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.root / SURVIVOR_MANIFEST
        self._entries: list[dict[str, Any]] = []
        if self.manifest_path.exists():
            doc = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            self._entries = list(doc.get("streams") or [])

    def persist(
        self,
        *,
        composite_id: str,
        template_id: str,
        decision_tf: str,
        direction: str,
        trigger_candidate_id: str,
        context_candidate_ids: list[str],
        available_at_ns: np.ndarray,
        stream_sha256: str,
        composite_class: str,
    ) -> Path:
        fname = _safe_name(composite_id)
        path = self.dir / fname
        ns = np.asarray(available_at_ns, dtype=np.int64)
        np.savez_compressed(path, available_at_ns=ns)
        meta = {
            "composite_id": composite_id,
            "template_id": template_id,
            "decision_tf": decision_tf,
            "direction": direction,
            "trigger_candidate_id": trigger_candidate_id,
            "context_candidate_ids": list(context_candidate_ids),
            "COMPOSITE_STREAM_SHA256": stream_sha256,
            "n_signals": int(ns.size),
            "composite_class": composite_class,
            "shard_file": fname,
        }
        (self.dir / f"{fname}.meta.json").write_text(json.dumps(meta), encoding="utf-8")
        self._entries = [e for e in self._entries if e.get("composite_id") != composite_id]
        self._entries.append(meta)
        self._flush_manifest()
        return path

    def _flush_manifest(self) -> None:
        doc = {
            "artifact": "composite_survivor_stream_manifest_v1",
            "SURVIVOR_STREAM_STORAGE": "DISK_BACKED",
            "ALL_SURVIVOR_STREAMS_IN_RAM": "NO",
            "n_streams": len(self._entries),
            "streams": self._entries,
        }
        tmp = self.manifest_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        tmp.replace(self.manifest_path)

    def load_ns(self, composite_id: str) -> np.ndarray:
        for e in self._entries:
            if e["composite_id"] == composite_id:
                data = np.load(self.dir / e["shard_file"])
                return np.asarray(data["available_at_ns"], dtype=np.int64)
        raise KeyError(composite_id)

    def entries(self) -> list[dict[str, Any]]:
        return list(self._entries)
