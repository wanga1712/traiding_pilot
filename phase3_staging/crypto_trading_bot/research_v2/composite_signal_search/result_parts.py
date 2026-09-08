"""Append-only parquet part writers — never re-read previous parts during flush."""
from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

RESULTS_PARTS_DIR = "composite_results_partial_parts_v1"
FOLDS_PARTS_DIR = "composite_fold_partial_parts_v1"
_PART_RE = re.compile(r"^part-(\d{6})\.parquet$")


def part_index(path: Path) -> int | None:
    m = _PART_RE.match(path.name)
    return int(m.group(1)) if m else None


def reconcile_orphan_parts(
    parts_dir: Path,
    *,
    committed_next_part: int,
    quarantine_dir: Path,
) -> list[str]:
    """
    RESULT_PART_RESUME_CRASH_SAFE=YES

    Parts with index >= committed_next_part are uncommitted orphans from a
    crash between part write and checkpoint commit. Move them aside; never
    overwrite a committed part.
    """
    parts_dir = Path(parts_dir)
    if not parts_dir.exists():
        return []
    quarantine_dir = Path(quarantine_dir)
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    moved: list[str] = []
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for path in sorted(parts_dir.glob("part-*.parquet")):
        idx = part_index(path)
        if idx is None:
            continue
        if idx >= int(committed_next_part):
            dest = quarantine_dir / f"{stamp}__{path.name}"
            shutil.move(str(path), str(dest))
            moved.append(path.name)
    return moved


class AppendOnlyPartWriter:
    """
    RESULT_WRITER_APPEND_ONLY=YES
    PREVIOUS_RESULT_ROWS_READ_DURING_FLUSH=NO
    RESULT_MEMORY_COMPLEXITY=O(CURRENT_BATCH)

    Each flush writes ONLY the current batch to part-NNNNNN.parquet.
    """

    def __init__(self, root: Path, *, dirname: str, next_part: int = 0) -> None:
        self.root = Path(root)
        self.dir = self.root / dirname
        self.dir.mkdir(parents=True, exist_ok=True)
        self.next_part = max(0, int(next_part))
        self._read_count = 0  # instrumentation for tests

    def flush(self, rows: list[dict[str, Any]]) -> Path | None:
        if not rows:
            return None
        # Intentionally never list/read prior parts here.
        path = self.dir / f"part-{self.next_part:06d}.parquet"
        if path.exists():
            raise FileExistsError(f"refusing to overwrite completed part: {path}")
        pd.DataFrame(rows).to_parquet(path, index=False)
        self.next_part += 1
        return path

    def part_paths(self) -> list[Path]:
        """Offline helper only — not used by flush()."""
        self._read_count += 1
        return sorted(self.dir.glob("part-*.parquet"))
