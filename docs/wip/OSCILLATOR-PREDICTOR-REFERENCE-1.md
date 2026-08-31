# WIP=OSCILLATOR-PREDICTOR-REFERENCE-1

STATUS=REVIEW

## Goal

Add a causal price-domain predictor layer inspired by DiNapoli Oscillator Predictor semantics, with clear separation between:

- **A.** `DINAPOLI_DETRENDED_OSCILLATOR_REFERENCE_V1` — documented non-proprietary DNO
- **B.** `PROJECT_DINAPOLI_STYLE_OSCILLATOR_PREDICTOR_V1` — transparent project reconstruction
- **C.** `INVERSE_PREDICTOR_ENGINE_V1` — reused for DMA/Stoch/MACD (not duplicated)

## Key formulas

**DNO:** `DNO_t = Close_t - SMA_N(Close)_t` (default N=7)

**Analytic inverse:** `P = (N * D_TARGET + S) / (N - 1)`

**Dynamic targets (V1):** `TARGET_OB = OB_OS_LEVEL_PERCENT * mean(confirmed positive peaks)`

## Validation gates

| Gate | Result |
|---|---|
| DNO_INVERSE_OB_ROUNDTRIP | PASS |
| DNO_INVERSE_OS_ROUNDTRIP | PASS |
| PEAK_CONFIRMATION_CAUSALITY | PASS |
| FUTURE_PEAK_LEAKAGE_TEST | PASS |
| PREDICTOR_FUTURE_MUTATION_TEST | PASS |
| DNO_POST_GAP_INDEPENDENCE | PASS |
| PREDICTOR_POST_GAP_INDEPENDENCE | PASS |
| PREDICTOR_BATCH_STREAMING_PARITY | PASS |

## Artifacts

`artifacts/OSCILLATOR-PREDICTOR-REFERENCE-1/`

## Constraints observed

- No parameter optimization
- No signal search / trading PnL / OOS
- `MULTITF-INDICATOR-PARAMETER-SEARCH-1` not activated
