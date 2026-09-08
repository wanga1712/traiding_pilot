"""Memory guard + bounded composite compose execution."""
from __future__ import annotations

import gc
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


class MemoryGuardStop(RuntimeError):
    """Controlled stop when RSS exceeds MEMORY_GUARD_THRESHOLD_GB — resumable."""

    def __init__(self, message: str, *, rss_gb: float, threshold_gb: float) -> None:
        super().__init__(message)
        self.rss_gb = rss_gb
        self.threshold_gb = threshold_gb


def read_rss_bytes() -> int:
    """Best-effort current RSS in bytes (Linux /proc, else 0)."""
    try:
        with open("/proc/self/status", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    return int(parts[1]) * 1024
    except OSError:
        pass
    try:
        import resource

        # Linux: ru_maxrss is KB; macOS: bytes. Prefer /proc above.
        return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024
    except Exception:  # noqa: BLE001
        return 0


def read_vms_bytes() -> int:
    try:
        with open("/proc/self/status", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmSize:"):
                    parts = line.split()
                    return int(parts[1]) * 1024
    except OSError:
        pass
    return 0


@dataclass
class MemoryGuard:
    threshold_gb: float = 9.0
    warning_gb: float = 9.0
    poll_every: int = 1

    def rss_gb(self) -> float:
        return read_rss_bytes() / (1024**3)

    def check(self, *, context: str = "") -> float:
        rss = self.rss_gb()
        if rss >= float(self.threshold_gb):
            raise MemoryGuardStop(
                f"MEMORY_GUARD_STOP rss_gb={rss:.3f} threshold_gb={self.threshold_gb} {context}",
                rss_gb=rss,
                threshold_gb=float(self.threshold_gb),
            )
        return rss


def save_json(path: Path, obj: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


COMPOSITE_CHECKPOINT = "composite_execution_checkpoint_v1.json"
COMPOSITE_RESULT_PARTIAL = "composite_results_partial_v1.parquet"
COMPOSITE_FOLD_PARTIAL = "composite_fold_stability_partial_v1.parquet"
COMPOSITE_RESULT_BATCH_SIZE = 100
COMPOSITE_CHECKPOINT_EVERY = 50


def default_memory_guard() -> MemoryGuard:
    thr = float(os.environ.get("MEMORY_GUARD_THRESHOLD_GB", "9"))
    warn = float(os.environ.get("RSS_WARNING_GB", "9"))
    return MemoryGuard(threshold_gb=thr, warning_gb=warn)
