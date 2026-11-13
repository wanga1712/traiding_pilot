# WIP=TRADING-PILOT-HEDGE-EFFECT-AND-CHURN-ATTRIBUTION-1

STATUS=REVIEW
STARTED_AT=2026-11-13
BASE_COMMIT=f5a8ff750cee65554951cc8e9d911e6ab4b1c700
GIT_COMMIT=PENDING
MODE=DIAGNOSTICS -> CONTROLLED_BACKTEST -> ATTRIBUTION -> REVIEW
HOST=S13
ASSET=ETHUSDT
INITIAL_CAPITAL=100
LEVERAGE=10
LIVE_TRADING=NO
MODEL_RETRAINING=NO
QWEN_FULL_RUN=NO
OOS_OPENED=NO

## Conclusions

HEDGE_EFFECT=IMMATERIAL.

The 52 HEDGE cycles had `+5.3819 USDT` gross PnL and `+1.8414 USDT`
net PnL in isolation. Their causal effect in the complete policy comparison is
only `+0.1317 USDT` across four independent 100-USDT portfolios because the
HEDGE state changes later PRIMARY actions and their costs. HEDGE prevented no
liquidations. Maximum drawdown was unchanged in three portfolios and worsened
by `0.5228` percentage points in RUN1 40/60.

CHURN_ROOT_CAUSE=MULTIPLE_CAUSES.

Of 4,749 `AI_EXIT` trade exits, 3,594 were forced by the Risk Engine and 1,155
by CatBoost management. Median holding was one hour in every portfolio, and
4,033 exits were followed by a new PRIMARY entry within one hour. The policy
immediately allows another entry on the next event. `HOLD -> SKIP` caused zero
exits.

RUN2_HEDGE_SIGNAL_DIAGNOSIS=NO_MODEL_SIGNAL_AFTER_RISK_PREEMPTION.

Only 24 RUN2 decisions reached the management model. `OPEN_HEDGE` had median
probability `4.26%`, maximum `8.08%`, and ranked fifth in 23 of 24 states.
`HOLD` won 23 states and `EXIT` won one. Free collateral was available in all
24 states; margin was not the blocker. Most PRIMARY positions were closed by
the Risk Engine before the model could propose a hedge.

MODEL_MANAGEMENT_QUALITY=WEAK.

Only 790 of 69,716 management labels chose `OPEN_HEDGE`, versus 16,993
`CLOSE_HEDGE`; 75.2% of the OPEN_HEDGE winners beat the second action by no
more than 0.05 USDT. Hedge outcomes were also fragile: 34/52 had negative net
PnL and the median was `-0.0936 USDT`; the three largest winners supplied
70.5% of all positive hedge PnL. Removing the single best hedge changes total
hedge net PnL from `+1.8414` to `-3.3123 USDT`.

## New defect found and repaired

The repaired event simulator still used futures-open and mark-close as the
execution/valuation price for Spot. This mixed the two accounting contours.
The circuit now has separate `spot_open`, `spot_close`, `futures_open`, and
mark-price fields. The correction changed the controlled totals by two orders
and one PRIMARY cycle but left all 52 HEDGE fills intact.

The isolated-deficit reconciliation is explicit:

`trade.net_pnl` includes the full theoretical isolated deficit, while collateral
can only lose available isolated margin. `ISOLATED_DEFICIT_CREDIT` is therefore
reported separately. With that line, accounting parity errors are below
`6e-12 USDT`.

## Input freeze

SHA256 values are recorded in
`docs/wip/evidence/TRADING-PILOT-HEDGE-EFFECT-AND-CHURN-ATTRIBUTION-1/input_manifest_v1.json`.

Key model hashes:

- entry direction: `df5c3eaefaab1dbdf47441e765886e882e24f2373af6dae2df86977e7b49bc86`
- entry risk: `ab2955f0efd89565d3833402cdb8425c877c8ed4bac9d34246819cbb405fd45d`
- position management: `3da5206e4099ae0edec19c0485731c33dc0af20bf1848820e714bce62f9fada0`
- minute market data: `7ce4044ff159c87251650a98925ee4519dfc06745a9e2810b39e86bcc8f9f3c0`
- funding data: `d40566ab8331ef9756d08a6c1ed67f880da02550b226c8e18083f4b9d46e8654`

## Hedged versus unhedged control

Both runs used the same frozen CatBoost, DEVELOPMENT data, thresholds, order
constraints, fees, slippage, funding, and 10x isolated execution. The only
policy change in control B was removal of the OPEN_HEDGE/CLOSE_HEDGE action
space; unused margin stayed as reserve.

| Portfolio | HEDGED | UNHEDGED | HEDGE effect | HEDGED DD | UNHEDGED DD | Liquidations |
|---|---:|---:|---:|---:|---:|---:|
| RUN1 60/40 | 342.3584 | 342.2531 | +0.1053 | 43.9411% | 43.9411% | 1 / 1 |
| RUN1 40/60 | 228.3915 | 228.3650 | +0.0264 | 33.7122% | 33.1895% | 1 / 1 |
| RUN2 60/40 | 299.7419 | 299.7419 | 0.0000 | 60.0764% | 60.0764% | 1 / 1 |
| RUN2 40/60 | 200.0258 | 200.0258 | 0.0000 | 60.0260% | 60.0260% | 1 / 1 |

No portfolio reached zero equity in either branch. HEDGE did not improve the
minimum equity or prevent any liquidation. The largest system contribution is
`+0.1053 USDT`, or about `0.033%` of aggregate initial capital across the four
separate portfolios.

## All 52 HEDGE cycles

The complete record is
`/var/tmp/traiding_pilot_ui_workspace/gpu_ai_trading_policy_v1/hedge_effect_churn_attribution_v1/analysis_final_v1/hedge_cycles_v1.csv`.
It contains all requested primary/hedge timestamps, prices, sides, margins,
probabilities, PnL before and after the hedge, fees, funding, liquidation
distance, exposure changes, and cycle results. All critical fields have zero
missing values.

| Metric | Result |
|---|---:|
| HEDGE opened / closed | 52 / 52 |
| Gross PnL | +5.3819 USDT |
| Net PnL | +1.8414 USDT |
| Positive / negative net | 18 / 34 |
| Positive gross, non-positive net | 8 |
| Median net PnL | -0.0936 USDT |
| Holding median / P90 | 2h / 13.5h |
| PRIMARY PnL change during all hedges | -12.4185 USDT |
| Paired no-hedge interval PnL | -12.4185 USDT |
| Paired HEDGED interval PnL | -10.5771 USDT |
| Adverse intervals compensated, median fraction | 60.7% |
| One HEDGE per PRIMARY cycle | 52 unique cycles |
| Overlapping hedge intervals | 0 |

The paid-to-open/close structure is material: `3.4074 USDT` fees,
`0.1331 USDT` funding, and `1.3677 USDT` estimated HEDGE slippage consumed
almost all of the `5.3819 USDT` gross gain.

These are paired market-path counterfactuals, but they are not statistically
independent observations because the strategy remains serially dependent.

## Churn attribution

| Portfolio | PRIMARY cycles | Median hold | Reentry <=1h | CatBoost exits | Risk exits | Gross-positive | Net-positive | Positive gross / negative net |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| RUN1 60/40 | 1,741 | 1h | 1,457 | 590 | 1,150 | 891 | 767 | 124 |
| RUN1 40/60 | 1,979 | 1h | 1,673 | 563 | 1,415 | 999 | 865 | 134 |
| RUN2 60/40 | 307 | 1h | 261 | 1 | 305 | 137 | 130 | 7 |
| RUN2 40/60 | 726 | 1h | 642 | 1 | 724 | 338 | 308 | 30 |
| Total | 4,753 | 1h | 4,033 | 1,155 | 3,594 | 2,365 | 2,070 | 295 |

The dominant Risk Engine reason was `RISK_DRAWDOWN_LIMIT`; a persistent
peak-to-current futures drawdown over 5% forces exit at the next available
open. CatBoost management exits had a median `EXIT` probability near 0.515,
so the model also rarely had a decisive hold signal. The exchange of
`HOLD -> SKIP` is not a closing path and caused zero exits.

Turnover by holding bucket:

- cycles held <=1h account for 94.6%, 94.4%, 99.3%, and 99.6% of portfolio
  turnover;
- median daily turnover was 871, 781, 596, and 570 USDT;
- 295 cycles were profitable before costs and non-profitable after costs.

The resulting execution totals are:

- 9,643 executed orders;
- 4,753 PRIMARY opens, 4,749 PRIMARY exits, 29 averages, 4 liquidations;
- 52 HEDGE opens and 52 HEDGE closes;
- 495,424.3885 USDT notional turnover;
- 247.6257 USDT fees and 99.0495 USDT slippage.

## RUN2 management diagnosis

Only 24 management-model states had a PRIMARY position. `OPEN_HEDGE` rank was
4 once and 5 twenty-three times. `AVERAGE_PRIMARY` was second in all 24, while
`HOLD` won 23 and `EXIT` won one.

The median OPEN_HEDGE probability was `0.0426`; the maximum was `0.0808`.
All 24 states had positive free collateral. Eight states had adverse PRIMARY
PnL. These probabilities and ranks are not close to the actual decision
boundary.

Training labels contain 33,512 allowed OPEN_HEDGE states and 790 rows whose
best counterfactual action is OPEN_HEDGE. CLOSE_HEDGE has 16,993 winning rows.
The OPEN_HEDGE utility margin is weak: median `0.0151 USDT`, with 594/790
(75.2%) winners ahead by at most `0.05 USDT`.

## Accounting attribution

Aggregate across four independent portfolios:

| Line | HEDGED |
|---|---:|
| Initial capital | 400.0000 |
| SPOT net PnL | +868.6155 |
| PRIMARY gross PnL before slippage | +140.3963 |
| PRIMARY fees | -244.2048 |
| PRIMARY funding | +0.5457 |
| PRIMARY slippage | -97.5419 |
| HEDGE gross PnL before slippage | +6.7496 |
| HEDGE fees | -3.4074 |
| HEDGE funding | -0.1331 |
| HEDGE slippage | -1.3677 |
| Isolated deficit credit | +0.8654 |
| Final equity | 1,070.5176 |
| Accounting error | < 6e-12 |

`LIQUIDATION_NET_LOSS=-17.8799 USDT` is a subset of PRIMARY net PnL and is not
added twice. Futures net PnL is `-198.0979 USDT`; nearly the entire positive
result came from Spot. This is not evidence that HEDGE created the account's
return.

Accounting-only fee/slippage sensitivity, without rerunning the policy path:

| Portfolio | Actual | Zero fees/slippage | Double fees/slippage |
|---|---:|---:|---:|
| RUN1 60/40 | 342.3584 | 494.4735 | 190.2433 |
| RUN1 40/60 | 228.3915 | 375.8124 | 80.9706 |
| RUN2 60/40 | 299.7419 | 314.5554 | 284.9285 |
| RUN2 40/60 | 200.0258 | 232.4379 | 167.6136 |

These values isolate accounting impact only; changed costs could alter the
actual trading path.

## Recommended next investigation

Do not add hedge complexity or tune thresholds. A future management-model WIP
should first define balanced counterfactual labels for
`HOLD`, `OPEN_HEDGE`, `CLOSE_HEDGE`, and `EXIT`, including fees, funding,
slippage, liquidation distance, and the consequences of immediate re-entry.
The Risk Engine's global-peak drawdown exits also need separate policy review
because they dominate the realized short holding time.

No training or next WIP was started.

## Tests

- Local: 45 passed.
- S13: 45 passed.
- Added tests cover unhedged action-space isolation, separate Spot/Futures
  prices, deficit reconciliation, all 52-cycle linking, and label counting.

## Artifacts

- Final HEDGED run:
  `/var/tmp/traiding_pilot_ui_workspace/gpu_ai_trading_policy_v1/hedge_effect_churn_attribution_v1/catboost_hedged_final_v1/`
- Final UNHEDGED run:
  `/var/tmp/traiding_pilot_ui_workspace/gpu_ai_trading_policy_v1/hedge_effect_churn_attribution_v1/catboost_unhedged_final_v1/`
- Final attribution:
  `/var/tmp/traiding_pilot_ui_workspace/gpu_ai_trading_policy_v1/hedge_effect_churn_attribution_v1/analysis_final_v1/hedge_attribution_v1.json`
- All 52 records:
  `/var/tmp/traiding_pilot_ui_workspace/gpu_ai_trading_policy_v1/hedge_effect_churn_attribution_v1/analysis_final_v1/hedge_cycles_v1.csv`
- Committed compact evidence:
  `docs/wip/evidence/TRADING-PILOT-HEDGE-EFFECT-AND-CHURN-ATTRIBUTION-1/`

## RETURN

```text
WIP=TRADING-PILOT-HEDGE-EFFECT-AND-CHURN-ATTRIBUTION-1
STATUS=REVIEW
BASE_COMMIT=f5a8ff7
HEDGE_OPENED=52
HEDGE_CLOSED=52
HEDGE_GROSS_PNL=5.3819
HEDGE_NET_PNL=1.8414
HEDGE_EFFECT_ON_TOTAL_EQUITY=0.1317
HEDGE_EFFECT_ON_DRAWDOWN=UNCHANGED;RUN1_40_WORSE_BY_0.5228_PP
LIQUIDATIONS_PREVENTED=0
RUN1_60_HEDGED=342.3584
RUN1_60_UNHEDGED=342.2531
RUN1_40_HEDGED=228.3915
RUN1_40_UNHEDGED=228.3650
RUN2_60_HEDGED=299.7419
RUN2_60_UNHEDGED=299.7419
RUN2_40_HEDGED=200.0258
RUN2_40_UNHEDGED=200.0258
PRIMARY_CYCLES=4753
MEDIAN_HOLDING_TIME=1H
AI_EXIT_COUNT=4749
REENTRY_WITHIN_1H=4033
TOTAL_TURNOVER=495424.3885
TOTAL_FEES=247.6257
TOTAL_SLIPPAGE=99.0495
PROFITABLE_BEFORE_COSTS=2365
PROFITABLE_AFTER_COSTS=2070
RUN2_HEDGE_SIGNAL_DIAGNOSIS=OPEN_HEDGE_RANK_4_TO_5;MEDIAN_PROBABILITY_0.0426;FREE_MARGIN_AVAILABLE;RISK_ENGINE_CLOSED_PRIMARY_FIRST
CHURN_ROOT_CAUSE=MULTIPLE_CAUSES
HEDGE_EFFECT=IMMATERIAL
MODEL_MANAGEMENT_QUALITY=WEAK
ACCOUNTING_PARITY=PASS
TESTS_PASS=45_LOCAL;45_S13
MODEL_RETRAINING=NO
QWEN_FULL_RUN=NO
OOS_OPENED=NO
LIVE_TRADING=NO
NEXT_WIP=none
```
