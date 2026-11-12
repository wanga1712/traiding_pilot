# WIP=TRADING-PILOT-EVENT-DRIVEN-QWEN-POLICY-1

STATUS=REVIEW
PHASE=REVIEW
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

## Result

- Triggered market/position/risk events: 4,123.
- Suppressed by hysteresis, dedup, or cooldown: 3,871.
- Qwen-eligible events: 329.
- Actual Qwen calls after grouping/cache: 275.
- Qwen action changes: 6.
- Fallbacks: 22.
- Actual hedge opens: 0.
- Hedge-close events: 0.
- Risk events: 6.
- Median Qwen latency: 12.84 seconds; P90: 17.03 seconds.

| Run | Allocation | CatBoost only | Qwen 336h | Qwen event-driven | Added value |
|---|---|---:|---:|---:|---:|
| RUN 1 | 60/40 | 342.3394 | 342.3452 | 342.3394 | 0.0000 |
| RUN 1 | 40/60 | 228.3672 | 228.4057 | 228.3672 | 0.0000 |
| RUN 2 | 60/40 | 299.8139 | 299.8139 | 299.7707 | -0.0432 |
| RUN 2 | 40/60 | 200.0139 | 200.0139 | 199.9955 | -0.0184 |

All six Qwen action changes were `SKIP -> REDUCE_POSITION` in RUN 2. This
proves the adapter can alter real allowed decisions, but total event-driven
added value is negative: `-0.0616 USDT`.

No hedge was actually opened. Qwen CLOSE_HEDGE proposals were therefore
inapplicable to the state and were rejected by policy. REDUCE_POSITION has no
training examples, so its successful execution is a policy capability, not
validated learned support.

Worst drawdown: 60.07%. Liquidations across the four event portfolios: 6.

## RETURN

```text
WIP=TRADING-PILOT-EVENT-DRIVEN-QWEN-POLICY-1
STATUS=REVIEW
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
QWEN_ADDED_VALUE=-0.0616_TOTAL;NO_MATERIAL_ADVANTAGE
LIQUIDATIONS=6
MAX_DRAWDOWN=60.07%
OOS_OPENED=NO
LIVE_TRADING=NO
NEXT_WIP=none
```
