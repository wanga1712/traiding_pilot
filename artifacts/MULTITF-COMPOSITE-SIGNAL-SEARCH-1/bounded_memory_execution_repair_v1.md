# COMPOSITE-BOUNDED-MEMORY-EXECUTION-REPAIR-1

## Status
STOPPED after bounded-memory smoke. Full composite search was **not** launched.

## Stop / preserve
- `CURRENT_COMPOSITE_EXECUTION_STOPPED=YES` (systemd disabled + stopped; no OOM loop)
- `ATOMIC_CHECKPOINT_PRESERVED=YES` (`582/582`)
- Atomic streams converted to disk shards without regenerating signals

## Root cause
See `composite_memory_root_cause_v1.json`.
- `OOM_PREVIOUS_RSS_APPROX_GB=26`
- `ROOT_CAUSE=E` (combination): full 582-stream pickle residency + `expand_all_templates` retaining all composite signal arrays + all-TF bars + unbounded result lists / DataFrame copies

## Repair implementation
- Lazy per-id `AtomicStreamStore` (`atomic_streams_shards_v1/`, LRU ≤5)
- Compact int64 AVAILABLE_AT + searchsorted context timelines
- Deterministic composite definition generator (no full list in RAM)
- Incremental parquet flush (batch ≤100) + composite checkpoint every 50
- Application RSS guard at 9 GiB
- Systemd: `MemoryHigh=10G`, `MemoryMax=12G`, `Restart=no`
- Near-redundancy Jaccard blockwise by TF/direction/family

## Smoke acceptance
From `composite_memory_smoke_acceptance_v1.json`:
- candidates evaluated: **120**
- peak RSS: **~0.307 GiB**
- RSS growth first→last half: **~-0.011 GiB**
- `BOUNDED_MEMORY_SMOKE=PASS`

## Parity
- Context compact vs object timeline: unit-checked PASS
- Definition generator IDs vs expand combinatorics: unit-checked PASS
- Evaluation/classification call path unchanged (`evaluate_signals_window` / `classify_composite`)

## Hard stop
`READY_FOR_BOUNDED_MEMORY_EXECUTION_REVIEW=YES` — do not start full compose until independent review.
