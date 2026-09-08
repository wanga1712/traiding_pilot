#!/usr/bin/env python3
from pathlib import Path
from crypto_trading_bot.research_v2.composite_signal_search.stream_store import (
    AtomicStreamStore,
    materialize_shards_from_pickle,
)

art = Path("/var/tmp/traiding_pilot_ui_workspace/artifacts/MULTITF-COMPOSITE-SIGNAL-SEARCH-1")
man = materialize_shards_from_pickle(artifact_root=art, force=True)
print("shards", man["n_streams"], "source_bytes", man["source_pickle_bytes"])
store = AtomicStreamStore(art, max_active=5)
print("len", len(store), "active", store.active_count)
cid = next(store.ids())
s = store.get(cid)
print("sample", s.candidate_id, s.n_signals, s.available_at_ns.dtype)
store.release()
print("active_after_release", store.active_count)
