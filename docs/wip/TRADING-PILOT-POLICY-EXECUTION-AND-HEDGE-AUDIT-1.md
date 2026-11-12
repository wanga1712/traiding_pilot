# WIP=TRADING-PILOT-POLICY-EXECUTION-AND-HEDGE-AUDIT-1

STATUS=ACTIVE
PHASE=TRACE_AND_DIAGNOSIS
STARTED_AT=2026-11-12
BASE_COMMIT=218390d02019e71bda21122aef56b599d2429ff0
MODE=AUDIT -> REPAIR -> TEST -> HISTORICAL REGRESSION
LIVE_TRADING=NO
MODEL_RETRAINING=NO
QWEN_FINE_TUNING=NO
OOS_OPENED=NO

## Goal

Explain why the event-driven policy generated thousands of events/trades, but
never filled a HEDGE, and separate signals, proposals, approvals, rejections,
orders, fills, and position transitions with exact reasons.

## Audit scope

- Full trace:
  `MARKET_EVENT -> CATBOOST -> QWEN -> POLICY -> RISK_ENGINE -> ORDER -> FILL/REJECT -> POSITION_STATE`.
- HEDGE count correctness and state transfer.
- Trade turnover, fees, slippage, completed cycles, averaging limits.
- Decision/execution timestamp causality.
- Partial reductions, margin exhaustion, liquidation, and cost accounting.
- Synthetic LONG/SHORT hedge scenarios and state reachability.

## Repair rule

Only proven execution, accounting, trace, or state-transfer defects may be
changed. Frozen CatBoost/Qwen artifacts and prior results remain immutable.
Thresholds are not optimized on history.

## Required tests

- PRIMARY LONG and SHORT.
- HEDGE open and close.
- HEDGE rejection with reason.
- Averaging limit.
- Partial reduction.
- Repeated-event deduplication.
- Margin exhaustion.
- Liquidation.
- Fee/funding/slippage accounting.
- Causal event timing.
- No synthetic capital creation.

## Historical regression

Use the same 2020-2021 DEVELOPMENT data, 60/40 and 40/60 allocations:

1. `CATBOOST_ONLY`.
2. Saved `QWEN_EVENT_DRIVEN_BEFORE_FIX`.
3. `QWEN_EVENT_DRIVEN_AFTER_FIX`.

If no hedge opens, report exact counts for no signal, policy rejection, margin
shortage, risk rejection, Qwen rejection, and order rejection.

## Safety

- No live trading, deployment, restart, migrations, or S7 mutation.
- No OOS/confirmation.
- No model retraining or Qwen fine-tuning.
- No next WIP automatically.

## RETURN

```text
WIP=TRADING-PILOT-POLICY-EXECUTION-AND-HEDGE-AUDIT-1
STATUS=REVIEW
BASE_COMMIT=218390d
ROOT_CAUSES=
DEFECTS_CONFIRMED=
DEFECTS_FIXED=
HEDGE_SIGNAL_COUNT=
HEDGE_PROPOSED_COUNT=
HEDGE_APPROVED_COUNT=
HEDGE_REJECTED_COUNT=
HEDGE_FILLED_COUNT=
HEDGE_CLOSED_COUNT=
HEDGE_REJECTION_REASONS=
SYNTHETIC_HEDGE_TESTS=
PRIMARY_TRADES=
HEDGE_TRADES=
TOTAL_EXECUTED_ORDERS=
COMPLETED_TRADE_CYCLES=
TOTAL_NOTIONAL_TURNOVER=
TOTAL_FEES=
TOTAL_SLIPPAGE=
AVERAGING_LIMIT_TEST=
CAUSALITY_TESTS=
ACCOUNTING_TESTS=
CATBOOST_ONLY_EQUITY=
QWEN_BEFORE_FIX_EQUITY=
QWEN_AFTER_FIX_EQUITY=
MAX_DRAWDOWN=
LIQUIDATIONS=
OOS_OPENED=NO
MODEL_RETRAINING=NO
LIVE_TRADING=NO
NEXT_WIP=none
```

