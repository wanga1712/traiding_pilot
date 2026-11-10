# WIP=TRADING-PILOT-BASELINE-AND-AUDIT-1

STATUS=REVIEW

STARTED_AT=2026-11-10
CLOSED_AT=

## Goal

Establish the true repository baseline, preserve pre-existing local changes
outside `main`, and audit the implementation committed on `origin/main` before
any functional repair is authorized.

## Context

The previous audit only partially used the obsolete local `master`. The local
checkout had extensive uncommitted work and was 6 commits ahead and 98 commits
behind `origin/main` at audit start. The current repository authority is Git
on `origin/main`; S13 is compute/research/UI and S7 is the market-data and
PostgreSQL authority.

## Inputs

- Repository: `wanga1712/traiding_pilot`
- Target branch: `origin/main`
- Verified control SHA: `faacaf08b3eda971d972f4e4fb4c6fedecbf969d`
- Current V2 architecture and research-governance documents
- Existing WIP reports and implemented `research_v2` modules

## Constraints

- SAFE / READ-FIRST / NO DEPLOY
- No trading algorithm, model parameter, or frozen research changes.
- No access to blocked OOS or confirmation data.
- No real trading.
- No S7 data or S13 runtime data changes.
- No database migration, deployment, or restart.
- No push, merge, pull, or reset.
- No automatic start of the next WIP.
- Preserve runtime artifacts, secrets, databases, and large datasets outside Git.

## Non-goals

- Implementing fixes or modifying trading behavior.
- Running the full automated test suite, benchmarks, or production smoke tests.
- Declaring research profitability or model readiness.
- Changing statuses of existing WIPs.

## Baseline preservation

- Pre-audit branch: `master`
- Pre-audit HEAD: `4b82803cc4be233c6c9b831c7e8937fc2b507e71`
- Baseline branch: `baseline/trading-pilot-pre-main-20261110`
- Baseline commit: `5e05b7c79165981b5fd8b30a0e1f0eca133c3bae`
- Baseline scope: 110 source, documentation, and test files
- Excluded: `data/training_dataset.parquet` (84.5 MB), 25 training
  checkpoints (221.9 MB), logs, `.env`, keys, databases, and virtual environments
- Secret scan: three README placeholder matches; no literal credential found
- GitHub push: NO

## Implementation / Experiment

This WIP is an audit only. It collects evidence by inspecting Git and the
actual `origin/main` tree, without executing production jobs or opening
restricted data.

### Audit plan

- [x] Verify repo, remotes, branch, HEAD, and WIP controls.
- [x] Fetch `origin --prune`; do not merge or reset.
- [x] Compare local work with `origin/main`.
- [x] Preserve and secret-screen local work in a baseline commit.
- [x] Start a new audit branch at the exact `origin/main` commit.
- [x] Read current governance and architecture authority.
- [x] Market data and OHLCV.
- [x] PostgreSQL and persistence.
- [x] Indicators, DMA, causality, and look-ahead.
- [x] Strategy/signal construction and research/execution separation.
- [x] Backtests, costs, funding, slippage, PnL, and risk.
- [x] API configuration, timeouts, exceptions, and secrets.
- [x] Background processes, GUI, and resource lifecycle.
- [x] Automatic test inventory and coverage adequacy.

## Anti-leakage rules

Do not read or evaluate blocked OOS/confirmation data. Treat retrospective
labels and future outcomes as unavailable at feature or signal time. Preserve
existing research freezes and dataset access guards.

## Acceptance criteria

- Baseline is preserved and no secret/runtime artifact is committed.
- Local work is reconciled with the actual `origin/main` SHA.
- Every reported defect is tied to current code with file and line evidence.
- Findings are classified as CONFIRMED, SUSPECTED, ALREADY_FIXED, LEGACY, or
  NOT_APPLICABLE.
- A prioritized repair and regression-test list is available.
- No functional change is made before separate approval.

## Results

All findings below were checked against `origin/main` at
`faacaf08b3eda971d972f4e4fb4c6fedecbf969d`. No blocked OOS dataset was
opened, no service was contacted, no migration was run, and no production
artifact was modified.

### Audit summary by area

| Area | Result |
|---|---|
| OHLCV source | S7 canonical 1m path is declared correctly; S13 cache is disposable. The implementation cannot import because `research_v2.resampling` is absent. |
| OHLCV completeness/UTC | Requested cache range is normalized to UTC and preflight checks monotonicity, duplicate timestamps, and OOS timestamps. Exact resampling/completeness could not be verified because the implementation is missing. |
| PostgreSQL | No PostgreSQL DDL/DML or connection code exists in current Git. S7's `market.sqlite3` is used as a partition manifest; a missing `annotations` module prevents inspection of the UI's `S7PostgresAnnotationStore`. Runtime DB state was not touched. |
| Indicators/DMA | Closed-bar `available_at` semantics and display displacement are separated correctly. Two cross-gap signal defects and incomplete cache invalidation remain. |
| Research/execution boundary | Current policy and execution code is research-only, 1x, one-position, and does not submit orders. The OOS range guard has an overlap hole. |
| Costs/PnL/risk | Fees and slippage accounting is implemented and tested. Historical funding is deliberately absent from primary PnL. No liquidation/leverage/risk engine is part of this implementation; those remain planned roadmap work. |
| API/secrets | No tracked `.env`, key, PEM, DB, or literal credential was found, but `.gitignore` does not protect the untracked local credential/runtime files. Legacy deploy scripts pin the obsolete 10.8.x host, disable host checking, and omit process timeouts. |
| GUI/lifecycle | The current UI entry point imports five absent modules, cannot be reproduced from a clean checkout, and is launched by `pkill`/`nohup` rather than a supervised service. |
| Tests | 43 test-related Python files and 252 test functions are present, but clean collection is invalidated by missing imports. No tests cover the packaging, cache, OOS-overlap, or deployment failures below. |

## Defect register

### TPA-001

- **Severity:** CRITICAL
- **Status:** CONFIRMED
- **File:line:** `phase3_staging/crypto_trading_bot/research_v2/market_data/bars_service.py:13`;
  `phase3_staging/crypto_trading_bot/research_v2/visualization/expert_app.py:12-15,32-33`;
  `phase3_staging/crypto_trading_bot/research_v2/reversal_events/build_dataset.py:13,30`;
  `phase3_staging/crypto_trading_bot/research_v2/wave_engine/freeze_dataset.py:13,24`
- **Actual:** A static import audit against `HEAD` found six imported project
  modules that are absent from the Git tree: `resampling`, `annotations`,
  `visualization.chart_engine`, `visualization.dinapoli_live`,
  `visualization.zigzag_live`, and `zigzag.classic`.
- **Expected:** Every internal import resolves from the same clean Git checkout.
- **Evidence/reproduction:** `git ls-tree -r --name-only HEAD` contains 210
  `research_v2` Python files, but none of the six targets. A clean import of
  `market_data.bars_service` or `visualization.expert_app` therefore raises
  `ModuleNotFoundError` before any market data can be read.
- **Consequences:** Data loading, the chart UI, wave-dataset rebuilding, and
  portions of test collection fail from `origin/main`. The previously audited
  stale `master` cannot be used to infer current DB/UI correctness.
- **Fix:** Recover the authoritative V2 implementations from the approved
  source or refactor imports to existing current modules. Do not copy them
  blindly from stale `master` or runtime without hash/parity review.
- **Regression test:** In a clean environment, import
  `market_data.bars_service`, `visualization.expert_app`,
  `reversal_events.build_dataset`, and `wave_engine.freeze_dataset`.

### TPA-002

- **Severity:** HIGH
- **Status:** CONFIRMED
- **File:line:** repository root; `README.md:1-16` has no installation contract
- **Actual:** `git ls-tree` contains no `requirements*.txt`, `pyproject.toml`,
  `setup.py`, `Pipfile`, `poetry.lock`, or equivalent environment lock.
- **Expected:** A fresh checkout has a versioned, reproducible dependency set,
  including NumPy, pandas, PyArrow, Dash, Plotly, Flask, CatBoost, and test
  dependencies used by current code.
- **Evidence/reproduction:** `git ls-tree -r --name-only HEAD` returns zero
  dependency manifests. Deploy scripts rely on pre-existing `.venv` and
  `.venv_bakeoff` directories under `/var/tmp`.
- **Consequences:** Clean validation, disaster recovery, and model/evidence
  reproducibility depend on undocumented mutable runtime environments.
- **Fix:** Add a pinned project and test dependency manifest plus a clean-install
  smoke procedure.
- **Regression test:** Create a fresh virtual environment from the manifest and
  import the public packages before running unit tests.

### TPA-003

- **Severity:** HIGH
- **Status:** CONFIRMED
- **File:line:** `phase3_staging/crypto_trading_bot/research_v2/composite_signal_search/oos_guard.py:41-56`
- **Actual:** `assert_no_oos_bounds` rejects only windows whose start is at or
  after OOS start. The second condition is
  `e > oos_end and s >= oos_start`, so a window with
  `s < oos_start < oos_end_window < e` is accepted.
- **Expected:** Any interval overlap with the locked OOS interval is rejected,
  including partial overlap.
- **Evidence/reproduction:** With the current OOS start
  `2023-06-20T06:08:00Z` from
  `reversal_signal_study/config.py:23-26`, the call with start
  `2023-01-01` and end `2023-07-01` passes both checks despite opening OOS rows.
- **Consequences:** A future caller can read locked OOS data through an
  overlapping range while the guard appears to permit the call.
- **Fix:** Reject `start < oos_end and end > oos_start`; treat invalid or
  timezone-mixed bounds as fail-closed rather than silently returning.
- **Regression test:** Cover fully before, partial leading overlap, exact
  boundaries, fully inside, partial trailing overlap, and fully after OOS.

### TPA-004

- **Severity:** HIGH
- **Status:** CONFIRMED
- **File:line:** `phase3_staging/crypto_trading_bot/research_v2/indicator_engine/cache.py:43-48`;
  `phase3_staging/crypto_trading_bot/research_v2/inverse_predictors/batch_thresholds.py:58-65,110-126`
- **Actual:** Indicator cache keys use only length, first/last timestamps, and
  first/last closes. Inverse-threshold cache keys use only timeframe,
  parameters, length, and first/last close times. Middle-bar content is absent.
- **Expected:** Cache identity changes whenever any OHLCV value that affects the
  calculation changes.
- **Evidence/reproduction:** Run `compute_series(..., use_cache=True)` on a bar
  list, mutate only a middle close, and run again with the same endpoints. The
  second call returns the first result. The same scenario defeats the inverse
  threshold cache.
- **Consequences:** Backfills, corrected candles, or reprocessed bars can
  silently reuse stale indicators/signals and contaminate features, validation,
  or model inputs.
- **Fix:** Hash all ordered timestamp/open/high/low/close/volume values, or use
  an immutable dataset version plus verified content hash.
- **Regression test:** Middle-price, middle-volume, and middle-timestamp
  mutations must each produce a cache miss and recomputed values.

### TPA-005

- **Severity:** HIGH
- **Status:** CONFIRMED
- **File:line:** `phase3_staging/crypto_trading_bot/research_v2/indicator_engine/dma.py:26,44-69`
- **Actual:** Raw `sma()` is computed across gaps. Current validity only checks
  the current DMA window, while `prev_price`/`prev_dma` are read from `i-1`
  without requiring the previous bar to belong to the same contiguous segment.
- **Expected:** Cross primitives at the first valid post-gap bar either restart
  without a predecessor or compare only same-segment values.
- **Evidence/reproduction:** For period 3, insert a gap before bar 3. Bar 5 has
  a contiguous current window and becomes valid, but its predecessor and
  previous DMA came from across the gap; a synthetic clean crossing can emit
  `PRICE_CROSS_UP_DMA`/`PRICE_CROSS_DOWN_DMA`.
- **Consequences:** False signals at gap recovery boundaries can enter research
  signal banks and composite search.
- **Fix:** Compute SMA segment-aware or require `same_segment(gap_flags, i-1, i)`
  before expressing a cross; keep values valid without inventing a signal.
- **Regression test:** Compare a no-gap series with a gapped series containing
  identical post-gap prices and assert no cross primitive at first recovery.

### TPA-006

- **Severity:** HIGH
- **Status:** CONFIRMED
- **File:line:** `phase3_staging/_deploy_cockpit_s13.py:9-27`;
  `phase3_staging/_deploy_feature_bank_s13.py:9-30`;
  `phase3_staging/_deploy_oscillator_event_study_s13.py:9-40`;
  `phase3_staging/_discovery_watch_and_freeze.py:14-41`
- **Actual:** Several deployment scripts hard-code `sergey@10.8.0.13`, pass
  `StrictHostKeyChecking=no`, and run SSH/SCP without connection or process
  timeouts.
- **Expected:** Use the current V2 Tailscale alias/config, verify host keys,
  run in batch mode, and bound every remote operation.
- **Evidence/reproduction:**
  `docs/architecture/RUNTIME_HOST_MAP_V2.md:3-8` calls old 10.8.x addresses
  historical; the scripts still target them.
- **Consequences:** Deployment can fail on current hosts while silently trusting
  an incorrect SSH endpoint, or hang indefinitely waiting for network/auth.
- **Fix:** Centralize host configuration, use `s13`/the approved SSH config,
  enable host verification, and add `BatchMode`, `ConnectTimeout`,
  `ServerAliveInterval`, and subprocess timeouts.
- **Regression test:** Static deploy-config test asserts no 10.8.x literals,
  no `StrictHostKeyChecking=no`, and that every `ssh`/`scp` wrapper has a timeout.

### TPA-007

- **Severity:** HIGH
- **Status:** CONFIRMED
- **File:line:** `phase3_staging/_discovery_watch_and_freeze.py:339-344,426,432`
- **Actual:** The watcher's success path unconditionally runs `git add`,
  `git commit`, and `git push origin main`, then reports
  `PUSHED_TO_GITHUB=YES`.
- **Expected:** No automatic commit or push. Freeze/commit/push must be a
  separately reviewed action.
- **Evidence/reproduction:** `main()` calls `commit_and_push()` after checks; the
  helper directly executes all three Git mutations.
- **Consequences:** An unattended or mistaken run can publish research artifacts
  and alter `main` without user acceptance, contrary to the current WIP control.
- **Fix:** Remove the push, gate commit behind an explicit user flag, and run all
  Git mutations externally after review.
- **Regression test:** Dry-run with a mocked Git executable must assert that no
  `add`, `commit`, or `push` command is invoked by default.

### TPA-008

- **Severity:** MEDIUM
- **Status:** CONFIRMED
- **File:line:** `phase3_staging/crypto_trading_bot/research_v2/market_data/bars_service.py:165,196-210`
- **Actual:** Remote monthly Parquet is copied directly to its final cache path
  with `scp` and no timeout; local copy uses direct `write_bytes`. The resampled
  cache is also overwritten in place with `pq.write_table`.
- **Expected:** Download/write to a unique temporary file, validate readability,
  fsync if appropriate, and atomically replace the cache target. Remote commands
  have finite timeouts.
- **Evidence/reproduction:** An interrupted SCP can leave a partial file; the
  next invocation returns it because `local_path.exists()` is true, then
  `pq.read_table` fails or a partial resampled table is consumed.
- **Consequences:** A transient network failure or process kill can poison the
  disposable cache until manual deletion.
- **Fix:** Atomic temp+replace, Parquet validation, and bounded SCP.
- **Regression test:** Inject a truncated Parquet and failed SCP; assert the old
  valid cache remains intact or the temporary file is removed.

### TPA-009

- **Severity:** MEDIUM
- **Status:** CONFIRMED
- **File:line:** `phase3_staging/crypto_trading_bot/research_v2/dinapoli_when_reconstruction/signals_ext.py:114-155`
- **Actual:** `was_os` and `was_ob` state is retained when samples are invalid
  across a data gap. The post-gap signal loop does not reset or verify segment
  continuity before emitting from that remembered state.
- **Expected:** Signal-state memory starts fresh after a gap/insufficient-history
  segment.
- **Evidence/reproduction:** Set oversold before a gap, insert a gap, then
  produce a post-gap K/D crossover; the function can emit `UP` from the
  pre-gap oversold flag.
- **Consequences:** Signals at recovery boundaries depend on stale pre-gap
  context.
- **Fix:** Reset both flags when the current source index starts a new segment
  or when required history is invalid.
- **Regression test:** Gap before crossover must not emit; the equivalent
  contiguous series must emit.

### TPA-010

- **Severity:** MEDIUM
- **Status:** CONFIRMED
- **File:line:** `ROADMAP.md:14-18,1008-1010,1560`;
  `docs/architecture/TRADING_PROJECT_HANDOFF_V2.md:3-5`
- **Actual:** The top of the roadmap names
  `PROBABILITY-TRADING-POLICY-RESEARCH-1` (REVIEW) as current primary, while
  the Phase 8a entry and index still mark
  `MULTITF-INDICATOR-PARAMETER-SEARCH-1` as ACTIVE. The V2 handoff still names
  old authority `a5816ad7…`.
- **Expected:** One unambiguous active/current primary WIP and one current
  authority pointer.
- **Evidence/reproduction:** Direct comparison of the cited lines.
- **Consequences:** An agent can select the wrong WIP, violate the
  one-active-primary rule, or cite stale authority.
- **Fix:** Reconcile statuses and authority only after user acceptance; add a
  CI documentation-consistency check.
- **Regression test:** Parse roadmap headings/index and assert at most one
  ACTIVE primary plus matching current-WIP/authority references.

### TPA-011

- **Severity:** HIGH
- **Status:** CONFIRMED
- **File:line:** `.gitignore:1-3`
- **Actual:** The current `origin/main` ignore file contains only
  `__pycache__/` and `*.pyc`. Local secret and runtime paths are consequently
  reported as non-ignored untracked files, including `api_keys.env`,
  `crypto_trading_bot/database/db_credintials.env`,
  `crypto_trading_bot/private_key.pem`,
  `crypto_trading_bot/public_key.pem`, `app.log`, and the 84.5 MB
  `data/training_dataset.parquet`.
- **Expected:** Credentials, private keys, databases, caches, logs, large data,
  build outputs, IDE state, and virtual environments are ignored by default.
- **Evidence/reproduction:** `git check-ignore -v -- api_keys.env app.log
  data/training_dataset.parquet crypto_trading_bot/private_key.pem` returns no
  match. `git status --porcelain=v1 -uall` reports 368 non-ignored untracked
  paths from the retained old workspace.
- **Consequences:** A future `git add -A` can commit live credentials or
  multi-hundred-megabyte runtime data into Git.
- **Fix:** Restore explicit ignore rules for secrets, keys, databases, data,
  logs, checkpoints, build products, IDE files, and virtual environments; add a
  pre-commit secret scan.
- **Regression test:** Assert representative secret/runtime paths are ignored
  and `git add -An` stages none of them.

## Classification

| Class | Count | Notes |
|---|---:|---|
| CONFIRMED | 11 | TPA-001 through TPA-011 |
| SUSPECTED | 0 | No unverified issue was promoted to a defect |
| ALREADY_FIXED | 1 | `AGENTS.md`, `ROADMAP.md`, and V2 architecture authority exist on `main` even though absent from stale `master` |
| LEGACY | 3 | Stale top-level `crypto_trading_bot/database`, `crypto_trading_bot/trading`, and `gui` implementations exist only off current `main`; they are not treated as current defects |
| NOT_APPLICABLE | 3 | No current live-order API, no implemented PostgreSQL trading-run store in Git, and no current liquidation/leverage risk engine |

## Non-defect limitations

- Exact historical futures funding is explicitly excluded from the primary
  provisional execution PnL and reported only as a separate 1 bp stress
  diagnostic (`provisional_execution/evaluation.py:197-200,291-296`).
- The provisional and policy simulators use 1x, one position, no averaging,
  no stops, and no liquidation search. This is the declared current research
  scope, not a hidden live-execution claim.
- Confirmation marking before execution in
  `policy_research/run_policy_research.py:180-191` is an intentional
  at-most-once OOS barrier, not counted as a defect.

## Tests

Static inventory only; no tests were run because the user did not request test
execution and the repository has no dependency manifest.

- Test-related Python files: 43 (including package/config files)
- Test functions: 252
- Current blockers to collection: missing imports in TPA-001
- Missing regressions: clean import/dependency install, full-content cache
  invalidation, OOS interval overlap, post-gap DMA/Stochastic state, atomic cache
  recovery, deployment host/timeout policy, and automatic-push prohibition

## Prioritized repair order

1. Restore or replace the six missing modules and add a clean-import gate.
2. Add a pinned environment manifest and clean-install CI.
3. Fix the OOS interval-overlap guard before any future research access.
4. Replace partial cache fingerprints and make cache writes atomic.
5. Correct DMA/Stochastic post-gap semantics.
6. Harden deployment transport and remove automatic Git push.
7. Reconcile roadmap/WIP authority after user acceptance.

## Artifacts

- This report
- Root control/plan: `WIP.md`
- Local Git branches and commits listed above; no remote upload

## Browser/runtime evidence

Not applicable; no deploy, restart, UI launch, or runtime mutation is allowed.

## Git commit

GIT_COMMIT=faacaf08b3eda971d972f4e4fb4c6fedecbf969d (audit base); audit-doc commit recorded on the local branch

## RETURN

```text
WIP=TRADING-PILOT-BASELINE-AND-AUDIT-1
STATUS=REVIEW
LOCAL_BRANCH=audit/trading-pilot-baseline-20261110
LOCAL_HEAD=changes-committed-after-audit
ORIGIN_MAIN_HEAD=faacaf08b3eda971d972f4e4fb4c6fedecbf969d
BASELINE_COMMIT=5e05b7c79165981b5fd8b30a0e1f0eca133c3bae
AHEAD=audit-doc-commits
BEHIND=0
FILES_CHANGED=WIP.md,docs/wip/TRADING-PILOT-BASELINE-AND-AUDIT-1.md,ROADMAP.md
CONFIRMED_DEFECTS=11
CRITICAL=1
HIGH=7
ALREADY_FIXED=1
LEGACY=3
TESTS_RUN=none
TESTS_FAILED=0
UNVERIFIED=S7 PostgreSQL,runtime S13,S13/S7 live connectivity,actual resampling implementation,blocked OOS data
NEXT_WIP_PROPOSAL=TRADING-PILOT-IMPORT-AND-DATA-INTEGRITY-REPAIR-1
```

## Decision

Audit complete; awaiting user review. No functional repair is authorized by
this WIP.

## Roadmap update

ROADMAP_STATUS_UPDATED=YES

NEXT_WIP=TRADING-PILOT-IMPORT-AND-DATA-INTEGRITY-REPAIR-1 (proposal only; do not start automatically)
