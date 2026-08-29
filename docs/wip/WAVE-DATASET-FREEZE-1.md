# WIP=WAVE-DATASET-FREEZE-1

STATUS=REVIEW

STARTED_AT=2026-08-29
CLOSED_AT=

## Goal

Create the canonical immutable historical wave dataset (`WAVE_ENGINE_V1` / `WAVE_DATASET_V1`) that all subsequent research WIPs will reference.

## Context

Phase 0 accepted: Fibonacci-specific ratios not supported; retain wave geometry, R≈1, empirical R distribution. Group ATR configs frozen without further tuning.

## Inputs

- Canonical ETHUSDT 1m → resampled TFs
- Accepted configs from `ZIGZAG-NORMALIZATION-AND-DINAPOLI-RETEST-1`

## Constraints

- Do not optimize against indicators / PnL / volume / OI / reversal accuracy
- Do not overwrite V1 once frozen (next revision = V2)
- Do not activate `REVERSAL-EVENT-DATASET-1` in this WIP

## Non-goals

Volume, indicators, predictors, Bybit, liquidations, ML, PnL

## Implementation / Experiment

Package: `phase3_staging/crypto_trading_bot/research_v2/wave_engine/`

- `v1_config.py` — frozen configs + research decisions
- `freeze_dataset.py` — pivots / legs / rolling geometry / R distributions / validation / manifests
- `run_freeze.py` — CLI
- `sanity_overlay.py` — sample TF overlay JSON for 5m/1H/2H/4H/6H/1D

## Anti-leakage rules

Pivot confirmation metadata never precedes pivot bar. R uses completed D (retrospective geometry labels). Features for future WHEN studies must still respect availability times in later WIPs.

## Acceptance criteria

- Manifests + parquet datasets created
- Pivot / leg / R validation PASS
- Research decisions recorded permanently
- Roadmap STATUS=REVIEW (not auto-CLOSED)

## Results

| TF | Config | Quality | Pivots | Legs | Windows | R_median |
|---|---|---|---:|---:|---:|---:|
| 5m | ATR(10)×15 D3/B0 | OK | 562 | 561 | 559 | 0.989 |
| 15m | ATR(10)×15 D3/B0 | OK | 453 | 452 | 450 | 0.945 |
| 30m | ATR(10)×15 D3/B0 | OK | 313 | 312 | 310 | 0.997 |
| 1H | ATR(14)×2.5 D3/B0 | MARGINAL_TOO_DENSE | 3013 | 3012 | 3010 | 0.971 |
| 2H | ATR(14)×2.5 D3/B0 | OK | 1500 | 1499 | 1497 | 0.975 |
| 4H | ATR(14)×2.5 D3/B0 | OK | 752 | 751 | 749 | 0.968 |
| 6H | ATR(14)×0.5 D3/B0 | OK | 1348 | 1347 | 1345 | 0.991 |
| 8H | ATR(14)×0.5 D3/B0 | OK | 1034 | 1033 | 1031 | 0.954 |
| 12H | ATR(14)×0.5 D3/B0 | OK | 678 | 677 | 675 | 1.002 |
| 1D | ATR(14)×0.5 D3/B0 | OK | 339 | 338 | 336 | 0.990 |

- `PIVOT_VALIDATION=PASS`
- `LEG_VALIDATION=PASS`
- `R_VALIDATION=PASS`
- Time range ≈ 2019-05-12 → 2024-06-29 UTC
- Canonical target: continuous **R** + `LEG_PERSISTENCE_BASELINE_V1` (R_BASELINE=1.0)
- Fib COP/OP/XOP fields: `LEGACY_DIAGNOSTIC_ONLY`

## Artifacts

S13 root (immutable):

`/var/tmp/traiding_pilot_ui_workspace/wave_dataset_v1/`

- `wave_pivots_v1.parquet`
- `wave_legs_v1.parquet`
- `rolling_geometry_v1.parquet`
- `r_distribution_by_tf_v1.csv`
- `wave_engine_manifest_v1.json`
- `wave_dataset_manifest_v1.json`
- `WAVE_DATASET_V1_IMMUTABLE.txt`
- `sanity_overlays/`

Local copies of manifests/summaries:

`artifacts/WAVE-DATASET-FREEZE-1/`

## Browser/runtime evidence

Sanity overlays regenerated for 5m/1H/2H/4H/6H/1D under `sanity_overlays/` (frozen ATR engine; existing LWC still defaults to percent ZigZag — overlay JSON is the reproduction check for this WIP).

## Git commit

GIT_COMMIT=PENDING

## RETURN

See chat RETURN for this WIP.

## Decision

Awaiting user acceptance before CLOSED. Do **not** start `REVERSAL-EVENT-DATASET-1` until then.

## Roadmap update

ROADMAP_STATUS_UPDATED=YES

NEXT_WIP=REVERSAL-EVENT-DATASET-1
