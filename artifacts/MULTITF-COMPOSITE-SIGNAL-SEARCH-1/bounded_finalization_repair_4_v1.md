# COMPOSITE-BOUNDED-FINALIZATION-REPAIR-4

BASE_REPAIR_COMMIT: `d7916ee9c9a0dcdb5e9bed6400d7ab253948f5f4`  
SPEC_FREEZE_COMMIT: `476927817e21ef6869261a0114b27864fdf2d789`

## Scope

Execution/finalization plumbing only. No methodology change, no OOS, no real 200829 run.

## Delivered

1. Canonical class name `INCREMENTAL_SELECTIVE` (criteria unchanged; `SELECTIVE_THRESHOLD_CHANGED=NO`)
2. Full-completion finalization gate (fail closed unless 200829 complete)
3. `COMPOSITE_STREAM_SHA256` on every result row (compact int64)
4. Disk-backed survivor streams (`composite_survivor_streams_v1/`)
5. Bounded part assembly → `composite_results_all_v1.*` + fold CSV
6. Exact dedup by stream SHA
7. Near-redundancy Jaccard ≥0.95 blockwise by (direction, decision_tf) with frozen representative rule
8. Raw + model survivor banks + hashes
9. Summaries, execution report, low-TF T5 sections, model handoff
10. `COMPOSITE_FDR_STATUS=NOT_USED`
11. Finalizer dry test: 500 results / 2000 folds → PASS
12. Runtime projection (~15 cand/min → ~223 hours) — operational only

## Hard stop

`READY_FOR_FULL_COMPOSITE_EXECUTION_REVIEW=YES`  
Real full composite search was **not** started.
