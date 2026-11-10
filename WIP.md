# WIP — TRADING-PILOT-IMPORT-AND-DATA-INTEGRITY-REPAIR-1

STATUS=REVIEW
STARTED_AT=2026-11-10
MODE=SAFE / LOCAL-FIRST / NO DEPLOY / NO RESEARCH RERUN
REPOSITORY=wanga1712/traiding_pilot
TARGET_BRANCH=main

## Goal

Restore the implementation that current `main` cannot import, protect secrets,
and repair the confirmed data-integrity defects from
`TRADING-PILOT-BASELINE-AND-AUDIT-1` before any research result is reconsidered.

## Accepted parent

- Parent WIP: `TRADING-PILOT-BASELINE-AND-AUDIT-1`
- Parent status: ACCEPTED / CLOSED
- Audited commit: `c21e0569e3474efb598bb58a4c181b34676e93e0`
- Accepted diagnostics: 11 confirmed defects
- Limit: audit-only; no tests were executed and system health was not confirmed

## Scope

### Stage 1 — restoration and protection

- Restore the 22 missing project files from S13 read-only runtime source after
  hash and compatibility review.
- Add a reproducible dependency manifest.
- Add a clean-import smoke test.
- Restore ignore rules for secrets, keys, logs, databases, data, checkpoints,
  build outputs, IDE state, and virtual environments.

### Stage 2 — correctness guards

- Fix the OOS interval-overlap guard.
- Replace partial in-memory cache fingerprints with full-content fingerprints.
- Make OHLCV cache writes atomic and bounded.
- Correct DMA and Stochastic state behavior across candle gaps.
- Add focused regression tests.

### Stage 3 — verification

- Run targeted unit and integration tests.
- Run local import checks from the project package root.
- Do not run model training, OOS/confirmation access, research pipelines,
  deployments, service restarts, database migrations, or live trading.

## Constraints

- Do not modify CatBoost models, model parameters, predictions, frozen research
  evidence, or historical research result artifacts.
- Do not open blocked OOS or confirmation datasets.
- Do not modify S7 data or S13 runtime data.
- S13 may be read only to restore missing source files and verify hashes.
- Do not deploy or restart any service.
- Do not automatically start another WIP after this one.
- Do not overwrite prior research outputs.

## Acceptance criteria

- All six previously missing import targets resolve from a clean checkout.
- Dependency installation is described by versioned project requirements.
- Secret/runtime paths are ignored and cannot be staged by a broad `git add`.
- OOS overlap, cache invalidation, atomic cache recovery, and post-gap signal
  tests pass.
- Existing frozen artifacts and model files remain byte-for-byte unchanged.
- No research rerun, deploy, S7/S13 mutation, or live trade occurs.

## Evidence

Audit inputs:
`docs/wip/TRADING-PILOT-BASELINE-AND-AUDIT-1.md`

Restoration source:
`sergey@s13:/var/tmp/traiding_pilot_ui_workspace/phase3_staging/`

Implementation evidence and RETURN will be recorded in
`docs/wip/TRADING-PILOT-IMPORT-AND-DATA-INTEGRITY-REPAIR-1.md`.

## Verification summary

- Restored 22 source/schema files from S13 read-only source with hash checks.
- Import smoke: PASS for 10 data/UI/wave consumers.
- Focused integrity, OOS, indicator-engine, and trading-run tests: 61 passed.
- Non-research test groups: 186 passed.
- Composite-signal suite: 49 passed.
- Indicator parameter-search suite: 34 passed, 10 failed.
- Total: 269 passed, 10 failed.

The 10 failures are confined to existing frozen registry/spec and routing
comparisons in `indicator_parameter_search`. They are not repaired here because
doing so requires research-artifact reconciliation outside this WIP.

GitHub repository default branch was changed from `master` to `main`.

No model, frozen result, S7 dataset, or S13 runtime data was changed. No
research pipeline, OOS/confirmation run, deploy, restart, or migration ran.

## RETURN

```text
WIP=TRADING-PILOT-IMPORT-AND-DATA-INTEGRITY-REPAIR-1
STATUS=REVIEW
LOCAL_BRANCH=wip/trading-pilot-import-data-integrity-repair-1
LOCAL_HEAD=a24442fe1c6b6658545fb763d31ad9e4f9f8a544
BASE_MAIN=b83393dace03943da0527c2c732ecc3d9cb31c53
PARENT_CLOSED=TRADING-PILOT-BASELINE-AND-AUDIT-1
RESTORED_MODULES=PASS_22_FILES
SECRETS_PROTECTED=PASS_TESTS
OOS_GUARD=PASS_TESTS
CACHE_INVALIDATION=PASS_TESTS
GAP_HANDLING=PASS_TESTS
DEFAULT_BRANCH=main
TESTS_RUN=279
TESTS_PASSED=269
TESTS_FAILED=10
KNOWN_FAILURES=indicator_parameter_search_frozen_registry_spec_and_routing_mismatch
IMPLEMENTATION_COMMIT=a24442fe1c6b6658545fb763d31ad9e4f9f8a544
RESEARCH_RERUN=none
DEPLOY=none
S7_S13_MUTATION=none
NEXT_WIP=none
```
