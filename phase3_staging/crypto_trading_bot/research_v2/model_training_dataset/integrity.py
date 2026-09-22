from __future__ import annotations
import numpy as np

def map_events_to_rows(available_at_ns, decision_at_ns):
    """Map only in-window events to first decision row at/after availability."""
    events=np.asarray(available_at_ns,dtype=np.int64); grid=np.asarray(decision_at_ns,dtype=np.int64)
    if grid.size == 0: return np.empty(0,np.int64)
    keep=(events>=grid[0]) & (events<=grid[-1])
    events=events[keep]
    rows=np.searchsorted(grid,events,side='left')
    return rows[(rows>=0)&(rows<grid.size)]

def target_window_indices(close_time_ns, decision_ns, horizon_ns):
    t=np.asarray(close_time_ns,dtype=np.int64); start=int(decision_ns); end=start+int(horizon_ns)
    return np.flatnonzero((t>start)&(t<=end))
