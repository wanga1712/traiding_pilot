# WIP — TRADING-PILOT-FROZEN-REGISTRY-RECONCILIATION-1

STATUS=REVIEW
STARTED_AT=2026-11-10
MODE=DIAGNOSTIC / READ-ONLY / NO RESEARCH / NO DEPLOY
REPOSITORY=wanga1712/traiding_pilot
TARGET_BRANCH=main

## Goal

Determine why 10 `indicator_parameter_search` tests disagree with the frozen
registry/spec artifacts and candidate routing code, without changing those
artifacts or running research.

## Parent

- Parent WIP: `TRADING-PILOT-IMPORT-AND-DATA-INTEGRITY-REPAIR-1`
- Parent status: ACCEPTED / CLOSED
- Parent implementation commit: `a24442fe1c6b6658545fb763d31ad9e4f9f8a544`
- Base main: `1bfdb9708df635e83971f1e9a6e9545b543f8d77`

## Scope

- Reproduce the 10 known failures.
- Separate file-encoding/line-ending hash mismatches from semantic registry and
  routing mismatches.
- Compare the frozen CSV/JSON schema and route fields with the code that reads
  them.
- Identify the authoritative version and propose a minimal repair path.
- Do not modify frozen artifacts or production routing in this WIP.

## Constraints

- No market research.
- No OOS or confirmation access.
- No CatBoost or other model training.
- No model, prediction, or frozen-result changes.
- No S7/S13 access or mutation.
- No deployment, service restart, or migration.
- No candidate search, backtest, or research pipeline execution.
- No automatic start of a later implementation WIP.

## Acceptance criteria

- All 10 failures are classified as encoding-only or semantic.
- Each semantic mismatch cites the frozen field and routing expectation.
- The authoritative artifact version is identified.
- A minimal, reviewable reconciliation plan is documented.
- No research artifact or runtime host is changed.

- Reproduced: 10/10 failures.
- Encoding-only: 2.
- Semantic/test-expectation drift: 8.
- Frozen V2 is authoritative.
- Existing V2 data matches current code without registry mismatches.

## RETURN

```text
WIP=TRADING-PILOT-FROZEN-REGISTRY-RECONCILIATION-1
STATUS=REVIEW
LOCAL_BRANCH=diagnostic/trading-pilot-frozen-registry-reconciliation-1
LOCAL_HEAD=ee4c5dabe51e0fe6b3558d0c484c10ff30fa4b75
BASE_MAIN=1bfdb9708df635e83971f1e9a6e9545b543f8d77
PARENT_CLOSED=TRADING-PILOT-IMPORT-AND-DATA-INTEGRITY-REPAIR-1
TESTS_REPRODUCED=10
ENCODING_ONLY=2
SEMANTIC_MISMATCH=8
AUTHORITY=FROZEN_SEARCH_SPEC_V2
RUNTIME_REGISTRY_MISMATCH=0
ROUTING_UNRESOLVED=0
ARTIFACT_CHANGES=none
RESEARCH_RERUN=none
S7_S13_ACCESS=none
DEPLOY=none
NEXT_WIP_PROPOSAL=TRADING-PILOT-FROZEN-REGISTRY-TEST-ALIGNMENT-1
```
