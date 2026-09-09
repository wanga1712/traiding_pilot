# COMPOSITE-PERFORMANCE-AND-FINALIZER-INTEGRITY-REPAIR-5

Execution/performance plumbing only. Frozen research methodology unchanged.

## Changes

1. **Survivor persistence** — append-only metadata parts (`part-NNNNNN.jsonl`, batch ≤100) + per-composite `.npz`/`.meta.json`. No global manifest rewrite per survivor. Final manifest assembled once.
2. **Resume safety** — exact-match idempotent reuse; mismatch fail-closed; crash-before-checkpoint covered by unit test.
3. **Trigger caches** — aggregate + fold metric caches keyed by trigger/direction(/fold); bounded signal LRU ≤32.
4. **Near-redundancy** — lexical tie ascending; cardinality prefilter before exact Jaccard; no global all-pairs matrix.
5. **Finalizer CLI** — `--phase finalize-bounded` calls `run_finalization(..., allow_partial_test=False)` with frozen authority SHA gate.
6. **S13 evidence** — finalizer memory stress (≥50k/≥200k) + ≥1000 real compose smoke + ≥100 T1–T6 parity.

## Hard stop

Do **not** start the real 200829 full composite search in this WIP.
OOS remains locked.
