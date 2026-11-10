# WIP=TRADING-PILOT-CAPITAL-GROWTH-EXPERIMENT-1

STATUS=REVIEW
REGISTRATION=AUTHORIZED
ACTIVATED=YES

STARTED_AT=2026-11-10
CLOSED_AT=
MODE=BUILD + RUN / HISTORICAL SIMULATION ONLY
INITIAL_CAPITAL=100 USDT
ASSET=ETHUSDT
LEVERAGE=10X_ISOLATED
FUTURES_MODE=HEDGE_MODE
LIVE_TRADING=DISABLED

## Goal

Determine through a historical simulation whether Trading Pilot can grow
capital by holding a primary long-term position and using an opposite futures
position to offset adverse movement.

The primary position may be LONG or SHORT. The hedge is always opposite and is
a temporary risk-reduction position, not an automatic symmetric copy.

## Authorization

- `USER_APPROVAL=YES`
- `DATE=2026-11-10`
- `SCOPE=BUILD_AND_RUN_HISTORICAL_SIMULATION`
- `LIVE_TRADING=NO`
- S13 execution and modification authorized by the user.
- S7 remains read-only and out of scope.

## Capital structures

| Variant | Spot USDT | Futures USDT |
|---|---:|---:|
| A | 60 | 40 |
| B | 40 | 60 |

Spot behavior may be HOLD or SWING. Futures contains a primary position and a
temporary hedge position. The same collateral may not support multiple
positions. Rebalancing occurs only under rules frozen before the historical
runs.

## Position model

- `PRIMARY_POSITION`: the current directional thesis.
- `HEDGE_POSITION`: optional opposite position sized from current risk.

Required states:

- `FLAT`
- `PRIMARY_OPEN`
- `HEDGED`
- `HEDGE_CLOSED`
- `PRIMARY_AVERAGED`
- `EXITED`
- `RISK_EXIT`
- `LIQUIDATED`

Every state transition and order decision must be recorded in an event journal.

## Dynamic hedge scope

- Support partial and full hedge sizes.
- Do not automatically equal the primary position size.
- Re-evaluate gross exposure, net exposure, used/free margin, maintenance
  margin, both liquidation prices, realized/unrealized PnL, and two-sided
  liquidation risk before opening a hedge.
- Hedge realized profit cannot be reused until all execution costs have been
  deducted and the position is closed.
- Repeated hedging is allowed only under a pre-frozen count and condition set.
- A position that can liquidate before a hedge becomes possible is classified
  as unprotected.

## Pre-trade risk engine

Before every primary, hedge, or averaging entry:

- Calculate adverse-move loss at +/-3%, 5%, 8%, 10%, and 15%.
- Calculate margin and liquidation-buffer changes.
- Compare portfolio PnL with and without the proposed hedge.
- Evaluate whether later averaging remains feasible.
- Calculate break-even price and expected holding cost including fees/funding.
- Report historical recovery-time P50/P90, unresolved share, and uncertainty
  using only information available at decision time.

The primary experiment may not predict a loss above 5% of total capital for one
thesis. Reduce size or skip the entry when this cannot be guaranteed. A
hold-to-liquidation stress run is separate from the main result.

## Futures budget allocation

- 40% initial primary position
- 20% hedge reserve
- 20% first averaging reserve
- 20% second averaging reserve

These percentages apply only to the futures budget. Maximum averaging count is
two. Averaging requires the thesis to remain intact, confirming indicators, and
a second successful risk-engine pass.

Required controls:

- Hedge disabled
- Averaging disabled
- Base hedge/average configuration

## Accounting

Track separately:

- Spot ETH and Spot USDT
- Futures free collateral
- PRIMARY margin
- HEDGE margin
- PRIMARY/HEDGE unrealized and realized PnL
- Funding, fees, and slippage
- Transfers between positions and contours
- Total portfolio equity

Hedge profit may not be counted as both equity growth and an external capital
injection. Liquidation applies the selected exchange's rules and must be marked
approximate if required historical inputs are unavailable.

## Historical runs

### RUN 1 — DISCOVERY

- Use the first eligible year from approved DEVELOPMENT data.
- Evaluate capital splits A/B, Spot HOLD/SWING, hedge, no-hedge control, and
  no-averaging control.
- Limited rule selection is allowed only if described before execution.
- Freeze configurations, risk parameters, exits, hedge rules, and SHA256 after
  RUN 1.

### RUN 2 — VALIDATION

- Use the immediately following chronological year from approved DEVELOPMENT
  data.
- Do not alter frozen parameters after observing RUN 2.
- Simulate realistic fills, fees, funding, liquidation, and missing candles.
- Stop a configuration on smoke, accounting, or risk-test failure and report
  why.

Existing OOS/confirmation remain closed. CatBoost and frozen research artifacts
are immutable.

## Implementation completed

- Simulator package:
  `phase3_staging/crypto_trading_bot/research_v2/capital_growth/`.
- Twelve independent portfolios per run: A/B capital split x HOLD/SWING spot
  mode x hedged-with-averaging, hedged-without-averaging, and unhedged control.
- PRIMARY and HEDGE positions are accounted for independently, with isolated
  margin, mark-price liquidation, fees, funding, slippage, and partial hedges.
- The pre-trade risk engine evaluates adverse moves of 3%, 5%, 8%, 10%, and
  15%, free margin, liquidation buffers, future hedging capacity, and the 5%
  total-capital loss limit.
- The explicit state machine and event journal cover `FLAT`, `PRIMARY_OPEN`,
  `HEDGED`, `HEDGE_CLOSED`, `PRIMARY_AVERAGED`, `EXITED`, `RISK_EXIT`, and
  `LIQUIDATED`.
- No CatBoost model, frozen research artifact, S7 data, or blocked
  OOS/confirmation set was read or changed.
- RUN 1 used six CPU workers on S13. CUDA was not used because no model was
  trained.

The strategy is intentionally a fixed causal baseline:

- LONG when `close > SMA20 > SMA50`; SHORT when
  `close < SMA20 < SMA50`.
- A hedge becomes eligible after a confirmed opposite trend and at least a
  2-ATR adverse excursion.
- Averaging is eligible at 2-ATR and 4-ATR adverse excursions while the
  original thesis remains intact, capped at two entries.
- Exit occurs after an opposite trend following at least 72 hours, or at the
  end of the run.

## Data gate

| Check | Result |
|---|---:|
| Observation window | 2020-01-01 through 2022-01-01 UTC |
| Expected minutes | 1,052,640 |
| Spot coverage | 99.7866% |
| Futures coverage | 100% |
| Mark-price coverage | 99.9950% |
| Combined coverage | 99.7816% |
| Spot gaps | 14; maximum 355 minutes |
| Futures gaps | 0 |
| Mark-price gaps | 2; maximum 30 minutes |
| Funding | 2,193 / 2,193 rows |
| Duplicate rows | 0 |
| Preflight | PASS |

Source data came from public Binance spot/futures/mark-price/funding APIs and
the disposable S13 spot cache. S7 was not changed.

## Final results

RUN 1 covers 2020-01-01 through 2021-01-01. RUN 2 covers 2021-01-01 through
2022-01-01 using the configuration frozen and hash-verified before RUN 2.
Every portfolio starts with 100 USDT.

| Run | Best portfolio | Final equity | Buy & Hold equivalent |
|---|---|---:|---:|
| RUN 1 | `A_HOLD_UNHEDGED_AVG` | 269.84 | 570.78 |
| RUN 2 | `A_HOLD_UNHEDGED_AVG` | 206.28 | 498.80 |

Dynamic hedging did not beat the matching unhedged control in any of the eight
comparisons. `HEDGED_BEATS_UNHEDGED_COUNT=0/8`.

| Run | Pair | Hedged final | Unhedged final | Delta | Liq. prevented | Averaging effect |
|---|---|---:|---:|---:|---:|---:|
| RUN 1 | A HOLD | 233.18 | 269.84 | -36.65 | +1 | -1.03 |
| RUN 1 | A SWING | 151.75 | 173.57 | -21.83 | -3 | -4.28 |
| RUN 1 | B HOLD | 105.10 | 157.92 | -52.82 | -3 | -0.12 |
| RUN 1 | B SWING | 123.26 | 142.69 | -19.43 | -4 | -3.30 |
| RUN 2 | A HOLD | 206.22 | 206.28 | -0.06 | 0 | 0.00 |
| RUN 2 | A SWING | 113.16 | 125.57 | -12.42 | -2 | 0.00 |
| RUN 2 | B HOLD | 104.88 | 144.37 | -39.49 | -3 | 0.00 |
| RUN 2 | B SWING | 103.17 | 114.58 | -11.40 | -2 | 0.00 |

`NET_LIQUIDATIONS_PREVENTED=-16`: the hedged portfolios had 65 liquidation
events versus 49 for their unhedged controls. The negative count means hedging
created more liquidation events in aggregate.

### RUN 1 portfolios

| Portfolio | Final | PRIMARY PnL | HEDGE PnL | Max DD | Liq. | Hedges | Avg. | PF |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A_HOLD_HEDGED_AVG | 233.18 | -5.44 | -1.78 | 26.73% | 5 | 5 | 2 | 0.828 |
| A_HOLD_HEDGED_NOAVG | 234.21 | -7.13 | -0.01 | 25.14% | 5 | 5 | 0 | 0.830 |
| A_HOLD_UNHEDGED_AVG | 269.84 | -29.18 | 0.00 | 27.38% | 6 | 0 | 2 | 0.528 |
| A_SWING_HEDGED_AVG | 151.75 | -19.25 | 0.19 | 27.66% | 7 | 11 | 4 | 0.405 |
| A_SWING_HEDGED_NOAVG | 156.02 | -8.48 | -1.46 | 27.66% | 8 | 11 | 0 | 0.531 |
| A_SWING_UNHEDGED_AVG | 173.57 | -17.16 | 0.00 | 26.20% | 4 | 0 | 3 | 0.300 |
| B_HOLD_HEDGED_AVG | 105.10 | -24.39 | -1.16 | 31.40% | 8 | 11 | 3 | 0.526 |
| B_HOLD_HEDGED_NOAVG | 105.22 | -20.44 | 0.28 | 31.33% | 8 | 11 | 0 | 0.584 |
| B_HOLD_UNHEDGED_AVG | 157.92 | -46.67 | 0.00 | 14.49% | 5 | 0 | 3 | 0.355 |
| B_SWING_HEDGED_AVG | 123.26 | -17.64 | 0.13 | 20.77% | 8 | 12 | 4 | 0.400 |
| B_SWING_HEDGED_NOAVG | 126.56 | -8.32 | -1.26 | 20.15% | 9 | 12 | 0 | 0.516 |
| B_SWING_UNHEDGED_AVG | 142.69 | -14.85 | 0.00 | 18.69% | 4 | 0 | 3 | 0.313 |

### RUN 2 portfolios

| Portfolio | Final | PRIMARY PnL | HEDGE PnL | Max DD | Liq. | Hedges | Avg. | PF |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A_HOLD_HEDGED_AVG | 206.22 | -39.76 | -0.02 | 40.57% | 6 | 1 | 0 | 0.011 |
| A_HOLD_HEDGED_NOAVG | 206.22 | -39.76 | -0.02 | 40.57% | 6 | 1 | 0 | 0.011 |
| A_HOLD_UNHEDGED_AVG | 206.28 | -39.98 | 0.00 | 40.57% | 6 | 0 | 0 | 0.011 |
| A_SWING_HEDGED_AVG | 113.16 | -7.72 | -2.38 | 27.02% | 10 | 8 | 0 | 0.500 |
| A_SWING_HEDGED_NOAVG | 113.16 | -7.72 | -2.38 | 27.02% | 10 | 8 | 0 | 0.500 |
| A_SWING_UNHEDGED_AVG | 125.57 | -9.35 | 0.00 | 24.54% | 8 | 0 | 0 | 0.470 |
| B_HOLD_HEDGED_AVG | 104.88 | -36.07 | -0.43 | 33.10% | 11 | 9 | 0 | 0.525 |
| B_HOLD_HEDGED_NOAVG | 104.88 | -36.07 | -0.43 | 33.10% | 11 | 9 | 0 | 0.525 |
| B_HOLD_UNHEDGED_AVG | 144.37 | -41.96 | 0.00 | 16.71% | 8 | 0 | 0 | 0.488 |
| B_SWING_HEDGED_AVG | 103.17 | -7.70 | -2.17 | 22.99% | 10 | 8 | 0 | 0.478 |
| B_SWING_HEDGED_NOAVG | 103.17 | -7.70 | -2.17 | 22.99% | 10 | 8 | 0 | 0.478 |
| B_SWING_UNHEDGED_AVG | 114.58 | -9.16 | 0.00 | 17.32% | 8 | 0 | 0 | 0.448 |

### Execution costs by portfolio

Values are USDT. Negative funding is a cash cost paid by the portfolio.

| Run | Portfolio | Fees | Funding | Slippage | Liq. fees |
|---|---|---:|---:|---:|---:|
| RUN 1 | A_HOLD_HEDGED_AVG | 0.831 | -3.258 | 0.332 | 0.199 |
| RUN 1 | A_HOLD_HEDGED_NOAVG | 0.766 | -3.394 | 0.307 | 0.201 |
| RUN 1 | A_HOLD_UNHEDGED_AVG | 1.262 | -3.309 | 0.505 | 0.216 |
| RUN 1 | A_SWING_HEDGED_AVG | 0.735 | -0.943 | 0.294 | 0.118 |
| RUN 1 | A_SWING_HEDGED_NOAVG | 0.563 | -0.888 | 0.225 | 0.079 |
| RUN 1 | A_SWING_UNHEDGED_AVG | 0.448 | -1.038 | 0.179 | 0.065 |
| RUN 1 | B_HOLD_HEDGED_AVG | 1.191 | -3.824 | 0.477 | 0.263 |
| RUN 1 | B_HOLD_HEDGED_NOAVG | 1.067 | -3.778 | 0.427 | 0.240 |
| RUN 1 | B_HOLD_UNHEDGED_AVG | 1.366 | -3.772 | 0.546 | 0.233 |
| RUN 1 | B_SWING_HEDGED_AVG | 0.640 | -0.836 | 0.256 | 0.112 |
| RUN 1 | B_SWING_HEDGED_NOAVG | 0.494 | -0.787 | 0.198 | 0.078 |
| RUN 1 | B_SWING_UNHEDGED_AVG | 0.400 | -0.923 | 0.160 | 0.055 |
| RUN 2 | A_HOLD_HEDGED_AVG | 0.307 | -1.331 | 0.123 | 0.228 |
| RUN 2 | A_HOLD_HEDGED_NOAVG | 0.307 | -1.331 | 0.123 | 0.228 |
| RUN 2 | A_HOLD_UNHEDGED_AVG | 0.307 | -1.335 | 0.123 | 0.230 |
| RUN 2 | A_SWING_HEDGED_AVG | 0.476 | -0.611 | 0.190 | 0.081 |
| RUN 2 | A_SWING_HEDGED_NOAVG | 0.476 | -0.611 | 0.190 | 0.081 |
| RUN 2 | A_SWING_UNHEDGED_AVG | 0.304 | -0.723 | 0.122 | 0.063 |
| RUN 2 | B_HOLD_HEDGED_AVG | 1.480 | -3.151 | 0.592 | 0.361 |
| RUN 2 | B_HOLD_HEDGED_NOAVG | 1.480 | -3.151 | 0.592 | 0.361 |
| RUN 2 | B_HOLD_UNHEDGED_AVG | 1.371 | -3.442 | 0.548 | 0.304 |
| RUN 2 | B_SWING_HEDGED_AVG | 0.436 | -0.583 | 0.174 | 0.076 |
| RUN 2 | B_SWING_HEDGED_NOAVG | 0.436 | -0.583 | 0.174 | 0.076 |
| RUN 2 | B_SWING_UNHEDGED_AVG | 0.282 | -0.685 | 0.113 | 0.061 |

No portfolio reached 500, 1,000, or 10,000 USDT. The best portfolios crossed
200 USDT in both runs. `BEATS_BUY_AND_HOLD=NO`.

Representative `A_HOLD_HEDGED_AVG` holding/recovery diagnostics:

| Run | Mean hold | Max hold | Recovery P50 MAE | Within 50% | Unresolved rate |
|---|---:|---:|---:|---:|---:|
| RUN 1 | 130.34 h | 336 h | 807.33 h | 0% | 27.10% |
| RUN 2 | 141.99 h | 328 h | 1,020 h | 0% | 15.06% |

The historical recovery-time estimate is not calibrated adequately for use as
a trading-risk input.

## Testing and integrity

- Capital-growth test suite, local: `11 passed`.
- Capital-growth test suite, S13: `11 passed`.
- Governance prerequisite `indicator_parameter_search`: `44 passed`.
- Synthetic tests verify that primary entry, hedge entry, averaging, isolated
  liquidation, and accounting paths execute rather than remaining unreachable.
- Frozen configuration SHA256:
  `c7f44d8a022ceb6e882240c5c753dff60c9f0f91fdf5087c554a981db37bff57`.
- S13 artifact manifest: 1,583 files, 281,307,066 bytes, all size/SHA256
  checks PASS.

## Evidence

Small and representative evidence is committed under
[`docs/wip/TRADING-PILOT-CAPITAL-GROWTH-EXPERIMENT-1/results/`](TRADING-PILOT-CAPITAL-GROWTH-EXPERIMENT-1/results/).
Evidence commit: `4b15f3d7cb678a5d349d744584cd80c47b4a2c21`.

- `summary_v1.json` - complete machine-readable result, SHA256
  `fa20ccec272e655750dfc80cbafaeaf2ec2d5b36f2c36c91f9664d9ae2cc3a8`.
- `artifact_manifest_v1.json` - hashes for all 1,583 remote artifacts, SHA256
  `98d44badba76fc558163a663ed28cf6eda8b15b4e7bc6d976583435d695d14fb`.
- `frozen_config_v1.json` - configuration frozen after RUN 1.
- `control_comparisons_v1.json` - eight hedged/unhedged comparisons.
- `data_preflight_v1.json` - data coverage and limitations.
- `RUN1_DISCOVERY/portfolio_metrics.csv` and
  `RUN2_VALIDATION/portfolio_metrics.csv` - complete per-portfolio metrics,
  including holding time, recovery diagnostics, costs, thresholds, and risk
  exits.
- Equity-curve charts and representative PRIMARY/HEDGE charts, trade journals,
  and event journals for `A_HOLD_HEDGED_AVG`; the corresponding unhedged chart
  is included for comparison.

The full runtime tree remains at:

```text
S13:/var/tmp/traiding_pilot_ui_workspace/capital_growth_experiment_v1/
```

Invalidated intermediate runs remain preserved on S13 with explicit
`INVALIDATED_...` or `ABORTED_...` names and must not be used as final results.

## Limitations

- Maintenance margin uses a fixed low-notional tier instead of historical
  exchange tier changes.
- Intrabar liquidation uses mark OHLC rather than order-book depth.
- Historical fee changes and mark/index spread microstructure are
  approximated.
- RUN 2 is chronological validation within DEVELOPMENT, not an unlocked OOS
  evaluation.
- The baseline strategy is heuristic and does not use a CatBoost model.
- The historical recovery-time estimate has poor calibration and must not be
  treated as validated.

## Prioritized follow-up

1. Do not promote dynamic hedging: it lost to the unhedged control in every
   comparison and generated more liquidations.
2. Before any further hedge study, add dynamic maintenance-margin tiers,
   order-book-aware slippage/liquidation, and historical fee schedules.
3. Recalibrate or remove the recovery-time estimate as a risk input.
4. Test any revised hedge trigger only in a separately approved WIP with new
   frozen parameters; do not tune against RUN 2.
5. Keep research models, frozen results, S7, S13 runtime data, OOS, and
   confirmation sets outside the experiment unless separately authorized.

## Reporting

For each portfolio report:

- Final capital from 100 USDT
- PRIMARY and HEDGE realized PnL
- PRIMARY loss at hedge open/close
- Liquidations prevented versus control
- Liquidation and emergency-exit counts
- Hedge and averaging counts
- Mean/max holding time
- Recovery-time accuracy
- Maximum drawdown, profit factor, fees, funding, and slippage
- Hedged/unhedged returns and Buy & Hold comparison
- Equity, PRIMARY PnL, and HEDGE PnL charts
- Trade and state-transition journals
- Separate checks for 200, 500, 1000, and 10000 USDT thresholds

## Governance and safety

- Register exactly one active primary WIP before implementation.
- Do not close another WIP automatically.
- No real orders.
- No deployment or service restart.
- No S7 changes. S13 mutation is limited to the isolated experiment workspace.
- No modification of frozen artifacts.
- No blocked OOS/confirmation access.
- No claim of live readiness from a historical simulation.

## Acceptance criteria

The experiment must demonstrate, with full margin, liquidation, funding, fees,
and slippage accounting, whether dynamic hedging improves outcomes over the
unhedged control.

## RETURN

```text
WIP=TRADING-PILOT-CAPITAL-GROWTH-EXPERIMENT-1
STATUS=REVIEW
INITIAL_CAPITAL=100
LEVERAGE=10
HEDGE_MODE=ENABLED_IN_SIMULATOR
RUN1=2020-01-01..2021-01-01
RUN2=2021-01-01..2022-01-01
EVIDENCE_COMMIT=4b15f3d7cb678a5d349d744584cd80c47b4a2c21
CONFIG_SHA=c7f44d8a022ceb6e882240c5c753dff60c9f0f91fdf5087c554a981db37bff57
PRIMARY_PNL=A_HOLD_HEDGED_AVG_RUN1=-5.44;RUN2=-39.76
HEDGE_PNL=A_HOLD_HEDGED_AVG_RUN1=-1.78;RUN2=-0.02
AVERAGING_EFFECT=RUN1=-1.03/-4.28/-0.12/-3.30;RUN2=0/0/0/0
LIQUIDATIONS_PREVENTED=-16
LIQUIDATIONS_OCCURRED=65_HEDGED/49_UNHEDGED
FINAL_EQUITY_RANGE=103.17..269.84
MAX_DRAWDOWN=40.57_WORST;A_HOLD_HEDGED=26.73_RUN1/40.57_RUN2
BEATS_UNHEDGED_CONTROL=NO_0_OF_8
BEATS_BUY_AND_HOLD=NO
TESTS_RUN=LOCAL_11_PASS;S13_11_PASS;GOVERNANCE_PREREQ_44_PASS
TESTS_FAILED=0
ARTIFACT_MANIFEST=PASS_1583_FILES
S7_CHANGED=NO
FROZEN_RESEARCH_CHANGED=NO
OOS_OPENED=NO
LIVE_TRADING=NO
NEXT_WIP=none
```

## Decision

Historical simulation completed and returned as `REVIEW`. Dynamic hedging is
not supported by this baseline experiment. No follow-up WIP is activated.

## Superseded activation note

Activated for historical simulator build and RUN 1 → freeze → RUN 2.

## Roadmap update

ROADMAP_STATUS_UPDATED=YES

NEXT_WIP=none
