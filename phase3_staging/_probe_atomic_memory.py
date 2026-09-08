#!/usr/bin/env python3
"""Probe atomic stream cache sizes for memory root-cause audit (S13)."""
from __future__ import annotations

import json
import pickle
import resource
import sys
import time
from pathlib import Path

art = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
t0 = time.time()
with (art / "atomic_streams_cache_v1.pkl").open("rb") as fh:
    streams = pickle.load(fh)
rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
n_events = sum(len(v.get("events") or []) for v in streams.values())
n_avail = sum(len(v.get("available_at") or []) for v in streams.values())
sample = next(iter(streams.values()))
reps = json.loads((art / "atomic_representative_bank_v1.json").read_text(encoding="utf-8"))
out = {
    "n_streams": len(streams),
    "pickle_bytes": (art / "atomic_streams_cache_v1.pkl").stat().st_size,
    "deserialized_maxrss_kb": rss_kb,
    "deserialized_maxrss_gb": round(rss_kb / (1024 * 1024), 3),
    "total_events": n_events,
    "total_available_at_strings": n_avail,
    "sample_keys": sorted(sample.keys()),
    "n_representatives": reps.get("n_representatives"),
    "load_sec": round(time.time() - t0, 2),
}
print(json.dumps(out, indent=2))
(art / "_memory_probe_atomic_v1.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
