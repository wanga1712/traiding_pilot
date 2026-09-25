# PROBABILITY-MODEL-BAKEOFF-1

Status: **REVIEW**

Parent dataset authority: `201efd1e1b98056d526baced8042a51887c0218e`

Result evidence commit: `860c4683bd93593e204656a903c29776b0e75225`

Runtime: S13, completed 2026-09-25 09:48:34 MSK

## Decision

The frozen DEVELOPMENT walk-forward bakeoff completed all 252 expected
model/fold runs. Ten of 84 model/feature-set/horizon configurations satisfy the
predeclared `SUPPORTED` rule. At most one model was then selected per horizon.

Two DEVELOPMENT candidates survive:

| Horizon | Selected candidate | Log loss | Brier | ECE | Delta log loss vs prior | Delta Brier vs prior | Improved folds |
|---:|---|---:|---:|---:|---:|---:|---:|
| 30m | CatBoost / FS_FULL | 0.690347 | 0.248602 | 0.011725 | -0.002794 | -0.001395 | 3/3 |
| 60m | CatBoost / FS_FULL | 0.691667 | 0.249259 | 0.014760 | -0.001553 | -0.000778 | 3/3 |

No candidate is selected for 120m, 240m, 480m, 720m, or 1440m.

The improvement over the chronological training-prior baseline is consistent
but small. Per-fold ROC AUC is 0.534–0.550 for 30m and 0.530–0.543 for 60m;
balanced accuracy is 0.523–0.534 and 0.517–0.526 respectively. This is weak
DEVELOPMENT evidence of directional probability information. It is not an
independent generalization result and is not evidence of profitability.

## Scope and integrity

| Check | Result |
|---|---|
| Dataset authority hashes | PASS |
| Frozen targets and configs | PASS |
| Engineering smoke and serialization parity | PASS |
| Expected/completed model-fold runs | 252 / 252 |
| Preprocessing future-row leakage | 0 |
| Deterministic sample reproducibility | PASS |
| Selected models frozen and reloadable | PASS |
| Final model lineage | COMPLETE |
| OOS access count | 0 |
| PnL or execution test | NOT PERFORMED |

`DEVELOPMENT_REUSE_BIAS=YES` and
`DEVELOPMENT_MODEL_METRICS_INDEPENDENT_OOS=NO`. The atomic and composite
families were researched on this same DEVELOPMENT corpus. The independent
post-2023-06-20 period remains unopened.

## Dataset and targets

- Rows: 143,779.
- Chronological folds: 35,868 / 35,930 / 35,980 / 36,001 rows.
- Horizons: 30, 60, 120, 240, 480, 720, and 1440 minutes.
- Feature counts: FS_DENSE=15, FS_DENSE_ATOMIC=299,
  FS_DENSE_COMPOSITE=5,493, FS_FULL=5,777.
- Zero-return exclusions by horizon: 313 / 241 / 181 / 132 / 71 / 66 / 53.
- Censored exclusions by horizon: 52 / 96 / 181 / 349 / 685 / 1,021 / 2,029.
- Logistic L2, LightGBM, and CatBoost were all available and evaluated with
  their frozen configurations.

## Candidate classification

Across 84 non-baseline configurations:

- `SUPPORTED`: 10.
- `WEAK`: 0.
- `NOT_SUPPORTED`: 74.

DEVELOPMENT-only ablation evidence shows incremental information from atomic,
composite, and full feature families for some tree-model/horizon combinations.
The stable evidence is concentrated at 30m and 60m. Longer horizons do not beat
the prior baseline reliably and are not carried forward.

## Calibration

Chronological Platt calibration was evaluated without using future OOF rows:
WFV_2 used WFV_1 predictions, and WFV_3 used WFV_1+WFV_2 predictions.
Calibration worsened both log loss and Brier on every evaluable fold:

| Horizon | Fold | Raw log loss | Calibrated log loss | Raw Brier | Calibrated Brier |
|---:|---|---:|---:|---:|---:|
| 30m | WFV_2 | 0.691780 | 0.692627 | 0.249316 | 0.249737 |
| 30m | WFV_3 | 0.689618 | 0.689890 | 0.248240 | 0.248375 |
| 60m | WFV_2 | 0.692416 | 0.693745 | 0.249630 | 0.250295 |
| 60m | WFV_3 | 0.690735 | 0.691329 | 0.248796 | 0.249092 |

Final DEVELOPMENT calibrators are preserved for reproducibility, but the frozen
probability variant proposed for the independent OOS exam is **RAW**.

## Frozen models

| Horizon | Model SHA256 | Bytes | Training rows |
|---:|---|---:|---:|
| 30m | `79db5021d666a5dd9b79da34c85293809837f924c4b571585778163821025959` | 391,042 | 143,414 |
| 60m | `2cba813ddf434047a4b5d5a0517fc95873bc0223145d73961093263bfb84e5e2` | 391,018 | 143,442 |

Final model manifest SHA256:
`d13822629acbe9a7d8d725bf2753b5eaab69b2c8a5950700081fc64aad904305`.

The canonical large artifacts remain on S13 under:

`/var/tmp/traiding_pilot_ui_workspace/artifacts/PROBABILITY-MODEL-BAKEOFF-1/`

The 100,542,955-byte OOF prediction table has SHA256
`dc3c90f88513a5023299ae6b19d9b8cef102c65d0cfcc402a153cf44f698b862`.
Small and medium evidence is committed under
`docs/wip/PROBABILITY-MODEL-BAKEOFF-1/results/`.

## Review recommendation

Accept the bakeoff as a completed DEVELOPMENT experiment and carry only the
30m and 60m CatBoost/FS_FULL raw-probability candidates into the next,
separately authorized `INDEPENDENT-OOS-MODEL-EVALUATION-1` WIP. The OOS exam
must remain a one-shot evaluation with no candidate retuning. Execution, fees,
and the “$10” result remain out of scope until predictive OOS evidence is
reviewed.

## Required return

```text
WIP=PROBABILITY-MODEL-BAKEOFF-1
MODE=DEVELOPMENT-WALKFORWARD-DIRECTION-PROBABILITY-1
PARENT_DATASET_AUTHORITY=201efd1e1b98056d526baced8042a51887c0218e
DATASET_WIP_STATUS=CLOSED
MODEL_WIP_STATUS=REVIEW
DATASET_AUTHORITY_GATE=PASS
DEVELOPMENT_REUSE_BIAS=YES
DEVELOPMENT_MODEL_METRICS_INDEPENDENT_OOS=NO
ROWS=143779
FOLD_1_ROWS=35868
FOLD_2_ROWS=35930
FOLD_3_ROWS=35980
FOLD_4_ROWS=36001
TARGET_HORIZONS=30m,60m,120m,240m,480m,720m,1440m
ZERO_RETURN_COUNTS=313,241,181,132,71,66,53
CENSORED_COUNTS=52,96,181,349,685,1021,2029
FEATURE_SET_DENSE_COUNT=15
FEATURE_SET_DENSE_ATOMIC_COUNT=299
FEATURE_SET_DENSE_COMPOSITE_COUNT=5493
FEATURE_SET_FULL_COUNT=5777
LOGISTIC_AVAILABLE=YES
LIGHTGBM_AVAILABLE=YES
CATBOOST_AVAILABLE=YES
MODEL_SMOKE_GATE=PASS
EXPECTED_MODEL_FOLD_RUNS=252
COMPLETED_MODEL_FOLD_RUNS=252
SUPPORTED_CANDIDATE_COUNT=10
WEAK_CANDIDATE_COUNT=0
NOT_SUPPORTED_CANDIDATE_COUNT=74
ATOMIC_INCREMENTAL_INFORMATION=SUPPORTED_DEVELOPMENT_ONLY
COMPOSITE_INCREMENTAL_INFORMATION=SUPPORTED_DEVELOPMENT_ONLY
FULL_INCREMENTAL_INFORMATION=SUPPORTED_DEVELOPMENT_ONLY
SELECTED_30M_MODEL=CATBOOST|FS_FULL|RAW
SELECTED_1H_MODEL=CATBOOST|FS_FULL|RAW
SELECTED_2H_MODEL=NO
SELECTED_4H_MODEL=NO
SELECTED_8H_MODEL=NO
SELECTED_12H_MODEL=NO
SELECTED_24H_MODEL=NO
CALIBRATION_STATUS=PASS_EVALUATED_NOT_SELECTED
PREPROCESSING_FUTURE_ROW_LEAKAGE_COUNT=0
MODEL_SAMPLE_REPRODUCIBLE=PASS
OOS_OPENED=NO
OOS_ACCESS_COUNT=0
PNL_TESTED=NO
EXECUTION_TESTED=NO
FINAL_MODEL_MANIFEST_HASH=d13822629acbe9a7d8d725bf2753b5eaab69b2c8a5950700081fc64aad904305
RESULT_COMMIT=860c4683bd93593e204656a903c29776b0e75225
PUSHED_TO_GITHUB=NO
ROADMAP_STATUS_AFTER=REVIEW
NEXT_WIP=INDEPENDENT-OOS-MODEL-EVALUATION-1
NEXT_WIP_STARTED=NO
```
