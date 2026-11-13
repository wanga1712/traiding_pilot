# WIP=TRADING-PILOT-RISK-STATE-AND-TRADE-LIFECYCLE-REPAIR-1

STATUS=REVIEW
STARTED_AT=2026-11-13
BASE_COMMIT=071fd1df98298940d4d7d05e93850fc500552bbd
GIT_COMMIT=PENDING
MODE=DIAGNOSE -> REPAIR -> TEST -> HISTORICAL_REGRESSION -> REVIEW
HOST=S13
LIVE_TRADING=NO
MODEL_RETRAINING=NO
QWEN_FULL_RUN=NO
OOS_OPENED=NO

## Diagnosis

The previous audit showed that the Risk Engine caused 3,594 of 4,749
`AI_EXIT` events. The drawdown calculation used the lifetime peak of Futures
equity. After any earlier account peak, every new PRIMARY hypothesis inherited
that old drawdown and could be forced out on its first management bar.

Four additional lifecycle defects were confirmed:

1. A position had no durable hypothesis/cycle identity.
2. Lifecycle states were implicit and could not distinguish `HEDGE_CLOSED`,
   `RISK_EXIT`, `EXITED`, and `LIQUIDATED`.
3. Risk exits lost their cause in the trade record and appeared as generic
   `AI_EXIT`.
4. Run-end closes used the final bar-open timestamp, which sorted before the
   last decision row. `final_equity` therefore retained nonzero open margin and
   omitted final exit costs.

## Repair

- Risk drawdown is now scoped to the active PRIMARY hypothesis.
- `begin_risk_cycle()` freezes the post-entry equity baseline and starts a
  per-cycle Futures peak.
- `EXITED` and `LIQUIDATED` clear risk baseline/peak; the next PRIMARY starts a
  fresh risk cycle.
- Lifecycle IDs and transitions are persisted for every cycle.
- Orders, trades, decisions, and action traces carry `cycle_id`.
- Risk exits preserve `RISK_DRAWDOWN_LIMIT`, `LIQUIDATION_BUFFER_LIMIT`, or
  `LIQUIDATION_EVENT` as the trade reason.
- Terminal close is recorded at `decision_at`, after all prior equity rows, so
  final margin is zero and terminal costs are included.
- `lifecycle_events.csv` is emitted for every portfolio.

## Historical regression

Same frozen CatBoost, data, thresholds, 10x isolated execution, costs, and
HEDGE rules. Only the proven risk-state/lifecycle defects changed.

| Portfolio | Equity before | Equity after | Max DD before | Max DD after | Liquidations before/after |
|---|---:|---:|---:|---:|---:|
| RUN1 60/40 | 342.3584 | 353.2007 | 43.9411% | 33.9931% | 1 / 5 |
| RUN1 40/60 | 228.3915 | 265.0684 | 33.7122% | 27.7247% | 1 / 5 |
| RUN2 60/40 | 299.7419 | 299.6859 | 60.0764% | 60.0860% | 1 / 4 |
| RUN2 40/60 | 200.0258 | 199.7442 | 60.0260% | 60.0978% | 1 / 4 |

Aggregate:

| Metric | Before | After |
|---|---:|---:|
| PRIMARY cycles | 4,753 | 2,218 |
| Risk Engine exits | 3,594 | 76 |
| Re-entry <=1h | 4,033 | 1,813 |
| Executed orders | 9,643 | 4,552 |
| Notional turnover | 495,424.39 | 275,617.37 |
| Fees | 247.63 | 137.27 |
| Slippage | 99.05 | 54.91 |
| HEDGE orders | 104 | 84 |
| Liquidations | 4 | 18 |
| Aggregate final equity | 1,070.52 | 1,117.70 |

The repair removed 97.9% of stale-risk exits and reduced re-entry <=1h by
55.0%. It also exposed a negative side effect: positions are no longer closed
early by inherited risk state, so liquidation count increased from 4 to 18.
This is a risk finding, not a profitability improvement claim.

## Lifecycle integrity

All four portfolios passed:

- 2,218/2,218 PRIMARY cycles reached a terminal state;
- zero lifecycle transition anomalies;
- zero executed Futures orders after terminal state;
- zero executed Futures orders without a positive `cycle_id`;
- all final `used_margin` values equal zero;
- accounting parity error is below `4e-12 USDT`.

Observed states include `PRIMARY_OPEN`, `PRIMARY_AVERAGED`, `HEDGED`,
`HEDGE_CLOSED`, `RISK_EXIT`, `EXITED`, `LIQUIDATED`, and `FLAT`.

## Residual churn

After the repair, 2,122 exits are CatBoost management exits and only 76 are
Risk Engine exits. Median holding remains one hour in every portfolio. The
risk-state defect is fixed, but the model remains the dominant source of
short-duration exits. Changing that requires a separate action-learning/policy
WIP; no thresholds or models were changed here.

## Input and artifacts

- Input SHA256:
  `docs/wip/evidence/TRADING-PILOT-RISK-STATE-AND-TRADE-LIFECYCLE-REPAIR-1/input_manifest_v1.json`
- Compact result:
  `docs/wip/evidence/TRADING-PILOT-RISK-STATE-AND-TRADE-LIFECYCLE-REPAIR-1/summary_v1.json`
- Final S13 run:
  `/var/tmp/traiding_pilot_ui_workspace/gpu_ai_trading_policy_v1/risk_state_lifecycle_repair_v1/catboost_hedged_final_v3/`
- Final lifecycle audit:
  `/var/tmp/traiding_pilot_ui_workspace/gpu_ai_trading_policy_v1/risk_state_lifecycle_repair_v1/lifecycle_audit_final_v3.json`

## Tests

- Local: 48 passed.
- S13: 48 passed.
- New coverage: cross-cycle risk reset, cycle IDs, hedge lifecycle transitions,
  terminal state ordering, risk-reason propagation, and no post-terminal
  Futures orders.

## RETURN

```text
WIP=TRADING-PILOT-RISK-STATE-AND-TRADE-LIFECYCLE-REPAIR-1
STATUS=REVIEW
BASE_COMMIT=071fd1d
DEFECTS_CONFIRMED=5
DEFECTS_FIXED=5
RISK_STATE_ISOLATION=PASS
LIFECYCLE_STATES=PASS
STALE_STATE_LEAKS=0
PENDING_ORDER_LEAKS=0
RISK_EXIT_COUNT_BEFORE=3594
RISK_EXIT_COUNT_AFTER=76
REENTRY_WITHIN_1H_BEFORE=4033
REENTRY_WITHIN_1H_AFTER=1813
ACCOUNTING_PARITY=PASS
TESTS_PASS=48_LOCAL;48_S13
MODEL_RETRAINING=NO
QWEN_FULL_RUN=NO
OOS_OPENED=NO
LIVE_TRADING=NO
NEXT_WIP=none
```
