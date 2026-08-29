# REVERSAL_SIGNAL_EVENT_STUDY_V1

WIP=REVERSAL-SIGNAL-EVENT-STUDY-1  
STUDY_VERSION=REVERSAL_SIGNAL_EVENT_STUDY_V1  
OOS_OPENED=NO

## Dual analyses

1. **Pivot-centered** — first post-C directional signal delay, distance, remaining wave, MAE/MFE (where computed).
2. **Continuous timeline** — all causal signals over partition history, then retrospective match → unmatched = false positives.

## Matching

- Expected direction: HIGH→DOWN, LOW→UP
- Post-C match: `true_pivot_time ≤ signal < next_pivot_time` and delay ≤ max(decision_tf)
- First qualifying signal per (candidate, event) = MATCHED_POST_C; later = REPEAT_POST_C
- Pre-C warnings separate; do not count as successful WHEN
- Causal ledgers contain **no** true-C fields

## Partitions

| Partition | Span |
|---|---|
| DISCOVERY | 2019-05-12 → 2022-06-10 |
| VALIDATION | 2022-06-10 → 2023-06-20 |
| OOS | locked |

## Verdict

WHEN_SIGNAL_WEAK — real directional event association exists, but validation-stable candidates do not materially beat simple price-only baselines on the joint delay / false-positive tradeoff.
