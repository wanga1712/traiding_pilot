# WIP=ZIGZAG-NORMALIZATION-AND-DINAPOLI-RETEST-1

STATUS=REVIEW

STARTED_AT=2026-08-29
CLOSED_AT=

## Goal

Build timeframe-comparable ZigZag geometry (ATR / vol-percent families), freeze using **wave-geometry criteria only** (no R/DiNapoli leakage), then retest next-leg R and COP/OP/XOP vs control ratios.

## Context

Fixed-percent multitf (`FIXED_ZZ_BASELINE_V1`) showed R≈1 everywhere but fib modes not special; low TFs TOO_DENSE. Need normalization before market-context work.

## Inputs

- ETHUSDT 5m…1D via canonical resampling pipeline
- Immutable baseline: `/var/tmp/traiding_pilot_ui_workspace/dinapoli_multitf_sweep/`

## Constraints

- Do not overwrite FIXED_ZZ_BASELINE_V1
- Do not choose N/K using COP/OP/XOP / R metrics
- Prefer one global ATR config; else minimal TF groups

## Non-goals

Volume, OI, indicators, ML, PnL, further Fibonacci coefficient tuning

## Implementation / Experiment

- Family A: ATR(N)×K grid; depth=3 / backstep=0
- Family B: vol-percent reference
- Geometry bands (clock-time hours + ppy); group configs when no global
- Validation 70/30 chronological; bootstrap CIs; continuous-distribution verdict

## Anti-leakage rules

ZigZag calibration on discovery candles/geometry only. All R/target claims from validation.

## Acceptance criteria

Reported RETURN with classification; user review for geometry interpretation.

## Results

- `GLOBAL_NORMALIZED_ZZ_FOUND=NO`
- Groups: `5m-30m ATR(10)*K=15`; `1H-4H ATR(14)*K=2.5`; `6H-1D ATR(14)*K=0.5`
- R median ≈ 0.98–1.14 across TFs
- Fib density edges vs controls ≈ 0 / negative
- `DINAPOLI_SPECIFIC_RATIOS_SUPPORTED=NO`
- `LEG_PERSISTENCE_SUPPORTED=YES`
- `CONTINUOUS_WAVE_DISTRIBUTION_SUPPORTED=YES`
- Freeze note: `DINAPOLI_SPECIFIC_RATIOS_NOT_SUPPORTED`; retain R≈1 / empirical R

## Artifacts

`/var/tmp/traiding_pilot_ui_workspace/dinapoli_normalized_retest/`

Including: `normalized_zigzag_config.csv`, `normalized_dinapoli_multitf.csv`, `fixed_vs_normalized_comparison.csv`, `summary.json`, …

## Browser/runtime evidence

S13 CLI run; baseline marker `FIXED_ZZ_BASELINE_V1.txt` present.

## Git commit

GIT_COMMIT=PENDING

## RETURN

See chat RETURN for WIP=ZIGZAG-NORMALIZATION-AND-DINAPOLI-RETEST-1 (2026-08-29). Summary above.

## Decision

Awaiting user acceptance. Expected close label: **CLOSED_NEGATIVE** for Fibonacci-specific hypothesis; wave geometry / R≈1 retained.

## Roadmap update

ROADMAP_STATUS_UPDATED=YES (STATUS=REVIEW in ROADMAP.md)

NEXT_WIP=WAVE-DATASET-FREEZE-1
