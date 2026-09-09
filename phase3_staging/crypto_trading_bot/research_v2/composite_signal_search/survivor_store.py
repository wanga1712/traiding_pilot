"""Disk-backed survivor streams with append-only metadata (no per-signal global rewrite)."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterator

import numpy as np

SURVIVOR_STREAM_DIR = "composite_survivor_streams_v1"
SURVIVOR_META_PARTS_DIR = "composite_survivor_metadata_parts_v1"
SURVIVOR_MANIFEST = "composite_survivor_stream_manifest_v1.json"
SURVIVOR_META_BATCH_SIZE = 100


class SurvivorStreamMismatchError(RuntimeError):
    """Existing survivor shard does not match new persist request — fail closed."""


def _safe_name(composite_id: str) -> str:
    digest = hashlib.sha1(composite_id.encode("utf-8")).hexdigest()[:20]
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", composite_id)[:80]
    return f"{digest}__{slug}.npz"


def _meta_identity(meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "composite_id": meta["composite_id"],
        "COMPOSITE_STREAM_SHA256": meta["COMPOSITE_STREAM_SHA256"],
        "n_signals": int(meta["n_signals"]),
        "direction": meta["direction"],
        "decision_tf": meta["decision_tf"],
    }


class SurvivorStreamStore:
    """
    SURVIVOR_STREAM_STORAGE=DISK_BACKED
    ALL_SURVIVOR_STREAMS_IN_RAM=NO
    SURVIVOR_GLOBAL_MANIFEST_REWRITE_PER_SIGNAL=NO
    SURVIVOR_METADATA_APPEND_ONLY=YES
    SURVIVOR_METADATA_MEMORY_COMPLEXITY=O(CURRENT_BATCH)
    """

    def __init__(self, root: Path, *, dirname: str = SURVIVOR_STREAM_DIR) -> None:
        self.root = Path(root)
        self.dir = self.root / dirname
        self.dir.mkdir(parents=True, exist_ok=True)
        self.meta_parts_dir = self.root / SURVIVOR_META_PARTS_DIR
        self.meta_parts_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.root / SURVIVOR_MANIFEST
        self._batch: list[dict[str, Any]] = []
        self._next_meta_part = self._detect_next_meta_part()
        self._persisted_this_run = 0
        self._reused_idempotent = 0

    def _detect_next_meta_part(self) -> int:
        existing = sorted(self.meta_parts_dir.glob("part-*.jsonl"))
        if not existing:
            return 0
        last = existing[-1].name
        try:
            return int(last.split("-")[1].split(".")[0]) + 1
        except (IndexError, ValueError):
            return len(existing)

    def _meta_path(self, fname: str) -> Path:
        return self.dir / f"{fname}.meta.json"

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
        meta_path = self._meta_path(fname)

        if path.exists() or meta_path.exists():
            if not path.exists() or not meta_path.exists():
                raise SurvivorStreamMismatchError(
                    f"partial survivor shard for {composite_id}: path={path.exists()} meta={meta_path.exists()}"
                )
            old = json.loads(meta_path.read_text(encoding="utf-8"))
            if _meta_identity(old) != _meta_identity(meta):
                raise SurvivorStreamMismatchError(
                    f"survivor stream mismatch for {composite_id}: "
                    f"old={_meta_identity(old)} new={_meta_identity(meta)}"
                )
            # Exact match — idempotent reuse; do not append duplicate metadata.
            # Final assembly also reads per-shard .meta.json for unflushed crash windows.
            self._reused_idempotent += 1
            return path

        np.savez_compressed(path, available_at_ns=ns)
        meta_path.write_text(json.dumps(meta, separators=(",", ":")), encoding="utf-8")
        self._batch.append(meta)
        self._persisted_this_run += 1
        if len(self._batch) >= SURVIVOR_META_BATCH_SIZE:
            self.flush_metadata()
        return path

    def flush_metadata(self) -> Path | None:
        if not self._batch:
            return None
        part = self.meta_parts_dir / f"part-{self._next_meta_part:06d}.jsonl"
        with part.open("w", encoding="utf-8") as fh:
            for row in self._batch:
                fh.write(json.dumps(row, separators=(",", ":")) + "\n")
        self._next_meta_part += 1
        self._batch = []
        return part

    def close(self) -> None:
        self.flush_metadata()

    def load_ns(self, composite_id: str) -> np.ndarray:
        fname = _safe_name(composite_id)
        path = self.dir / fname
        if not path.exists():
            raise KeyError(composite_id)
        data = np.load(path)
        return np.asarray(data["available_at_ns"], dtype=np.int64)

    def iter_meta_records(self) -> Iterator[dict[str, Any]]:
        """Stream metadata without holding all survivors in RAM."""
        seen: set[str] = set()
        parts = sorted(self.meta_parts_dir.glob("part-*.jsonl"))
        for part in parts:
            with part.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    row = json.loads(line)
                    cid = row["composite_id"]
                    if cid in seen:
                        continue
                    seen.add(cid)
                    yield row
        # Include per-shard .meta.json not yet flushed to parts (crash window).
        for meta_path in sorted(self.dir.glob("*.meta.json")):
            row = json.loads(meta_path.read_text(encoding="utf-8"))
            cid = row["composite_id"]
            if cid in seen:
                continue
            seen.add(cid)
            yield row

    def assemble_final_manifest(self) -> dict[str, Any]:
        """Assemble canonical manifest ONCE after compose/finalization."""
        self.flush_metadata()
        by_id: dict[str, dict[str, Any]] = {}
        dup = 0
        missing = 0
        for row in self.iter_meta_records():
            cid = row["composite_id"]
            if cid in by_id:
                dup += 1
                continue
            shard = self.dir / row["shard_file"]
            if not shard.exists():
                missing += 1
                continue
            data = np.load(shard)
            ns = np.asarray(data["available_at_ns"], dtype=np.int64)
            if int(ns.size) != int(row["n_signals"]):
                raise SurvivorStreamMismatchError(
                    f"n_signals mismatch in final assembly for {cid}: meta={row['n_signals']} array={ns.size}"
                )
            # Optional: verify stream SHA matches stored array identity fields already in meta.
            by_id[cid] = row
        entries = [by_id[k] for k in sorted(by_id.keys())]
        doc = {
            "artifact": "composite_survivor_stream_manifest_v1",
            "SURVIVOR_STREAM_STORAGE": "DISK_BACKED",
            "ALL_SURVIVOR_STREAMS_IN_RAM": "NO",
            "SURVIVOR_GLOBAL_MANIFEST_REWRITE_PER_SIGNAL": "NO",
            "SURVIVOR_METADATA_APPEND_ONLY": "YES",
            "SURVIVOR_FINAL_MANIFEST_ASSEMBLY": "PASS" if missing == 0 else "FAIL",
            "SURVIVOR_DUPLICATE_METADATA_COUNT": dup,
            "SURVIVOR_MISSING_SHARD_COUNT": missing,
            "n_streams": len(entries),
            "streams": entries,
        }
        tmp = self.manifest_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        tmp.replace(self.manifest_path)
        return doc

    def entries(self) -> list[dict[str, Any]]:
        """Offline helper — materializes metadata list (finalization only)."""
        return list(self.iter_meta_records())
