"""Durable filesystem helpers: fsync files/dirs and atomic replace."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def fsync_path(path: Path) -> None:
    """Fsync an existing file."""
    path = Path(path)
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def fsync_dir(path: Path) -> None:
    """Fsync a directory (best-effort; required after atomic rename)."""
    path = Path(path)
    flags = getattr(os, "O_DIRECTORY", 0) or 0
    try:
        fd = os.open(str(path), os.O_RDONLY | flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """
    temp write → flush/fsync → atomic rename → fsync directory.
    Half-written content never appears under the final name.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(str(tmp), str(path))
    fsync_path(path)
    fsync_dir(path.parent)


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    atomic_write_bytes(path, text.encode(encoding))


def save_json_durable(path: Path, obj: Any) -> None:
    """CHECKPOINT_ATOMIC_REPLACE=YES with fsync."""
    payload = json.dumps(obj, indent=2, default=str)
    atomic_write_text(path, payload)
