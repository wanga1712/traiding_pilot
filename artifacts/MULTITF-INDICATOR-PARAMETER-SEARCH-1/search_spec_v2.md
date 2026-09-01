# MULTITF-INDICATOR-PARAMETER-SEARCH-1 — Search Spec v2

WIP: MULTITF-INDICATOR-PARAMETER-SEARCH-1
Study: MULTITF_INDICATOR_PARAMETER_SEARCH_V2
Frozen: 2026-09-01T17:15:38.631085+00:00
Supersedes: search_spec_v1.json (SUPERSEDED_INVALID_EXECUTION_SPEC)

## Purpose
Per-timeframe indicator parameter discovery with corrected route authority (NOT composite, NOT trading, NOT OOS).

## V2 corrections
- Pure DNO reference (`DNO_PERIOD_7_REFERENCE`) uses `DNO_ZERO_CROSS_UP/DOWN` via `compute_dno_feature_series`
- Oscillator predictor reference remains separate from pure DNO
- DNO quantile control remains separate (`CAUSAL_DNO_QUANTILE_80_20_CONTROL_V1`)
- Inverse routes map to real `inverse_predictors.registry.PARAMETER_REGISTRY` IDs
- Inverse direction purity enforced per candidate row

## Authorities
- Formula: `b93f3ca5655ecd727b6f5345c41aa5c434f3bfd0`
- Gap audit: `2d8a7384987914436d036d5a2c4edb9e1badb81c`
- Oscillator predictor: `6b1e34e4dffb469e0b9392c33d20e5689a2cdfe2`

## Splits
- DISCOVERY: 2019-05-12T00:00:00+00:00 → 2022-06-10T04:36:00+00:00
- VALIDATION: 2022-06-10T04:36:00+00:00 → 2023-06-20T06:08:00+00:00
- OOS: LOCKED

## Candidate families
DMA, STOCHASTIC, MACD, PURE_DNO, DNO_QUANTILE, OSC_PREDICTOR, INVERSE_PREDICTOR

Total registry rows: 3200
- DMA: 1680
- STOCH: 340
- MACD: 520
- PURE_DNO: 20
- DNO_QUANTILE: 40
- OSC_PREDICTOR: 480
- INVERSE: 120

## DNO controlled sweeps (one-factor-at-a-time)
Axes: ['period', 'peak_strength', 'lookback', 'samples', 'ob_os_level_percent']

## Selection
- Pareto on precision delta, recall, FPR, delay, premature rate, MAE
- BH-FDR q=0.1
- Redundancy Jaccard>=0.9
- Shortlist cap 2 per TF/direction/family (non-reference)

No composite search. No monetary PnL.
