# WIP=TRADING-PILOT-FROZEN-REGISTRY-RECONCILIATION-1

STATUS=CLOSED

STARTED_AT=2026-11-10
CLOSED_AT=2026-11-10

## Goal

Diagnose the 10 `indicator_parameter_search` test failures left open by
`TRADING-PILOT-IMPORT-AND-DATA-INTEGRITY-REPAIR-1`, separating checkout/encoding
effects from real frozen registry-to-code mismatches.

## Context

The accepted repair WIP ended in `REVIEW` with `269 passed, 10 failed`. All
failures were confined to frozen registry/spec hash and routing comparisons.
Its implementation commit is `a24442fe1c6b6658545fb763d31ad9e4f9f8a544`.

This WIP is diagnostic only. It does not modify frozen artifacts, routing code,
models, historical results, or runtime hosts.

## Inputs

- `artifacts/MULTITF-INDICATOR-PARAMETER-SEARCH-1/`
- `candidate_registry_snapshot_v1.csv`
- `candidate_registry_snapshot_v2.csv`
- `search_spec_v1.json`
- `search_spec_v2.json`
- Frozen-artifact verification code and routing tests

## Plan

- [x] Reproduce the 10 failures in the current checkout.
- [x] Compare expected Git-blob hashes with raw working-tree hashes.
- [x] Determine whether CRLF conversion explains the two hash checks.
- [x] Compare v1/v2 registry row counts and schema fields.
- [x] Trace route resolution expectations for DMA, inverse predictor, DNO
  quantile, and DNO reference rows.
- [x] Identify the authoritative frozen version.
- [x] Document classification and minimal reconciliation options.
- [x] Set `STATUS=REVIEW` and stop.

## Results

### Reproduction

All 10 known tests were reproduced with fixture-only inputs. No market data,
models, OOS/confirmation, runtime hosts, or research jobs were used.

### Registry authority

`search_spec_v2.json` declares:

- study version: `MULTITF_INDICATOR_PARAMETER_SEARCH_V2`
- v1 status: `SUPERSEDED_INVALID_EXECUTION_SPEC`
- v1 is superseded by v2

The active production loader in
`run_search._load_frozen_registry()` reads
`candidate_registry_snapshot_v2.csv`.

V1 is historical:

- 3220 rows, 14 columns
- no `execution_route` column
- families: 80 `DNO_PREDICTOR` instead of 20 `PURE_DNO` + 40 `DNO_QUANTILE`
- current resolver reports 200 unresolved rows

V2 is active:

- 3200 rows, 15 columns including `execution_route`
- families: `DMA=1680`, `STOCHASTIC=340`, `MACD=520`,
  `PURE_DNO=20`, `DNO_QUANTILE=40`, `OSC_PREDICTOR=480`,
  `INVERSE_PREDICTOR=120`
- `build_candidate_registry()` versus frozen V2: 0 mismatches
- routing preflight: 3200 total, 0 exceptions, 0 unresolved
- mandatory reference routes: 460/460 executable

### Failure classification

| Tests | Class | Cause |
|---:|---|---|
| 2 | ENCODING_ONLY | Working copies use CRLF; expected hashes are computed from LF Git blobs. Normalized content is identical. |
| 8 | TEST_EXPECTATION_DRIFT | Tests load superseded V1, assert V1 row count/routes, or expect route names no longer used by V2 (`INVERSE`, `PREDICTOR`). |

The eight semantic test failures are:

1. `test_frozen_registry_semantic_roundtrip`
2. `test_production_loader_uses_frozen_csv`
3. `test_inverse_predictor_rows`
4. `test_dno_quantile_control_route`
5. `test_dno_period_7_reference_semantics`
6. `test_candidate_routing_preflight_all_rows`
7. `test_mandatory_reference_routes_executable`
8. `test_production_frozen_registry_integration_by_family`

### Hash evidence

For both V1 and V2, working-tree content normalized from CRLF to LF is
byte-identical to the corresponding Git blob.

- V1 spec blob: `a50e6357...`; working raw:
  `8878954b...`
- V1 registry blob: `93a89cb4...`; working raw:
  `aaed4631...`
- V2 spec blob: `981fda57...`; working raw:
  `08ea6ee5...`
- V2 registry blob: `13e54358...`; working raw:
  `3940fe68...`

The V2 fallback constants currently equal the CRLF working hashes rather than
the freeze-commit blobs. This is recorded as a reconciliation issue, not
changed here.

### Reconciliation options

1. Make frozen-artifact verification newline-stable or declare frozen
   JSON/CSV files as binary/LF in `.gitattributes`.
2. Replace V2 fallback constants with freeze-commit blob hashes.
3. Split tests into explicit historical-V1 and active-V2 fixtures.
4. Point production-behavior tests to V2 and its 3200-row contract.
5. Assert current V2 route families (`PURE_DNO`, `DNO_QUANTILE_CONTROL`,
   predictor IDs for inverse rows) instead of obsolete generic names.
6. Keep V1 tests limited to historical row count, deserialization, and
   superseded status.

Dry checks of V2 semantics passed:

- inverse batch reference parity: PASS
- inverse batch signal parity: PASS
- inverse batch gap parity: PASS
- DNO quantile control route: PASS
- silent dead route count: 0
- pure-DNO non-zero primitive count: 0

No registry, spec, model, or research-result artifact was modified.

## Artifacts

- This report
- Root control: `WIP.md`
- `registry_reconciliation_evidence_v1.json`

## Git commit

GIT_COMMIT=ee4c5dabe51e0fe6b3558d0c484c10ff30fa4b75

## RETURN

```text
WIP=TRADING-PILOT-FROZEN-REGISTRY-RECONCILIATION-1
STATUS=CLOSED
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

## Decision

Diagnostic accepted by the user. The V2 test contract was aligned without
changing frozen artifacts. Full `indicator_parameter_search` suite: 44 passed.
No frozen artifact or routing repair was performed.

## Roadmap update

ROADMAP_STATUS_UPDATED=YES

NEXT_WIP=TRADING-PILOT-FROZEN-REGISTRY-TEST-ALIGNMENT-1 (proposal only; do not start automatically)
