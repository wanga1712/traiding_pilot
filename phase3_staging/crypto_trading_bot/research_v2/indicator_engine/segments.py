"""Contiguous segment utilities — recursive state must not cross gaps."""
from __future__ import annotations

from typing import Iterator

import numpy as np

RECURSIVE_STATE_CROSSES_GAP = "NO"


def segment_starts(gap_flags: np.ndarray) -> list[int]:
    """Index of each contiguous segment start (0 and every gap_flags[i]==True)."""
    if len(gap_flags) == 0:
        return []
    starts = [0]
    for i in range(1, len(gap_flags)):
        if gap_flags[i]:
            starts.append(i)
    return starts


def iter_segments(gap_flags: np.ndarray, length: int | None = None) -> Iterator[tuple[int, int]]:
    """Yield inclusive (start, end) for each contiguous segment."""
    n = length if length is not None else len(gap_flags)
    if n == 0:
        return
    starts = segment_starts(gap_flags[:n])
    for si, start in enumerate(starts):
        end = (starts[si + 1] - 1) if si + 1 < len(starts) else (n - 1)
        yield start, end


def same_segment(gap_flags: np.ndarray, a: int, b: int) -> bool:
    """True if indices a and b lie in the same contiguous segment."""
    if a < 0 or b < 0 or a >= len(gap_flags) or b >= len(gap_flags):
        return False
    if a > b:
        a, b = b, a
    if a == b:
        return True
    return not bool(np.any(gap_flags[a + 1 : b + 1]))


def segment_start_for(gap_flags: np.ndarray, index: int) -> int:
    """Segment start index containing `index`."""
    start = 0
    for i in range(1, min(index, len(gap_flags)) + 1):
        if gap_flags[i]:
            start = i
    return start


def segment_starts_array(gap_flags: np.ndarray) -> np.ndarray:
    """O(n) array where out[i] is segment start index for bar i."""
    n = len(gap_flags)
    out = np.zeros(n, dtype=int)
    start = 0
    for i in range(n):
        if i > 0 and gap_flags[i]:
            start = i
        out[i] = start
    return out
