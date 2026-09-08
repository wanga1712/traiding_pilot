"""Disk-backed atomic stream store: lazy per-candidate load, compact int64 times."""
from __future__ import annotations

import hashlib
import json
import pickle
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.bars import parse_ts

SHARD_DIR_NAME = "atomic_streams_shards_v1"
SHARD_MANIFEST = "atomic_streams_shard_manifest_v1.json"
MAX_ACTIVE_DEFAULT = 5


def _as_utc_ns(value: Any) -> int:
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1_000_000_000)
    dt = parse_ts(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1_000_000_000)


def safe_shard_name(candidate_id: str) -> str:
    digest = hashlib.sha1(candidate_id.encode("utf-8")).hexdigest()[:20]
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", candidate_id)[:80]
    return f"{digest}__{slug}.npz"


@dataclass(frozen=True)
class CompactStream:
    candidate_id: str
    decision_tf: str
    direction: str
    available_at_ns: np.ndarray  # int64, causal emission order
    signal_price: np.ndarray  # float64 aligned
    stream_hash: str
    n_signals: int

    def to_signal_dicts(
        self, *, direction: str | None = None, decision_tf: str | None = None
    ) -> list[dict[str, Any]]:
        direction = direction or self.direction
        decision_tf = decision_tf or self.decision_tf
        out: list[dict[str, Any]] = []
        for i in range(self.n_signals):
            ts = datetime.fromtimestamp(int(self.available_at_ns[i]) / 1_000_000_000, tz=timezone.utc)
            iso = ts.isoformat()
            out.append(
                {
                    "signal_id": f"{self.candidate_id}|{iso}",
                    "candidate_id": self.candidate_id,
                    "available_at": iso,
                    "signal_time": iso,
                    "signal_direction": direction,
                    "signal_price": float(self.signal_price[i]),
                    "calculated_at": iso,
                    "decision_tf": decision_tf,
                }
            )
        return out


def record_to_compact(rec: dict[str, Any]) -> CompactStream:
    events = list(rec.get("events") or [])
    if events:
        ns = np.fromiter((_as_utc_ns(e["available_at"]) for e in events), dtype=np.int64, count=len(events))
        prices = np.fromiter(
            (float(e.get("signal_price") or e.get("price") or 0.0) for e in events),
            dtype=np.float64,
            count=len(events),
        )
    else:
        av = list(rec.get("available_at") or [])
        ns = np.fromiter((_as_utc_ns(x) for x in av), dtype=np.int64, count=len(av))
        prices = np.zeros(len(av), dtype=np.float64)
    return CompactStream(
        candidate_id=str(rec["candidate_id"]),
        decision_tf=str(rec.get("decision_tf") or ""),
        direction=str(rec.get("direction") or ""),
        available_at_ns=ns,
        signal_price=prices,
        stream_hash=str(rec.get("stream_hash") or ""),
        n_signals=int(len(ns)),
    )


def materialize_shards_from_pickle(
    *,
    artifact_root: Path,
    pickle_name: str = "atomic_streams_cache_v1.pkl",
    force: bool = False,
) -> dict[str, Any]:
    """One-shot conversion of monolithic pickle → per-id npz shards (no replay)."""
    root = Path(artifact_root)
    shard_dir = root / SHARD_DIR_NAME
    manifest_path = root / SHARD_MANIFEST
    if manifest_path.exists() and shard_dir.exists() and not force:
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    pkl = root / pickle_name
    if not pkl.exists():
        pkl = root / "atomic_streams_checkpoint_v1.pkl"
    with pkl.open("rb") as fh:
        streams: dict[str, dict[str, Any]] = pickle.load(fh)

    shard_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    for cid, rec in streams.items():
        payload = rec if "candidate_id" in rec else {**rec, "candidate_id": cid}
        compact = record_to_compact(payload)
        fname = safe_shard_name(cid)
        path = shard_dir / fname
        np.savez_compressed(
            path,
            available_at_ns=compact.available_at_ns,
            signal_price=compact.signal_price,
        )
        meta = {
            "candidate_id": cid,
            "decision_tf": compact.decision_tf,
            "direction": compact.direction,
            "stream_hash": compact.stream_hash,
            "n_signals": compact.n_signals,
            "shard_file": fname,
        }
        (shard_dir / f"{fname}.meta.json").write_text(json.dumps(meta), encoding="utf-8")
        entries.append(meta)

    manifest = {
        "artifact": "atomic_streams_shard_manifest_v1",
        "n_streams": len(entries),
        "shard_dir": SHARD_DIR_NAME,
        "source_pickle": pkl.name,
        "source_pickle_bytes": pkl.stat().st_size,
        "representation": "available_at_ns_int64 + signal_price_float64",
        "HOT_PATH_OBJECT_DTYPE": "NO",
        "streams": entries,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


class ShardIntegrityError(RuntimeError):
    """Raised when required disk shards are missing or corrupt — fail closed."""


def verify_shard_integrity(artifact_root: Path, *, expected_n: int = 582) -> dict[str, Any]:
    """
    FULL_COMPOSE_MONOLITHIC_PICKLE_FALLBACK=NO
    SHARD_INTEGRITY_GATE — require manifest + all shard files before compose.

    Also require manifest candidate IDs == frozen composite_atomic_bank_v1.json IDs.
    """
    root = Path(artifact_root)
    manifest_path = root / SHARD_MANIFEST
    shard_dir = root / SHARD_DIR_NAME
    bank_path = root / "composite_atomic_bank_v1.json"
    if not manifest_path.exists():
        raise ShardIntegrityError(
            "atomic_streams_shard_manifest_v1.json missing. "
            "Run materialize_shards_from_pickle() offline first; "
            "full compose will not load the monolithic pickle."
        )
    if not shard_dir.is_dir():
        raise ShardIntegrityError(f"shard dir missing: {shard_dir}")
    if not bank_path.exists():
        raise ShardIntegrityError(f"frozen atomic bank missing: {bank_path.name}")
    bank = json.loads(bank_path.read_text(encoding="utf-8"))
    bank_ids = [c["candidate_id"] for c in bank.get("configs") or []]
    bank_set = set(bank_ids)
    if len(bank_ids) != len(bank_set):
        raise ShardIntegrityError("duplicate candidate_id in composite_atomic_bank_v1.json")
    if len(bank_set) != expected_n:
        raise ShardIntegrityError(f"atomic bank n={len(bank_set)} expected={expected_n}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = list(manifest.get("streams") or [])
    if len(entries) != expected_n:
        raise ShardIntegrityError(f"manifest n_streams={len(entries)} expected={expected_n}")
    ids: set[str] = set()
    for e in entries:
        cid = e["candidate_id"]
        if cid in ids:
            raise ShardIntegrityError(f"duplicate candidate_id in manifest: {cid}")
        ids.add(cid)
        path = shard_dir / e["shard_file"]
        if not path.exists():
            raise ShardIntegrityError(f"missing shard file for {cid}: {path.name}")
        data = np.load(path)
        ns = np.asarray(data["available_at_ns"])
        prices = np.asarray(data["signal_price"])
        if ns.dtype != np.int64:
            raise ShardIntegrityError(f"non-int64 timestamps for {cid}: {ns.dtype}")
        n_meta = int(e["n_signals"])
        if n_meta != int(ns.size):
            raise ShardIntegrityError(
                f"n_signals mismatch for {cid}: meta={n_meta} available_at={ns.size}"
            )
        if int(prices.size) != n_meta:
            raise ShardIntegrityError(
                f"signal_price length mismatch for {cid}: meta={n_meta} prices={prices.size}"
            )
    unknown = sorted(ids - bank_set)
    missing = sorted(bank_set - ids)
    if unknown or missing:
        raise ShardIntegrityError(
            f"shard candidate set mismatch unknown={len(unknown)} missing={len(missing)}"
        )
    return {
        "SHARD_INTEGRITY_GATE": "PASS",
        "n_streams": len(entries),
        "FULL_COMPOSE_MONOLITHIC_PICKLE_FALLBACK": "NO",
        "SHARD_CANDIDATE_SET_MATCH": "PASS",
        "SHARD_UNKNOWN_CANDIDATE_COUNT": 0,
        "SHARD_MISSING_CANDIDATE_COUNT": 0,
    }


class AtomicStreamStore:
    """LRU lazy loader — never holds all 582 streams simultaneously."""

    def __init__(
        self,
        artifact_root: Path,
        *,
        max_active: int = MAX_ACTIVE_DEFAULT,
        require_shards: bool = True,
        expected_n: int = 582,
    ) -> None:
        self.root = Path(artifact_root)
        self.shard_dir = self.root / SHARD_DIR_NAME
        self.max_active = max(1, int(max_active))
        manifest_path = self.root / SHARD_MANIFEST
        if require_shards:
            verify_shard_integrity(self.root, expected_n=expected_n)
        elif not manifest_path.exists():
            raise ShardIntegrityError(
                "shards required but missing; refuse monolithic pickle fallback"
            )
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self._by_id = {e["candidate_id"]: e for e in self.manifest["streams"]}
        self._lock = threading.Lock()
        self._lru: OrderedDict[str, CompactStream] = OrderedDict()

    def __contains__(self, candidate_id: str) -> bool:
        return candidate_id in self._by_id

    def __len__(self) -> int:
        return len(self._by_id)

    def ids(self) -> Iterator[str]:
        yield from self._by_id.keys()

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._lru)

    def get(self, candidate_id: str) -> CompactStream:
        with self._lock:
            if candidate_id in self._lru:
                self._lru.move_to_end(candidate_id)
                return self._lru[candidate_id]
        meta = self._by_id[candidate_id]
        path = self.shard_dir / meta["shard_file"]
        data = np.load(path)
        stream = CompactStream(
            candidate_id=candidate_id,
            decision_tf=str(meta["decision_tf"]),
            direction=str(meta["direction"]),
            available_at_ns=np.asarray(data["available_at_ns"], dtype=np.int64),
            signal_price=np.asarray(data["signal_price"], dtype=np.float64),
            stream_hash=str(meta.get("stream_hash") or ""),
            n_signals=int(meta["n_signals"]),
        )
        with self._lock:
            self._lru[candidate_id] = stream
            self._lru.move_to_end(candidate_id)
            while len(self._lru) > self.max_active:
                self._lru.popitem(last=False)
        return stream

    def release(self, candidate_id: str | None = None) -> None:
        with self._lock:
            if candidate_id is None:
                self._lru.clear()
            else:
                self._lru.pop(candidate_id, None)
