# WIP — TRADING-PILOT-CAPITAL-GROWTH-EXPERIMENT-1

STATUS=ACTIVE
STARTED_AT=2026-11-10
MODE=BUILD + RUN / HISTORICAL SIMULATION ONLY
INITIAL_CAPITAL=100 USDT
ASSET=ETHUSDT
LEVERAGE=10X_ISOLATED
HEDGE_MODE=ENABLED_IN_SIMULATOR
LIVE_TRADING=DISABLED

## Authorization

- `USER_APPROVAL=YES`
- `DATE=2026-11-10`
- `SCOPE=BUILD_AND_RUN_HISTORICAL_SIMULATION`
- S13 execution and modification authorized.
- S7 remains read-only and out of scope.
- Existing OOS/confirmation, CatBoost models, and frozen research artifacts
  remain immutable.

## Governance prerequisites

- `MULTITF-INDICATOR-PARAMETER-SEARCH-1`: CLOSED based on
  `wip_closure_v1.json`, accepted independent review, and commit `f232422`.
- `TRADING-PILOT-FROZEN-REGISTRY-RECONCILIATION-1`: CLOSED after V2 test-contract
  alignment; full suite `44 passed`.
- Frozen V2 registry matches current code with 0 mismatches.

## Work plan

- [ ] Commit governance/test-contract correction.
- [ ] Implement simulator package and risk engine.
- [ ] Add synthetic unit/integration tests.
- [ ] Run local test suite.
- [ ] Deploy code and dependencies to an isolated S13 workspace.
- [ ] Run data preflight for spot, futures mark, funding, fees, maintenance
  margin, and gaps.
- [ ] Execute RUN 1 discovery if preflight passes.
- [ ] Freeze configurations and SHA256.
- [ ] Execute RUN 2 validation without retuning.
- [ ] Produce equity curves, event journals, liquidation/cost reports, and
  controls.
- [ ] Set STATUS=REVIEW and stop.

## Mandatory data gate

RUN 1 requires:

- ETHUSDT price history covering both approved chronological years.
- Futures mark/contract price history or documented exchange-rule approximation.
- Historical funding.
- Fee and slippage inputs.
- Maintenance-margin tier inputs sufficient for 10x isolated liquidation.
- Gap coverage.

If any mandatory input is unavailable, RUN 1 stops with an explicit blocker.

## Safety

- No live orders, API keys, withdrawals, deploy of services, or trading.
- Do not modify S7.
- Do not open old OOS/confirmation.
- Do not modify CatBoost or frozen result artifacts.
- Do not tune on RUN 2.
- Keep all runtime outputs under an isolated S13 experiment directory.

## RETURN

```text
WIP=TRADING-PILOT-CAPITAL-GROWTH-EXPERIMENT-1
STATUS=IN_PROGRESS
LOCAL_BRANCH=wip/trading-pilot-capital-growth-experiment-1
LOCAL_HEAD=
BASE_MAIN=b3567bd4c952d65e55b05c909a6e0c11ac31fbce
INITIAL_CAPITAL=100
LEVERAGE=10
HEDGE_MODE=ENABLED_IN_SIMULATOR
RUN1=pending
RUN2=pending
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
