# WIP=TRADING-PILOT-EVENT-DRIVEN-QWEN-POLICY-1

STATUS=ACTIVE
PHASE=EVENT_DRIVEN_RUN
STARTED_AT=2026-11-12
MODE=EVENT-DRIVEN HISTORICAL SIMULATION
GPU=S13_QWEN_2_5_7B_AND_CATBOOST
LIVE_TRADING=NO
MODEL_RETRAINING=NO
QWEN_FINE_TUNING=NO
OOS_OPENED=NO

## Goal

Replace the calendar-triggered Qwen validator with a causal event monitor. Call
Qwen only for significant market, position, margin, or risk events, then compare
CatBoost-only, previous 336-hour Qwen validation, and event-driven Qwen.

## Frozen event contract

| Parameter | Value |
|---|---:|
| Noncritical cooldown | 4 hours |
| Signature dedup | 24 hours |
| Primary adverse event | 1.0 ATR |
| Adverse-event rearm | 0.5 ATR |
| Averaging events | 2.0 and 4.0 ATR |
| Hedge-close profit trigger | 0.5% of equity |
| CatBoost probability shift | 0.30 |
| Strong-entry probability | 0.80 |
| Volatility trigger | ATR/price 2% |
| Risk-loss warning | 3% |
| Risk-loss emergency | 5% |
| Liquidation-buffer warning | 5% |
| Liquidation-buffer emergency | 3% |
| Free-margin shift | 20 percentage points |
| Liquidation-distance shift | 3 percentage points |
| Qwen timeout | 30 seconds |
| Qwen timeout fallback | CatBoost action |
| Annual Qwen call limit | None |

Risk-emergency events bypass Qwen cooldown and execute a protective exit through
the Risk Engine. Qwen sees only events marked significant; all triggered and
suppressed events remain journaled.

## Minute-history rule

- The policy decision clock remains the closed 1H causal dataset.
- Minute futures/mark OHLC is aggregated into each decision hour.
- Entry, adverse, liquidation-buffer, and risk events use minute highs/lows.
- 1H/4H/1D indicators enter only after their source candle has closed.

## Compared policies

1. `CATBOOST_ONLY`.
2. `CATBOOST_QWEN_336H` from the accepted Qwen comparison.
3. `CATBOOST_QWEN_EVENT_DRIVEN`.

Both 60/40 and 40/60 allocations use spot HOLD, 10x isolated futures, and the
same costs and Risk Engine.

## Data limitation

Only 2020-2021 execution history is available. These years are
DEVELOPMENT/regression data, not independent OOS. Locked OOS remains untouched.

## Safety

- No CatBoost training.
- No Qwen fine-tuning or LoRA/QLoRA.
- No threshold search on RUN 2.
- No frozen-artifact or previous-result mutation.
- No live orders, deployment, S7 mutation, or service restart.

## RETURN

```text
WIP=TRADING-PILOT-EVENT-DRIVEN-QWEN-POLICY-1
STATUS=REVIEW
MARKET_EVENTS_DETECTED=
QWEN_CALLS=
QWEN_ACTION_CHANGES=
HEDGE_OPEN_EVENTS=
HEDGE_CLOSE_EVENTS=
RISK_EVENTS=
FALLBACKS=
MEDIAN_LATENCY=
P90_LATENCY=
CATBOOST_ONLY_EQUITY=
QWEN_336H_EQUITY=
QWEN_EVENT_DRIVEN_EQUITY=
QWEN_ADDED_VALUE=
LIQUIDATIONS=
MAX_DRAWDOWN=
OOS_OPENED=NO
LIVE_TRADING=NO
NEXT_WIP=none
```

