#!/usr/bin/env python3
"""Repair-3: preserve repair-2 smoke contamination, clean production compose state."""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ART = Path("/var/tmp/traiding_pilot_ui_workspace/artifacts/MULTITF-COMPOSITE-SIGNAL-SEARCH-1")
CKPT = ART / "composite_execution_checkpoint_v1.json"
RESULTS = ART / "composite_results_partial_parts_v1"
FOLDS = ART / "composite_fold_partial_parts_v1"
AUDIT = ART / "_repair2_smoke_contamination_audit_v1"
ATOMIC_CKPT = ART / "atomic_streams_checkpoint_v1.pkl"
ATOMIC_CACHE = ART / "atomic_streams_cache_v1.pkl"
MANIFEST = ART / "atomic_streams_shard_manifest_v1.json"


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    AUDIT.mkdir(parents=True, exist_ok=True)
    found = CKPT.exists()
    preserved = "NOT_PRESENT"
    if found:
        dest = ART / "composite_execution_checkpoint_repair2_smoke_v1.json"
        shutil.copy2(CKPT, dest)
        shutil.copy2(CKPT, AUDIT / "composite_execution_checkpoint_v1.json")
        preserved = "YES"
        CKPT.unlink()
        print("preserved checkpoint ->", dest)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for name, src in (("results", RESULTS), ("folds", FOLDS)):
        if src.exists():
            dest = AUDIT / f"{stamp}_{name}"
            if dest.exists():
                shutil.rmtree(dest)
            shutil.move(str(src), str(dest))
            print("moved", src, "->", dest)

    # Ensure production dirs absent
    if RESULTS.exists():
        shutil.rmtree(RESULTS)
    if FOLDS.exists():
        shutil.rmtree(FOLDS)
    if CKPT.exists():
        CKPT.unlink()

    atomic_ok = ATOMIC_CKPT.exists() and MANIFEST.exists()
    n_streams = 0
    if MANIFEST.exists():
        n_streams = int(json.loads(MANIFEST.read_text(encoding="utf-8")).get("n_streams") or 0)

    report = {
        "artifact": "repair3_production_clean_v1",
        "REPAIR2_SMOKE_CHECKPOINT_FOUND": "YES" if found else "NO",
        "REPAIR2_SMOKE_CHECKPOINT_PRESERVED": preserved,
        "PRODUCTION_COMPOSE_CHECKPOINT_CLEAN": "YES" if not CKPT.exists() else "NO",
        "PRODUCTION_COMPOSE_RESULT_PARTS_CLEAN": "YES"
        if (not RESULTS.exists() and not FOLDS.exists())
        else "NO",
        "ATOMIC_CHECKPOINT_PRESERVED": "YES" if atomic_ok else "NO",
        "ATOMIC_CHECKPOINT_COUNT": n_streams,
        "atomic_checkpoint_sha256": _sha(ATOMIC_CKPT) if ATOMIC_CKPT.exists() else None,
        "atomic_cache_sha256": _sha(ATOMIC_CACHE) if ATOMIC_CACHE.exists() else None,
        "audit_dir": str(AUDIT),
    }
    (ART / "repair3_production_clean_v1.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["PRODUCTION_COMPOSE_CHECKPOINT_CLEAN"] == "YES" and atomic_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
