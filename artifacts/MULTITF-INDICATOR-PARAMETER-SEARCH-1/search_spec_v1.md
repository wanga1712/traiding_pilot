# MULTITF-INDICATOR-PARAMETER-SEARCH-1 — Search Spec v1

WIP: MULTITF-INDICATOR-PARAMETER-SEARCH-1
Study: MULTITF_INDICATOR_PARAMETER_SEARCH_V1
Frozen: 2026-09-01T06:24:30.168852+00:00

## Purpose
Per-timeframe indicator parameter discovery (NOT composite, NOT trading, NOT OOS).

## Authorities
- Formula: `b93f3ca5655ecd727b6f5345c41aa5c434f3bfd0`
- Gap audit: `2d8a7384987914436d036d5a2c4edb9e1badb81c`
- Oscillator predictor: `6b1e34e4dffb469e0b9392c33d20e5689a2cdfe2`

## Splits
- DISCOVERY: 2019-05-12T00:00:00+00:00 → 2022-06-10T04:36:00+00:00
- VALIDATION: 2022-06-10T04:36:00+00:00 → 2023-06-20T06:08:00+00:00
- OOS: LOCKED

## Discovery folds
- FOLD_1: 2019-05-12T00:00:00+00:00 → 2020-05-21T01:32:00+00:00
- FOLD_2: 2020-05-21T01:32:00+00:00 → 2021-05-31T03:04:00+00:00
- FOLD_3: 2021-05-31T03:04:00+00:00 → 2022-06-10T04:36:00+00:00

## Candidate families
DMA, STOCHASTIC, MACD, DNO_PREDICTOR, OSC_PREDICTOR, INVERSE_PREDICTOR (executable only)

Total registry rows: 3220

## DNO controlled sweeps (one-factor-at-a-time)
Axes: ['period', 'peak_strength', 'lookback', 'samples', 'ob_os_level_percent']

## Selection
- Pareto on precision delta, recall, FPR, delay, premature rate, MAE
- BH-FDR q=0.1
- Redundancy Jaccard>=0.9
- Shortlist cap 2 per TF/direction/family (non-reference)

No composite search. No monetary PnL.
