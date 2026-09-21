# Current research state V1

Verified 2026-09-21 for `MULTITF-COMPOSITE-SIGNAL-SEARCH-1`.

The 200,829-candidate DEVELOPMENT compose is complete. The checkpoint has
`completed_count=200829`, `next_candidate_index=200829`, the expected enumeration
SHA `397533c24eb48bd7e0c1f18dedc4d94393c5965107cc6165eb59ecad592f7b3e`, and
`OOS_OPENED=NO`, `OOS_ACCESS_COUNT=0`. Result integrity is PASS: 200,829 unique
composite rows and 803,316 fold rows, exactly four fold rows per composite, with
zero duplicate keys or missing candidates.

Production `finalize-bounded` ran only after those gates passed. It exited 0 at
2026-09-21 08:02:13 MSK after 11:39.18 wall time. Peak RSS was 1,757,652 KiB
(1.676 GiB), below the dedicated 10G/12G finalizer limits.

Class accounting:

| Class | Count |
|---|---:|
| INCREMENTAL_BALANCED | 11,523 |
| INCREMENTAL_SELECTIVE | 934 |
| WEAK_INCREMENTAL | 49,261 |
| NO_INCREMENTAL_EDGE | 139,108 |
| INSUFFICIENT | 3 |

The legacy `SELECTIVE` class count is zero. Raw survivors: 12,457, with set hash
`dda22dcdc757aa01e899fcd6bb0f97bb4cbfa8664ff867600614013d7952ca27`. After exact
and EVENT_STREAM_JACCARD near-redundancy deduplication at threshold 0.95, the
model survivor bank has 5,478 entries with hash
`9b7a2f04adc7234b75a4d4c20e1998be6dfed13a5ed86ae49cc4b96cee4027e9`.
There were 15,655 exact duplicate rows in 11,949 clusters. All 12,457 survivor
streams were audited: hash mismatch 0, signal-count mismatch 0, manifest missing
shards 0.

The development verdict is `COMPOSITE_INCREMENTAL_INFORMATION_SUPPORTED`.
`DEVELOPMENT_ONLY=YES`, `MODEL_FEATURE_HANDOFF_READY=YES`, with 284 atomic and
5,478 composite model features. This is not an OOS, PnL, or profitability claim.

Template counts are recorded in `finalizer_execution_evidence_v1.json` and the
canonical execution report. The WIP is `REVIEW`; independent review/user acceptance
is pending. The next WIP is `PROBABILITY-MODEL-TRAINING-DATASET-1`, status
`PLANNED`. Do not activate it automatically.

The finished compose service remains as audit evidence but is disabled after
completion. Do not delete its unit, logs, checkpoint, parts, shards, or publication
manifest. Do not rerun compose for this WIP.
