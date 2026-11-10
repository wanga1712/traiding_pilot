# WIP — TRADING-PILOT-CAPITAL-GROWTH-EXPERIMENT-1

STATUS=REVIEW
STARTED_AT=2026-11-10
REVIEWED_AT=2026-11-10
MODE=BUILD + RUN / HISTORICAL SIMULATION ONLY
INITIAL_CAPITAL=100 USDT
ASSET=ETHUSDT
LEVERAGE=10X_ISOLATED
HEDGE_MODE=ENABLED_IN_SIMULATOR
LIVE_TRADING=DISABLED

## Outcome

The historical experiment completed with a reproducible PASS data gate and
hash-frozen RUN 1 configuration.

- RUN 1: 2020-01-01 through 2021-01-01 UTC.
- RUN 2: 2021-01-01 through 2022-01-01 UTC, without retuning.
- Dynamic hedging beat the matching unhedged control in `0/8` comparisons.
- Hedged portfolios had 65 liquidation events; unhedged controls had 49.
- The best result in both runs was `A_HOLD_UNHEDGED_AVG`.
- Best final equity: 269.84 USDT in RUN 1 and 206.28 USDT in RUN 2.
- Buy & Hold equivalents: 570.78 USDT in RUN 1 and 498.80 USDT in RUN 2.
- `BEATS_BUY_AND_HOLD=NO`; no portfolio reached 500, 1,000, or 10,000 USDT.

The conclusion is limited to this fixed baseline strategy and execution model.
It does not prove that every possible hedge design cannot work.

## Completed work

- [x] Closed the stale governance blocker with documented authority.
- [x] Implemented the two-position hedge/averaging simulator and risk engine.
- [x] Added synthetic coverage for entry, hedge, averaging, liquidation, and
  accounting paths.
- [x] Passed the capital-growth suite locally and on S13: 11 tests each.
- [x] Passed the governance prerequisite suite: 44 tests.
- [x] Passed the S13 spot/futures/mark/funding data preflight.
- [x] Executed RUN 1 and froze the configuration SHA256.
- [x] Executed RUN 2 without changing the frozen configuration.
- [x] Verified all 1,583 S13 artifacts against the inventory manifest.
- [x] Published compact evidence and charts with the WIP report.
- [x] Set `STATUS=REVIEW`; no next WIP was started.

## Data and integrity

| Field | Value |
|---|---:|
| Spot coverage | 99.7866% |
| Futures coverage | 100% |
| Mark-price coverage | 99.9950% |
| Funding rows | 2,193 / 2,193 |
| Duplicate rows | 0 |
| Artifact count | 1,583 |
| Manifest verification | PASS |

The full runtime artifact tree remains at:

```text
S13:/var/tmp/traiding_pilot_ui_workspace/capital_growth_experiment_v1/
```

## Safety

- No live orders, withdrawals, deployment, or service restart.
- S7 was not changed.
- S13 mutation was limited to the isolated experiment workspace.
- OOS/confirmation remained closed.
- No CatBoost retraining or frozen-research modification.
- No tuning was performed after RUN 2 was observed.

## Artifacts

- WIP report:
  `docs/wip/TRADING-PILOT-CAPITAL-GROWTH-EXPERIMENT-1.md`
- Summary and evidence:
  `docs/wip/TRADING-PILOT-CAPITAL-GROWTH-EXPERIMENT-1/results/`
- Local report suite: 11 PASS.
- S13 report suite: 11 PASS.

## RETURN

```text
WIP=TRADING-PILOT-CAPITAL-GROWTH-EXPERIMENT-1
STATUS=REVIEW
LOCAL_BRANCH=wip/trading-pilot-capital-growth-experiment-1
BASE_MAIN=48d7b2abdfe4ea4a1a3b301be149a0993ee5a6fb
SIMULATOR_BASELINE=6fe32abbf2ef53eb3914f99ef403850a3ba220e0
EVIDENCE_COMMIT=4b15f3d7cb678a5d349d744584cd80c47b4a2c21
INITIAL_CAPITAL=100
LEVERAGE=10
HEDGE_MODE=ENABLED_IN_SIMULATOR
RUN1=2020-01-01..2021-01-01
RUN2=2021-01-01..2022-01-01
CONFIG_SHA=c7f44d8a022ceb6e882240c5c753dff60c9f0f91fdf5087c554a981db37bff57
PRIMARY_PNL=A_HOLD_HEDGED_AVG_RUN1=-5.44;RUN2=-39.76
HEDGE_PNL=A_HOLD_HEDGED_AVG_RUN1=-1.78;RUN2=-0.02
AVERAGING_EFFECT=RUN1=-1.03/-4.28/-0.12/-3.30;RUN2=0/0/0/0
LIQUIDATIONS_PREVENTED=-16
LIQUIDATIONS_OCCURRED=65_HEDGED/49_UNHEDGED
FINAL_EQUITY_RANGE=103.17..269.84
MAX_DRAWDOWN=40.57_WORST
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
