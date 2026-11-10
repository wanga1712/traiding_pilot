# WIP=TRADING-PILOT-CAPITAL-GROWTH-EXPERIMENT-1

STATUS=PLANNED
REGISTRATION=PROPOSED
ACTIVATED=NO

STARTED_AT=
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
- No S7/S13 changes.
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
RUN1=
RUN2=
CONFIG_SHA=
PRIMARY_PNL=
HEDGE_PNL=
AVERAGING_EFFECT=
LIQUIDATIONS_PREVENTED=
LIQUIDATIONS_OCCURRED=
FINAL_EQUITY=
MAX_DRAWDOWN=
BEATS_UNHEDGED_CONTROL=
BEATS_BUY_AND_HOLD=
OOS_OPENED=NO
LIVE_TRADING=NO
NEXT_WIP=none
```

## Decision

Proposed only. Not activated.

## Roadmap update

ROADMAP_STATUS_UPDATED=YES

NEXT_WIP=none
