# WIP - TRADING-PILOT-EVENT-DRIVEN-QWEN-POLICY-1

STATUS=REVIEW
PHASE=REVIEW
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

## Result

- 4,123 significant events triggered; 3,871 suppressed.
- 329 Qwen-eligible events produced 275 actual calls.
- Qwen changed six actions, all `SKIP -> REDUCE_POSITION` in RUN 2.
- Hedge opens/closes executed: 0/0.
- Fallbacks: 22.
- Event-driven Qwen added value: `-0.0616 USDT`.
- Event-driven final equity: RUN 1 `342.3394/228.3672`; RUN 2
  `299.7707/199.9955`.
- Maximum drawdown: 60.07%.
- Liquidations across four event portfolios: 6.

## RETURN

```text
WIP=TRADING-PILOT-EVENT-DRIVEN-QWEN-POLICY-1
STATUS=REVIEW
PHASE=REVIEW
LOCAL_BRANCH=wip/trading-pilot-event-driven-qwen-policy-1
MARKET_EVENTS_DETECTED=4123;SUPPRESSED_3871;QWEN_ELIGIBLE_329
QWEN_CALLS=275
QWEN_ACTION_CHANGES=6
HEDGE_OPEN_EVENTS=0
HEDGE_CLOSE_EVENTS=0
RISK_EVENTS=6
FALLBACKS=22
MEDIAN_LATENCY=12.84_SECONDS
P90_LATENCY=17.03_SECONDS
CATBOOST_ONLY_EQUITY=RUN1_60_342.3394;RUN1_40_228.3672;RUN2_60_299.8139;RUN2_40_200.0139
QWEN_336H_EQUITY=RUN1_60_342.3452;RUN1_40_228.4057;RUN2_60_299.8139;RUN2_40_200.0139
QWEN_EVENT_DRIVEN_EQUITY=RUN1_60_342.3394;RUN1_40_228.3672;RUN2_60_299.7707;RUN2_40_199.9955
QWEN_ADDED_VALUE=-0.0616_TOTAL
LIQUIDATIONS=6
MAX_DRAWDOWN=60.07%
OOS_OPENED=NO
LIVE_TRADING=NO
NEXT_WIP=none
```
