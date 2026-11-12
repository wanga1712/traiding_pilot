# WIP=TRADING-PILOT-ACTION-LEARNING-AUDIT-1

STATUS=REVIEW
PHASE=REVIEW
STARTED_AT=2026-11-12
MODE=AUDIT / READ-ONLY / NO TRAINING
MODEL_RETRAINING=NO
QWEN_FINE_TUNING=NO
LIVE_TRADING=NO
OOS_OPENED=NO

## Goal

Determine whether the completed GPU policy actually learned trading actions, or
merely reproduced a weak prior algorithm. Audit action representation, target
quality, CatBoost feature evidence, and Qwen decision information/permissions.

Do not launch another threshold-search run.
Do not train new CatBoost models.
Do not fine-tune Qwen or run LoRA/QLoRA.
Do not modify frozen models, datasets, Qwen requests/responses, OOS, or
confirmation sets.

## Audit tasks

1. Inventory the observed action distribution in the training data.
2. Determine why `CLOSE_HEDGE` is absent.
3. Assess label quality for entry, hold, averaging, and exit actions.
4. Identify which features are used by CatBoost and whether they have any
   validated predictive advantage.
5. Verify exactly when Qwen receives information and which actions the adapter
   and policy permit in each state.
6. Specify a causal multi-action counterfactual learning scheme that compares
   alternative outcomes from the same market/portfolio state without changing
   frozen results.

## Governance

- Previous WIP remains `REVIEW`; do not close or rewrite it.
- No real orders, deployment, restart, or API trading keys.
- S7 remains read-only.
- S13 is accessed only for existing isolated research artifacts.
- Frozen CatBoost, Qwen, datasets, predictions, and manifests are immutable.
- One new audit branch is used; no next WIP is started automatically.

## Findings

### Action coverage

The 4-hour management sample contains 17,012 labeled states:

| Action | TRAIN | SELECTION | RUN 2 | Total |
|---|---:|---:|---:|---:|
| HOLD | 1,113 | 1,315 | 3,892 | 6,320 |
| OPEN_HEDGE | 165 | 45 | 0 | 210 |
| CLOSE_HEDGE | 716 | 1,005 | 2,552 | 4,273 |
| AVERAGE_PRIMARY | 1,051 | 840 | 0 | 1,891 |
| REDUCE_POSITION | 0 | 0 | 0 | 0 |
| EXIT | 1,087 | 1,099 | 2,132 | 4,318 |

The premise that `CLOSE_HEDGE` is absent is incorrect. It is present in TRAIN
and SELECTION. The missing action is `REDUCE_POSITION`.

### Why CLOSE_HEDGE does not reach execution

- 8,656 sampled states have an open hedge.
- `CLOSE_HEDGE` is feasible in all of them and is the best counterfactual action
  in 4,273 states.
- `utility_CLOSE_HEDGE` is never positive; it is the immediate close cost and
  has a median of -0.0661 USDT.
- The trained management model predicts `CLOSE_HEDGE` zero times on SELECTION,
  giving recall 0/1,005 despite its presence in training.
- The policy therefore never applies `CLOSE_HEDGE`.
- Qwen never received a hedge-open state: 103 requests were FLAT, one had a
  primary open, and zero had an open hedge. It could not compensate for the
  management model's failure.

The prior REVIEW statement that the five-class warning referred to missing
`CLOSE_HEDGE` is corrected here: the absent class was `REDUCE_POSITION`.

### Label quality

- Entry classes on SELECTION: 255 SKIP, 2,241 LONG, 1,724 SHORT.
- Entry accuracy is 49.91%.
- Entry logloss is 0.9218 versus 0.8714 for the class prior: the model is worse
  than a constant prior.
- Entry SKIP recall is 0%; all 255 SKIP cases are predicted as LONG or SHORT.
- Management logloss improves from the class-prior 1.4171 to 1.1044, so some
  probability structure exists.
- Management predicts only HOLD, OPEN_HEDGE, AVERAGE_PRIMARY, and EXIT on
  SELECTION.
- Management recall: HOLD 78.25%, AVERAGE_PRIMARY 68.57%, EXIT 33.58%,
  OPEN_HEDGE 2.22%, CLOSE_HEDGE 0%, REDUCE undefined.
- OPEN_HEDGE labels are weak: 77.1% of selected examples beat the second-best
  action by at most 0.05 USDT and 38.6% by at most 0.01 USDT.
- Median best-vs-second utility margins: HOLD 4.66, EXIT 7.98, CLOSE_HEDGE 0.95,
  AVERAGE_PRIMARY 1.68, OPEN_HEDGE 0.015 USDT.
- REDUCE_POSITION was feasible in all 17,012 states but never selected; its
  utility rule produces no training examples.
- Action utilities are simplified terminal comparisons, not full counterfactual
  branches through fills, funding, path risk, and subsequent state.

### CatBoost feature evidence

Entry feature importance is concentrated in trend/volatility 25.34%, portfolio
state 25.04%, volume/structure 20.71%, DNO 8.85%, DMA 7.55%, and MACD 7.17%.
Inverse predictors and the oscillator predictor contribute 0%.

Entry has no validated advantage: its SELECTION logloss is worse than the class
prior despite non-zero in-sample feature importance.

Management importance is 63.99% portfolio state, 20.05% other raw/context
features, and smaller market-family shares. It improves probability logloss but
fails action coverage.

The risk model has 70.68% portfolio-state importance and 18.64% DMA importance.
Of 200 selected features, 190 have zero importance. Its MAE is 0.02369 versus
0.02388 for the train-mean baseline and 0.03029 for zero; improvement over the
train mean is only 0.00019.

Feature importance measures model use, not causal or tradeable advantage.

### Qwen information boundary

- Inputs contain only decision time, 11 current market features, CatBoost
  probabilities/risk forecasts, portfolio state, and risk state.
- Forbidden future-target fields in request logs: 0.
- Adapter permits all nine actions.
- Policy permits entry actions only when FLAT; management actions only with a
  primary; OPEN_HEDGE only without a hedge; CLOSE_HEDGE only with a hedge;
  AVERAGE only below two additions.
- Actual actions: 85 OPEN_SHORT, 17 OPEN_LONG, 1 HOLD.
- Action changes versus CatBoost: 0.
- 103/104 Qwen requests were FLAT and none received an open hedge. The weekly
  trigger tests entry decisions far more often than position management.

## Recommended action-learning schema

1. Represent data as `state_id, action, feasible, horizon_outcome`.
2. Create one immutable causal state snapshot with market indicators, positions,
   margin, exposure, liquidation distance, costs, and remaining risk.
3. Branch every feasible action from the same state into the fixed execution
   simulator over 24/72/168 hours.
4. Record terminal PnL, MFE/MAE, drawdown, liquidation, risk-limit hit, costs,
   time-to-exit, and recovery time per branch.
5. Generate `REDUCE_POSITION` and `CLOSE_HEDGE` outcomes from the same state even
   if the prior controller never selected them.
6. Train action-value or ranking models on counterfactual outcomes with a
   feasibility mask; do not copy one best-action label from the prior path.
7. Keep ENTRY and POSITION_MANAGEMENT objectives separate.
8. Apply purge/embargo to complete forward outcome windows.
9. Let policy choose argmax expected utility; Risk Engine can veto.
10. Query Qwen only at PRIMARY/HEDGE/risk decision boundaries, not mostly FLAT
    weekly samples.

## Prioritized remediation

1. Correct the missing-action documentation: `REDUCE_POSITION`.
2. Build genuine same-state counterfactual action outcomes before more training.
3. Fix CLOSE_HEDGE/REDUCE coverage through ranking or utility learning.
4. Reassess entry labels and class balance; current entry model is worse than
   the prior.
5. Revalidate or prune zero-importance feature families.
6. Move Qwen to explicit hedge/permission states in a future WIP.

## REQUIRED RETURN

```text
WIP=TRADING-PILOT-ACTION-LEARNING-AUDIT-1
STATUS=REVIEW
ACTIONS_OBSERVED=HOLD_6320;OPEN_HEDGE_210;CLOSE_HEDGE_4273;AVERAGE_1891;REDUCE_0;EXIT_4318
CLOSE_HEDGE_COUNT=4273_TOTAL;716_TRAIN;1005_SELECTION
CLOSE_HEDGE_CAUSE=PRESENT_IN_DATA;MANAGEMENT_RECALL_0;QWEN_NEVER_SAW_HEDGE_OPEN
ENTRY_LABEL_QUALITY=ACCURACY_49.91%;LOGLOSS_0.9218_WORSE_THAN_PRIOR_0.8714;SKIP_RECALL_0
HOLD_LABEL_QUALITY=MODEL_RECALL_78.25%;MEDIAN_UTILITY_MARGIN_4.66
AVERAGE_LABEL_QUALITY=MODEL_RECALL_68.57%;MEDIAN_UTILITY_MARGIN_1.68
EXIT_LABEL_QUALITY=MODEL_RECALL_33.58%;MEDIAN_UTILITY_MARGIN_7.98
FEATURE_ADVANTAGE=ENTRY_NONE;RISK_IMMATERIAL;MANAGEMENT_LOGLOSS_IMPROVES_BUT_ACTIONS_COLLAPSE
QWEN_INPUT_CAUSALITY=PASS_0_FORBIDDEN_FIELDS;103_FLAT;1_PRIMARY;0_HEDGE
QWEN_ALLOWED_ACTIONS=9_ADAPTER_ACTIONS;STATE_MASKED_BY_POLICY
QWEN_ACTUAL_ACTIONS=85_OPEN_SHORT;17_OPEN_LONG;1_HOLD
RECOMMENDED_ACTION_SCHEMA=STATE_ACTION_OUTCOME_TRIPLETS;COUNTERFACTUAL_BRANCHES;RANK_UTILITY;RISK_ENGINE_VETO
MODIFICATIONS_TO_FROZEN=NO
TRAINING_RUN=NO
QWEN_FINE_TUNING=NO
OOS_OPENED=NO
LIVE_TRADING=NO
NEXT_WIP=none
```
