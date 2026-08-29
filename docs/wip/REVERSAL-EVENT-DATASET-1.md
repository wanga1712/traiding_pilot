# WIP=REVERSAL-EVENT-DATASET-1

STATUS=REVIEW

STARTED_AT=2026-08-29
REVIEW_AT=2026-08-29

## Goal

Transform frozen `WAVE_DATASET_V1` pivots into leakage-safe canonical reversal-event research dataset `REVERSAL_EVENT_DATASET_V1`.

Laboratory only — no indicators, volume interpretation, predictors, ML, or PnL.

## Results (implementation PASS → user review)

```
PREVIOUS_WIP=WAVE-DATASET-FREEZE-1 STATUS=CLOSED
WAVE_ENGINE_VERSION=WAVE_ENGINE_V1
WAVE_DATASET_VERSION=WAVE_DATASET_V1
WAVE_DATASET_V1_UNCHANGED=YES
EVENT_DATASET_VERSION=REVERSAL_EVENT_DATASET_V1

TOTAL_EVENTS=9992
HIGH_EVENTS=4997
LOW_EVENTS=4995

DISCOVERY_EVENTS=5301
VALIDATION_EVENTS=2076
OOS_EVENTS=2586
PARTITION_CROSS_PURGED=19
NO_OUTCOME=10

EVENTS_WITH_COMPLETE_5M_CONTEXT=9970
EVENTS_WITH_COMPLETE_15M_CONTEXT=9631
EVENTS_WITH_COMPLETE_1H_CONTEXT=9007
EVENTS_WITH_COMPLETE_4H_CONTEXT=5519
CONTEXT_COMPLETE_ALL=5489

PARTITION_METHOD=chronological_time_span_60_20_20
EMBARGO_METHOD=purge_if_next_pivot_crosses_partition_boundary

SCHEMA_REGISTRY_CREATED=YES
ANTI_LEAKAGE_API=get_event_history(+closed_candle higher-TF filter)
ANTI_LEAKAGE_TESTS=PASS
UNFINISHED_HIGHER_TF_BAR_TEST=PASS
DATA_QUALITY=PASS
```

## Artifacts

S13: `/var/tmp/traiding_pilot_ui_workspace/reversal_event_dataset_v1/`  
Local manifests/samples: `artifacts/REVERSAL-EVENT-DATASET-1/`

Immutable marker: `REVERSAL_EVENT_DATASET_V1_IMMUTABLE.txt`

Code: `phase3_staging/crypto_trading_bot/research_v2/reversal_events/`

## Acceptance gate

| Gate | Result |
|---|---|
| WAVE_DATASET_V1 unchanged | PASS (pivots sha256 `df2c3a96…`) |
| Event identities reproducible | PASS |
| Multi-TF context 5m/15m/1H/4H | PASS |
| Schema registry | PASS |
| Causal vs retrospective separation | PASS |
| Anti-leakage API tested | PASS |
| Unfinished higher-TF bar leakage prevented | PASS |
| Chronological partitions + outcome purge | PASS |
| Data-quality validation | PASS |
| Manifest | PASS |

## Do not yet

Do **not** activate `REVERSAL-INDICATOR-ENGINE-1` until this WIP is accepted → CLOSED.

## NEXT_WIP (after CLOSED)

`REVERSAL-INDICATOR-ENGINE-1`
