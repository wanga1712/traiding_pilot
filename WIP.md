# WIP - TRADING-PILOT-HEDGE-EFFECT-AND-CHURN-ATTRIBUTION-1

STATUS=ACTIVE
PHASE=INPUT_FREEZE_AND_ATTRIBUTION
STARTED_AT=2026-11-13
BASE_COMMIT=f5a8ff750cee65554951cc8e9d911e6ab4b1c700
MODE=DIAGNOSTICS -> CONTROLLED_BACKTEST -> ATTRIBUTION -> REVIEW
HOST=S13
ASSET=ETHUSDT
INITIAL_CAPITAL=100
LEVERAGE=10
LIVE_TRADING=NO
MODEL_RETRAINING=NO
QWEN_FULL_RUN=NO
OOS_OPENED=NO

## Scope

Attribute the economics of all 52 HEDGE cycles, compare hedged and unhedged
CatBoost policies, explain the one-hour PRIMARY churn, and determine why RUN2
has no HEDGE signals. Use the simulator and model artifacts from
`TRADING-PILOT-POLICY-EXECUTION-AND-HEDGE-AUDIT-1` without changing signals or
tuning thresholds.

## Hard limits

- No CatBoost retraining, Qwen inference, LoRA/QLoRA, or threshold search.
- No frozen research, locked OOS, confirmation, S7, or live-trading changes.
- Do not overwrite prior WIP artifacts.
- Do not close prior REVIEW WIPs.
- Repair only proven accounting or execution defects, with regression tests.

## RETURN

```text
WIP=TRADING-PILOT-HEDGE-EFFECT-AND-CHURN-ATTRIBUTION-1
STATUS=ACTIVE
BASE_COMMIT=f5a8ff7
HEDGE_OPENED=pending
HEDGE_CLOSED=pending
HEDGE_GROSS_PNL=pending
HEDGE_NET_PNL=pending
HEDGE_EFFECT_ON_TOTAL_EQUITY=pending
HEDGE_EFFECT_ON_DRAWDOWN=pending
LIQUIDATIONS_PREVENTED=pending
RUN1_60_HEDGED=pending
RUN1_60_UNHEDGED=pending
RUN1_40_HEDGED=pending
RUN1_40_UNHEDGED=pending
RUN2_60_HEDGED=pending
RUN2_60_UNHEDGED=pending
RUN2_40_HEDGED=pending
RUN2_40_UNHEDGED=pending
PRIMARY_CYCLES=pending
MEDIAN_HOLDING_TIME=pending
AI_EXIT_COUNT=pending
REENTRY_WITHIN_1H=pending
TOTAL_TURNOVER=pending
TOTAL_FEES=pending
TOTAL_SLIPPAGE=pending
PROFITABLE_BEFORE_COSTS=pending
PROFITABLE_AFTER_COSTS=pending
RUN2_HEDGE_SIGNAL_DIAGNOSIS=pending
CHURN_ROOT_CAUSE=pending
HEDGE_EFFECT=pending
MODEL_MANAGEMENT_QUALITY=pending
ACCOUNTING_PARITY=pending
TESTS_PASS=pending
MODEL_RETRAINING=NO
QWEN_FULL_RUN=NO
OOS_OPENED=NO
LIVE_TRADING=NO
NEXT_WIP=none
```
