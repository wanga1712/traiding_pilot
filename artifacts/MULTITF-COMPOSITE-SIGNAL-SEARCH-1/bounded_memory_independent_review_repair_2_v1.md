# COMPOSITE-BOUNDED-MEMORY-INDEPENDENT-REVIEW-REPAIR-2

WIP: MULTITF-COMPOSITE-SIGNAL-SEARCH-1  
BASE_REPAIR_COMMIT: `ea53329c1479b8f904f0e83c3b370c71092a4a49`  
SPEC_FREEZE_COMMIT: `476927817e21ef6869261a0114b27864fdf2d789`  
ATOMIC_CHECKPOINT_COUNT: 582  

## Purpose

Close three independent-review blockers on the bounded-memory execution repair without rerunning atomic replay, changing frozen methodology, opening OOS, or starting full composite search.

## Fixes

### 1. Append-only result writer

- Removed read-all + concat + rewrite flush behavior.
- Added `result_parts.AppendOnlyPartWriter` writing `part-NNNNNN.parquet` under:
  - `composite_results_partial_parts_v1/`
  - `composite_fold_partial_parts_v1/`
- Checkpoint stores `next_result_part` / `next_fold_part`.
- Flush never reads prior parts.
- Unit test `test_flush_does_not_read_previous_parts` proves flush N does not call `pd.read_parquet`.

Flags: `RESULT_WRITER_APPEND_ONLY=YES`, `PREVIOUS_RESULT_ROWS_READ_DURING_FLUSH=NO`, `RESULT_MEMORY_COMPLEXITY=O(CURRENT_BATCH)`.

### 2. Stratified bounded-memory smoke

- Deterministic stratified selection across T1–T6 (streaming; not first-N global).
- Executed on S13 via normal bounded path with RSS every 5s.

Result:

- count=190
- by template: T1=25, T2=25, T3=25, T4=30, T5=60, T6=25
- 5m=30, 15m=30, T4 triple=30
- peak RSS=1.238 GB, growth=0.704 GB
- no guard stop
- `STRATIFIED_BOUNDED_MEMORY_SMOKE=PASS`

### 3. Real old/new parity

- Corpus n=70 (>=10 per T1–T6; >=10 5m; >=10 15m; >=10 T4 triple).
- Reference: pre-bounded `compose_signals` + `_timeline_for_config`.
- New: `compose_signals_from_compact` streaming path.
- Compared timestamps/signal counts (zero tolerance), metrics (1e-12), and class inputs including `PRECISION_DELTA_VS_PRICE_BASELINE`.

Result: all three parity gates PASS. Artifacts:

- `composite_old_new_parity_v1.csv`
- `composite_old_new_parity_summary_v1.json`

### 4. Result writer stress

- 20,000 synthetic rows through same append-only writer.
- peak=0.114 GB, growth≈0.00015 GB → `RESULT_WRITER_STRESS=PASS`

### 5. Shard integrity gate

- Full compose requires `atomic_streams_shard_manifest_v1.json` + all referenced shards.
- No silent monolithic pickle fallback (`FULL_COMPOSE_MONOLITHIC_PICKLE_FALLBACK=NO`).
- Integrity verified for 582 streams: `SHARD_INTEGRITY_GATE=PASS`

### 6. Containment retained

Effective S13 systemd (`systemctl show`):

- `Restart=no`
- `MemoryHigh=10737418240` (10G)
- `MemoryMax=12884901888` (12G)
- Application guard threshold remains 9 GB.

### 7. Frozen authority

Byte SHA matches freeze manifest for all four authorities (`repair2_freeze_sha_check_v1.json`).

`OOS_OPENED=NO`, `OOS_ACCESS_COUNT=0`.

## Hard stop

`READY_FOR_FULL_COMPOSITE_EXECUTION_REVIEW=YES`

Full composite search was **not** started.
