# WIP — TRADING-PILOT-BASELINE-AND-AUDIT-1

STATUS=REVIEW
STARTED_AT=2026-11-10
MODE=SAFE / READ-FIRST / NO DEPLOY
REPOSITORY=wanga1712/traiding_pilot
TARGET_BRANCH=main

## Goal

Reconcile the local repository with GitHub, preserve the pre-existing local
worktree in a separate baseline branch, and audit the implementation actually
committed on `origin/main`.

The prior audit used stale `master`. No prior finding is accepted until it is
rechecked against `faacaf08b3eda971d972f4e4fb4c6fedecbf969d` or a later
explicitly recorded `origin/main`.

## Baseline facts

- Pre-audit local branch: `master`
- Pre-audit local HEAD: `4b82803cc4be233c6c9b831c7e8937fc2b507e71`
- Fetched `origin/main`: `faacaf08b3eda971d972f4e4fb4c6fedecbf969d`
- Control SHA verified: YES
- Local `master` versus `origin/main`: AHEAD=6, BEHIND=98
- Baseline branch: `baseline/trading-pilot-pre-main-20261110`
- Baseline commit: `5e05b7c79165981b5fd8b30a0e1f0eca133c3bae`
- Audit branch: `audit/trading-pilot-baseline-20261110`
- Audit base: `origin/main` at `faacaf08b3eda971d972f4e4fb4c6fedecbf969d`

The baseline commit contains 110 source/documentation/test files. It excludes
the 84.5 MB training Parquet, 25 training checkpoints totaling 221.9 MB,
logs, databases, `.env`, keys, and virtual environments. Secret screening
found only three documented placeholders and no literal credential.
Nothing was pushed.

## Execution plan

- [x] Verify repository and remote.
- [x] Read existing WIP controls before work.
- [x] Record status, branches, remotes, HEAD, and recent history.
- [x] Fetch `origin --prune` without merge, pull, or reset.
- [x] Compare local `master` with `origin/main`.
- [x] Create and secret-screen a separate baseline branch/commit.
- [x] Create a clean audit branch directly from `origin/main`.
- [x] Read current `AGENTS.md`, `ROADMAP.md`, and V2 architecture documents.
- [x] Audit OHLCV collection, sources, timeframes, completeness, and UTC handling.
- [x] Audit PostgreSQL schema, transactions, connections, and duplicate writes.
- [x] Audit indicators, DMA, causality, and look-ahead exposure.
- [x] Audit strategy construction, signals, and research/execution boundaries.
- [x] Audit backtesting, fees, funding, slippage, PnL, and risk management.
- [x] Audit API configuration, exceptions, timeouts, and secret handling.
- [x] Audit background processes, GUI, and resource lifecycle.
- [x] Inventory automatic tests and identify coverage gaps without a broad test run.
- [x] Reconcile findings with existing WIPs and `research_v2`.
- [x] Classify findings and produce prioritized regression-test requirements.
- [x] Write RETURN, update the canonical WIP report, and set STATUS=REVIEW.

## Constraints

- No changes to trading algorithms, model parameters, or frozen research.
- No opening blocked OOS or confirmation datasets.
- No real trading.
- No changes to S7 data or S13 runtime data.
- No migrations, deploy, or restart.
- No automatic start of the next WIP.
- No changes to existing WIP statuses without acceptance.

## Evidence

Detailed evidence and the defect register live in
`docs/wip/TRADING-PILOT-BASELINE-AND-AUDIT-1.md`.

## Audit result

- 11 confirmed defects: 1 CRITICAL, 7 HIGH, 3 MEDIUM.
- The same root cause produces six missing internal import targets:
  `resampling`, `annotations`, `visualization.chart_engine`,
  `visualization.dinapoli_live`, `visualization.zigzag_live`, and
  `zigzag.classic`.
- No literal secret was found in tracked source; host-key verification is
  nevertheless disabled in legacy deployment scripts.
- The current indicator calculations keep `available_at` at the source-bar
  close and preserve display displacement separately. No direct future-value
  formula was confirmed, but stale-cache and post-gap signal defects remain.
- The research policy and provisional execution results are already documented
  in their existing WIPs and were not rerun or altered.
- This audit is completed diagnostic work, not confirmation that the system is
  healthy or that its 252 inventoried test functions pass. No tests were run.

## RETURN

```text
WIP=TRADING-PILOT-BASELINE-AND-AUDIT-1
STATUS=REVIEW
LOCAL_BRANCH=audit/trading-pilot-baseline-20261110
LOCAL_HEAD=c21e0569e3474efb598bb58a4c181b34676e93e0
ORIGIN_MAIN_HEAD=c21e0569e3474efb598bb58a4c181b34676e93e0
BASELINE_COMMIT=5e05b7c79165981b5fd8b30a0e1f0eca133c3bae
AHEAD=0
BEHIND=0
FILES_CHANGED=WIP.md,docs/wip/TRADING-PILOT-BASELINE-AND-AUDIT-1.md,ROADMAP.md
CONFIRMED_DEFECTS=11
CRITICAL=1
HIGH=7
ALREADY_FIXED=1
LEGACY=3
TESTS_RUN=none
TESTS_FAILED=0
TEST_CONFIRMATION=NOT_PERFORMED
AUDIT_CONCLUSION=DIAGNOSTIC_ONLY_ACCEPTABLE_NOT_SYSTEM_HEALTH
UNVERIFIED=S7 PostgreSQL,runtime S13,S13/S7 live connectivity,actual resampling implementation,blocked OOS data
NEXT_WIP_PROPOSAL=TRADING-PILOT-IMPORT-AND-DATA-INTEGRITY-REPAIR-1
```
