# INVERSE_PREDICTOR_ENGINE_V1

Deterministic **causal** inverse predictors: solve the hypothetical next-bar close `X`
that would make a defined indicator condition true.

This is **not** a forecast. It does not claim price will reach X.

## Hypothetical input

`HYPOTHETICAL_INPUT_TYPE=NEXT_BAR_CLOSE`

Do not use actual next high/low/path. Actual next market data is for later evaluation WIPs only.

## Time semantics

Reuse INDICATOR_ENGINE_V1:

- `CALCULATED_AT` / `AVAILABLE_AT` from last closed bar
- DMA display displacement does **not** change availability

## Solution hierarchy

1. Exact analytic
2. Deterministic numeric (not used in V1 baselines)
3. Explicit `UNSUPPORTED_V1` / `REQUIRES_INTRABAR_ASSUMPTION` / `AMBIGUOUS`

## Stochastic limitation

Full %K/%D with unknown next H/L is not uniquely determined by next close alone.
V1 supports raw %K levels under explicit `POINT_BAR` (H=L=X). K×D cross → `REQUIRES_INTRABAR_ASSUMPTION`.

## Bollinger

`UNSUPPORTED_V1` — next close changes mean and std jointly (nonlinear / possible multiple roots).

## Project oscillator

`PROJECT_OSCILLATOR_PREDICTOR_V1`: `close - SMA(N)` with causal rolling mean±k·std thresholds.
Not proprietary DiNapoli.

## Validation

Synthetic next-close replay through INDICATOR_ENGINE_V1 must reproduce the target condition.
