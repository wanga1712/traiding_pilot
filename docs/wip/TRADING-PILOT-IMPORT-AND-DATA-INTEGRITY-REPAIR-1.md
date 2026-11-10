# WIP=TRADING-PILOT-IMPORT-AND-DATA-INTEGRITY-REPAIR-1

STATUS=CLOSED

STARTED_AT=2026-11-10
CLOSED_AT=2026-11-10

## Goal

Restore a runnable current implementation and repair the data-integrity defects
confirmed by the accepted baseline audit, without changing models, frozen
research results, or runtime hosts.

## Context

`TRADING-PILOT-BASELINE-AND-AUDIT-1` is accepted at audited commit
`c21e0569e3474efb598bb58a4c181b34676e93e0`. It confirmed missing imports,
missing dependency manifests, incomplete secret protection, an OOS overlap
guard defect, stale cache keys, gap-crossing signal state, and unsafe legacy
automation.

The repair WIP starts from `main` at
`b83393dace03943da0527c2c732ecc3d9cb31c53`.

## Inputs

- Accepted audit report:
  `docs/wip/TRADING-PILOT-BASELINE-AND-AUDIT-1.md`
- Current Git implementation on `main`
- Read-only S13 runtime source under
  `/var/tmp/traiding_pilot_ui_workspace/phase3_staging`
- Existing frozen WIP definitions and tests

## Constraints

- No CatBoost retraining or model-parameter changes.
- No OOS or confirmation access.
- No historical research rerun or artifact overwrite.
- No S7/S13 mutation.
- No deploy, restart, migration, or live trading.
- No automatic start of a later WIP.

## Implementation plan

- [x] Verify S13 source identities and file hashes.
- [x] Restore missing modules:
      `resampling`, `annotations`, `chart_engine`, `dinapoli_live`,
      `zigzag_live`, and `zigzag.classic`.
- [x] Add dependency manifest and clean-import test.
- [x] Restore `.gitignore` protections and add a staging guard test.
- [x] Fix OOS interval-overlap rejection.
- [x] Replace partial cache fingerprints with content fingerprints.
- [x] Make OHLCV cache operations atomic and bounded.
- [x] Correct DMA and Stochastic post-gap behavior.
- [x] Run focused tests and local import checks.
- [x] Record evidence, set STATUS=REVIEW, and stop.

## Acceptance criteria

- Missing imports are resolved from current Git.
- Dependency manifest enables a clean environment.
- Secret/runtime files are ignored.
- OOS intervals cannot partially overlap a locked window.
- Middle-bar mutations invalidate cache entries.
- Cache interruption preserves the last valid cache.
- No false DMA/Stochastic signal is emitted at a gap recovery.
- No model, frozen research artifact, S7 data, or S13 runtime data changes.

## Results

### Restoration

Verified the S13 identity as `sergey` on
`sergey-System-Product-Name`. All source reads were from read-only paths under
`/var/tmp/traiding_pilot_ui_workspace/phase3_staging`.

Restored 22 source/schema files:

- `annotations`: 4 files
- `dinapoli`: 7 files
- `resampling`: 2 files
- `visualization`: 3 files
- `zigzag`: 6 files

All restored files matched their S13 SHA256 values before compatibility
patches. The patched files are limited to the annotation SSH transport,
resampling validation, CLI SSH defaults, and the audited correctness repairs.
Exact workspace hashes are recorded in `restored_source_hashes_v1.json`.

### Fixes

- Added pinned `requirements.txt` and `requirements-test.txt`.
- Expanded `.gitignore` to block credentials, keys, databases, logs, data,
  checkpoints, virtual environments, IDE state, and test temporary folders.
- Annotation PostgreSQL transport now uses `wanga@s7` by default, environment
  overrides, `BatchMode=yes`, `ConnectTimeout=15`, and a subprocess timeout.
- OOS interval checks reject partial overlap as well as windows starting in or
  after the locked OOS interval.
- Indicator and inverse-threshold cache keys hash all ordered OHLCV fields.
- OHLCV resampling validates strictly increasing unique source timestamps.
- Monthly and resampled Parquet cache writes use validated temporary files and
  atomic replacement; remote SCP is bounded and uses batch mode.
- DMA cross/slope values do not bridge a candle gap.
- Stochastic OB/OS memory resets at a candle gap.
- Composite durability `fsync` is portable on Windows.

### Verification

| Suite | Result |
|---|---|
| Import smoke | 10/10 PASS |
| Focused integrity/OOS/indicator/trading-run | 61 passed |
| Non-research test groups | 186 passed |
| Composite-signal | 49 passed |
| Indicator parameter search | 34 passed, 10 failed |
| Total | 269 passed, 10 failed |

The 10 failures are pre-existing research-artifact reconciliation failures:
frozen registry/spec hash and routing comparisons under
`tests/indicator_parameter_search`. They are outside this repair scope because
they require frozen research-artifact reconciliation; no such artifact was
changed.

### Repository setting

GitHub default branch was changed from `master` to `main` and the local
`origin/HEAD` symbolic ref now points to `origin/main`.

### Safety

- Research reruns: none
- OOS/confirmation access: none
- CatBoost training: none
- Model/parameter/result changes: none
- S7 data changes: none
- S13 runtime-data changes: none
- Deploy/restart/migration: none
- Live trading: none

## Artifacts

- This report
- Root control: `WIP.md`
- Local branch: `wip/trading-pilot-import-data-integrity-repair-1`
- `restored_source_hashes_v1.json`
- `verification_summary_v1.json`

## Git commit

GIT_COMMIT=a24442fe1c6b6658545fb763d31ad9e4f9f8a544

## RETURN

```text
WIP=TRADING-PILOT-IMPORT-AND-DATA-INTEGRITY-REPAIR-1
STATUS=CLOSED
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
NEXT_WIP=TRADING-PILOT-FROZEN-REGISTRY-RECONCILIATION-1
```

## Decision

Accepted by the user. The 10 known research-artifact test failures remain open
and are carried into `TRADING-PILOT-FROZEN-REGISTRY-RECONCILIATION-1`.

## Roadmap update

ROADMAP_STATUS_UPDATED=YES

NEXT_WIP=TRADING-PILOT-FROZEN-REGISTRY-RECONCILIATION-1
