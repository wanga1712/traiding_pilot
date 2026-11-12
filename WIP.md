# WIP - TRADING-PILOT-EVENT-DRIVEN-QWEN-POLICY-1

STATUS=ACTIVE
PHASE=EVENT_DRIVEN_RUN
STARTED_AT=2026-11-12
MODE=EVENT-DRIVEN HISTORICAL SIMULATION
MODEL_RETRAINING=NO
QWEN_FINE_TUNING=NO
LIVE_TRADING=DISABLED
OOS_OPENED=NO

## Frozen event policy

- Qwen is triggered by significant events, not a calendar interval.
- No annual call limit.
- Noncritical cooldown: 4 hours.
- Dedup window: 24 hours.
- Primary adverse: 1 ATR; rearm at 0.5 ATR.
- Averaging events: 2 and 4 ATR.
- Strong-entry event: 0.80 CatBoost probability.
- Probability shift: 0.30.
- Margin shift: 20 percentage points.
- Liquidation-distance shift: 3 percentage points.
- Risk warning/emergency: 3% / 5%.
- Liquidation warning/emergency: 5% / 3%.
- Qwen timeout: 30 seconds; safe fallback is the CatBoost action.
- Risk-emergency events bypass Qwen and execute through the Risk Engine.

Minute mark/futures extremes are used inside each closed 1H decision interval.
Higher-timeframe features remain causal.

## Compared policies

- `CATBOOST_ONLY`
- `CATBOOST_QWEN_336H`
- `CATBOOST_QWEN_EVENT_DRIVEN`

Both 60/40 and 40/60 are required. OOS stays locked and 2020-2021 remain
DEVELOPMENT/regression only.

## RETURN

```text
WIP=TRADING-PILOT-EVENT-DRIVEN-QWEN-POLICY-1
STATUS=ACTIVE
PHASE=EVENT_DRIVEN_RUN
LOCAL_BRANCH=wip/trading-pilot-event-driven-qwen-policy-1
MARKET_EVENTS_DETECTED=pending
QWEN_CALLS=pending
QWEN_ACTION_CHANGES=pending
HEDGE_OPEN_EVENTS=pending
HEDGE_CLOSE_EVENTS=pending
RISK_EVENTS=pending
FALLBACKS=pending
MEDIAN_LATENCY=pending
P90_LATENCY=pending
CATBOOST_ONLY_EQUITY=pending
QWEN_336H_EQUITY=pending
QWEN_EVENT_DRIVEN_EQUITY=pending
QWEN_ADDED_VALUE=pending
LIQUIDATIONS=pending
MAX_DRAWDOWN=pending
OOS_OPENED=NO
LIVE_TRADING=NO
NEXT_WIP=none
```
