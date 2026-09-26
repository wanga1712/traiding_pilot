# INDEPENDENT-OOS-MODEL-EVALUATION-1

Status: **REVIEW**

Mode: `ONE-SHOT-FROZEN-PROBABILITY-OOS-1`

Parent model authority: `860c4683bd93593e204656a903c29776b0e75225`

Parent dataset authority: `201efd1e1b98056d526baced8042a51887c0218e`

Result commit: `5e498326d0f0ca747e042f29e4bf681cb7efb8e6`

## Result

The frozen 30m and 60m CatBoost/FS_FULL RAW models both satisfy the
predeclared `OOS_SUPPORTED` rule on the first independent OOS exam. Both beat
their frozen DEVELOPMENT prior on full-period log loss and Brier score, and
both improve log loss in all three frozen chronological blocks. The measured
improvements are small and are evidence of probability generalization, not a
profitability result.

| Horizon | Valid rows | Log loss | Prior log loss | Delta | Brier | Prior Brier | Delta | ROC AUC | ECE | Class |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 30m | 109105 | 0.6907674623 | 0.6930493283 | -0.0022818660 | 0.2488109612 | 0.2499510751 | -0.0011401139 | 0.5397677179 | 0.0053349749 | `OOS_SUPPORTED` |
| 60m | 109158 | 0.6917403281 | 0.6930171190 | -0.0012767909 | 0.2492966107 | 0.2499349711 | -0.0006383604 | 0.5313961126 | 0.0082584829 | `OOS_SUPPORTED` |

The frozen DEVELOPMENT priors were `0.5050204303624471` for 30m and
`0.5051658510059815` for 60m. The observed OOS positive rates were
`0.5073827963887998` and `0.5088770406200187`, respectively; they were not
used to construct the baselines.

## Temporal stability and uncertainty

The log-loss deltas versus the frozen DEVELOPMENT prior were negative in every
predeclared block:

| Horizon | Block 1 | Block 2 | Block 3 |
|---|---:|---:|---:|
| 30m | -0.0032816928 | -0.0017833539 | -0.0017808539 |
| 60m | -0.0023903547 | -0.0007383487 | -0.0007018539 |

The fixed 7-calendar-day block bootstrap used 2000 repetitions and seed
`20260925`. Its 95% intervals were:

| Horizon | Delta log-loss 95% CI | Delta Brier 95% CI |
|---|---|---|
| 30m | [-0.0026615196, -0.0018982998] | [-0.0013286157, -0.0009499577] |
| 60m | [-0.0016705639, -0.0008666906] | [-0.0008339344, -0.0004333360] |

Both intervals remain below zero. These intervals are diagnostics and did not
change the frozen classification rule.

## Frozen exam and integrity

- OOS period: `2023-06-20T06:14:59.999999Z` through
  `2026-07-31T23:59:59.999999Z`.
- Canonical OOS rows: `109224`; valid classification rows: `109105` for 30m
  and `109158` for 60m.
- OOS opened: `YES`; logical evaluation run count: `1`; exam compromised:
  `NO`.
- Model hash gates: 30m `PASS`; 60m `PASS`.
- Feature counts: 15 dense + 284 atomic + 5478 composite = 5777 total.
- Feature schema, order, and frozen feature-set hash: `PASS`.
- Features available after decision: `0`; target-feature leakage: `0`.
- Target outcomes: 218442 complete, 0 gap-censored, 6 boundary-censored.
- Model retrains: `0`; calibrator: `NO`; OOS model selections: `0`; OOS
  hyperparameter tuning operations: `0`.
- PnL tested: `NO`; execution tested: `NO`.

The initial process stopped during dense feature materialization because the
shared bar normalizer omitted the already-frozen `trade_count` column. No
predictions or metrics existed or had been observed. The adapter was repaired
to read that column from the frozen canonical resampled parquet, with no model,
feature definition, order, target, baseline, methodology, or OOS-boundary
change. Deterministic pre-metrics checkpoints were then reused within the same
logical run. The final execution used eight atomic workers and reused 206
completed atomic checkpoints; GPU was not used because indicator/event replay
was the runtime bottleneck. The final process exited successfully in
5239.903 seconds, with runner-reported peak RSS 1.958 GiB and systemd-observed
unit peak memory 5.2 GiB.

## Evidence

Small and medium evidence is preserved in
`docs/wip/INDEPENDENT-OOS-MODEL-EVALUATION-1/results/`. The frozen spec and
period/source manifests are in `spec_freeze/`. The complete runtime artifact
root remains:

`/var/tmp/traiding_pilot_ui_workspace/artifacts/INDEPENDENT-OOS-MODEL-EVALUATION-1/`

Large evidence retained on S13:

| Artifact | Rows / shape | Bytes | SHA256 |
|---|---|---:|---|
| `oos_row_index_v1.parquet` | 109224 rows | 2467339 | `c66141359396fe391ee0c503663ccabb3a913fd8318b0384fa2c4e1b7f692fc2` |
| `oos_features_dense_v1.parquet` | 109224 × 15 | 13914765 | `9c89581279162f6065e0126664eb6372bb64d87959322e6e12ecf5d9eba19a9b` |
| `oos_atomic_feature_matrix_v1.npz` | 109224 × 284 | 1058126 | `1e31dde58f2f54f5e16251aeafa8e7e5c6d9e4ac873384b8939f0e5a332c8aaf` |
| `oos_composite_feature_matrix_v1.npz` | 109224 × 5478 | 13110130 | `8a61e5957e96406bae5e1f420d44de2f43664a3a80f96093a7d82d36afc253b6` |
| `oos_targets_v1.parquet` | 109224 rows | 2889543 | `4ff1a172f79fb5535881309b123199c51029a230029c9ece77cb6c03f1a50b57` |
| `oos_predictions_v1.parquet` | 109224 rows | 3763199 | `e9dd9dca6c9c9ed712477fff06bbeeaf565c97a05b71fd8437cb271dec696a4b` |

The integrity report status is `PASS`. Both horizons may be carried forward
separately into the later execution simulator. That next WIP remains unstarted
pending review and acceptance of this result.
