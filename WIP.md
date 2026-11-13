# WIP - TRADING-PILOT-RISK-STATE-AND-TRADE-LIFECYCLE-REPAIR-1

STATUS=ACTIVE
PHASE=DIAGNOSIS_AND_STATE_REPAIR
STARTED_AT=2026-11-13
BASE_COMMIT=071fd1df98298940d4d7d05e93850fc500552bbd
MODE=DIAGNOSE -> REPAIR -> TEST -> HISTORICAL_REGRESSION -> REVIEW
HOST=S13
ASSET=ETHUSDT
LIVE_TRADING=NO
MODEL_RETRAINING=NO
QWEN_FULL_RUN=NO
OOS_OPENED=NO

## Scope

Repair proven Risk Engine state and trade-lifecycle defects exposed by
`TRADING-PILOT-HEDGE-EFFECT-AND-CHURN-ATTRIBUTION-1`:

- retain risk/drawdown state only for the active trading hypothesis;
- reset risk state when the account returns to FLAT;
- represent FLAT, PRIMARY_OPEN, HEDGED, HEDGE_CLOSED, EXITED, RISK_EXIT, and
  LIQUIDATED explicitly;
- bind orders, fills, and risk decisions to one lifecycle/cycle ID;
- prevent stale risk state or pending orders from leaking into the next cycle;
- verify immediate re-entry and exit tracing without changing CatBoost,
  thresholds, leverage, costs, frozen research, or prior artifacts.

## Hard limits

- No model retraining, Qwen inference, parameter search, or live trading.
- No locked OOS/confirmation, S7 mutation, deploy, migration, or restart.
- Only proven accounting/execution/state defects may be changed.
- Preserve all prior REVIEW results and artifacts.

## RETURN

```text
WIP=TRADING-PILOT-RISK-STATE-AND-TRADE-LIFECYCLE-REPAIR-1
STATUS=ACTIVE
BASE_COMMIT=071fd1d
DEFECTS_CONFIRMED=pending
DEFECTS_FIXED=pending
RISK_STATE_ISOLATION=pending
LIFECYCLE_STATES=pending
STALE_STATE_LEAKS=pending
PENDING_ORDER_LEAKS=pending
RISK_EXIT_COUNT_BEFORE=pending
RISK_EXIT_COUNT_AFTER=pending
REENTRY_WITHIN_1H_BEFORE=4033
REENTRY_WITHIN_1H_AFTER=pending
ACCOUNTING_PARITY=pending
TESTS_PASS=pending
MODEL_RETRAINING=NO
QWEN_FULL_RUN=NO
OOS_OPENED=NO
LIVE_TRADING=NO
NEXT_WIP=none
```
