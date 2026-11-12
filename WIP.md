# WIP - TRADING-PILOT-POLICY-EXECUTION-AND-HEDGE-AUDIT-1

STATUS=ACTIVE
PHASE=TRACE_AND_DIAGNOSIS
STARTED_AT=2026-11-12
BASE_COMMIT=218390d02019e71bda21122aef56b599d2429ff0
MODE=AUDIT -> REPAIR -> TEST -> HISTORICAL REGRESSION
LIVE_TRADING=DISABLED
MODEL_RETRAINING=NO
QWEN_FINE_TUNING=NO
OOS_OPENED=NO

## Scope

Trace every potential action through market event, CatBoost, Qwen, policy,
Risk Engine, virtual order, fill/rejection, and final position state.

Investigate:

- Why HEDGE was never filled.
- Whether Qwen received correct PRIMARY/HEDGE state.
- Why Qwen proposed CLOSE_HEDGE without an open hedge.
- Hedge signal/proposal/approval/rejection/fill counter integrity.
- Trade churn, fees, slippage, cycles, averaging limits, and turnover.
- Decision/execution timestamps and minute-event causality.

## Hard limits

- No threshold optimization.
- No CatBoost retraining.
- No Qwen fine-tuning or LoRA/QLoRA.
- No changes to frozen models or prior results.
- No OOS, confirmation, S7 mutation, deployment, or live trading.

## Historical regression

After proven fixes and passing tests, rerun 2020-2021 for 60/40 and 40/60 and
compare `CATBOOST_ONLY`, `QWEN_EVENT_DRIVEN_BEFORE_FIX`, and
`QWEN_EVENT_DRIVEN_AFTER_FIX`.

## RETURN

```text
WIP=TRADING-PILOT-POLICY-EXECUTION-AND-HEDGE-AUDIT-1
STATUS=ACTIVE
PHASE=TRACE_AND_DIAGNOSIS
BASE_COMMIT=218390d
ROOT_CAUSES=pending
DEFECTS_CONFIRMED=pending
DEFECTS_FIXED=pending
HEDGE_SIGNAL_COUNT=pending
HEDGE_PROPOSED_COUNT=pending
HEDGE_APPROVED_COUNT=pending
HEDGE_REJECTED_COUNT=pending
HEDGE_FILLED_COUNT=pending
HEDGE_CLOSED_COUNT=pending
HEDGE_REJECTION_REASONS=pending
SYNTHETIC_HEDGE_TESTS=pending
PRIMARY_TRADES=pending
HEDGE_TRADES=pending
TOTAL_EXECUTED_ORDERS=pending
COMPLETED_TRADE_CYCLES=pending
TOTAL_NOTIONAL_TURNOVER=pending
TOTAL_FEES=pending
TOTAL_SLIPPAGE=pending
AVERAGING_LIMIT_TEST=pending
CAUSALITY_TESTS=pending
ACCOUNTING_TESTS=pending
CATBOOST_ONLY_EQUITY=pending
QWEN_BEFORE_FIX_EQUITY=pending
QWEN_AFTER_FIX_EQUITY=pending
MAX_DRAWDOWN=pending
LIQUIDATIONS=pending
OOS_OPENED=NO
MODEL_RETRAINING=NO
LIVE_TRADING=NO
NEXT_WIP=none
```
