# WIP=ZIGZAG-NORMALIZATION-AND-DINAPOLI-RETEST-1

STATUS=CLOSED

STARTED_AT=2026-08-29
CLOSED_AT=2026-08-29

## Goal

Normalize ZigZag across timeframes and finish the geometry question: R≈1 persistence, Fibonacci-specific attraction, continuous vs multimodal R.

## Context

Fixed-percent multitf (`FIXED_ZZ_BASELINE_V1`) showed R≈1 but fib modes not special; low TFs pathological. Normalization required before market-context work.

## Results (accepted)

```
DINAPOLI_SPECIFIC_RATIOS_SUPPORTED=NO
COP_RATIO_SPECIAL=NO
OP_RATIO_SPECIAL=NO
XOP_RATIO_SPECIAL=NO
LEG_PERSISTENCE_SUPPORTED=YES
CONTINUOUS_WAVE_DISTRIBUTION_SUPPORTED=YES
```

R median across tested TFs remains approximately 1.  
Normalized validation found no reproducible special density at 0.618 / 1.000 / 1.618 versus control ratios.

### Freeze research decision

`DINAPOLI_SPECIFIC_RATIOS_NOT_SUPPORTED`

Future research **MUST NOT** continue tuning Fibonacci ratios unless a completely new independently justified hypothesis is registered as a new roadmap WIP.

Retain as project research authority:

- wave geometry
- R≈1 baseline (`LEG_PERSISTENCE_BASELINE_V1`)
- complete empirical R distribution

### Normalized configurations

| Group | Config |
|---|---|
| 5m–30m | ATR(10)×15 / D3/B0 |
| 1H–4H | ATR(14)×2.5 / D3/B0 |
| 6H–1D | ATR(14)×0.5 / D3/B0 |

`GEOMETRY_COMPARABLE_ACROSS_TF=NO` — no single global ATR configuration.  
1H diagnostic: `MARGINAL_TOO_DENSE` (~602 pivots/year).

## Artifacts

- Normalized: `/var/tmp/traiding_pilot_ui_workspace/dinapoli_normalized_retest/`
- Baseline (immutable): `/var/tmp/traiding_pilot_ui_workspace/dinapoli_multitf_sweep/` (`FIXED_ZZ_BASELINE_V1`)

## Decision

**CLOSED** — experiment completed successfully. Fibonacci-specific hypothesis unsupported; wave geometry / leg persistence / continuous R supported.

## Roadmap update

ROADMAP_STATUS_UPDATED=YES

NEXT_WIP=WAVE-DATASET-FREEZE-1
