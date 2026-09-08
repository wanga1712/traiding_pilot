# COMPOSITE-FULL-EXECUTION-INTEGRITY-REPAIR-3

WIP: MULTITF-COMPOSITE-SIGNAL-SEARCH-1  
BASE_REPAIR_COMMIT: `2951216533575b3d6b13d515de632ad6d62714b4`  
SPEC_FREEZE_COMMIT: `476927817e21ef6869261a0114b27864fdf2d789`

## Purpose

Close independent-review blockers on full-execution integrity without changing frozen methodology, rerunning atomic replay, opening OOS, or starting the real full composite search.

## Fixes

1. **True streaming definition generator** — removed `list(iter_all_template_definitions(...))`. Full path uses the iterator directly.
2. **Isolated test runtimes** — smoke/parity/stress write under `_memory_smoke_runtime/`, `_full_path_smoke_runtime/`, `_writer_stress_runtime/` etc., never production checkpoint/parts.
3. **Cleaned Repair-2 smoke contamination on S13** — production checkpoint preserved as `composite_execution_checkpoint_repair2_smoke_v1.json`; parts moved to audit; production compose state cleaned; atomic 582 untouched.
4. **Enumeration authority** — `composite_enumeration_authority_v1.json` with streamed SHA256 over ordered IDs (`TOTAL=200829`).
5. **O(1) checkpoint** — full mode uses `next_candidate_index` / `completed_count` / `last_completed_composite_id` only (no completed-ID set/list).
6. **Crash-safe parts** — orphan parts with index ≥ committed `next_*_part` quarantined on resume.
7. **Shard authority** — manifest IDs must equal frozen atomic bank 582; dtype/length checks; `SHARD_CANDIDATE_SET_MATCH=PASS`.
8. **Full-path dry smoke** — real global generator, `max_candidates=300`, no `definitions=`; resume 150→300 parity PASS; peak RSS ≈0.324 GiB.

## Hard stop

`READY_FOR_FULL_COMPOSITE_EXECUTION_REVIEW=YES`  
Real full composite search was **not** started.
