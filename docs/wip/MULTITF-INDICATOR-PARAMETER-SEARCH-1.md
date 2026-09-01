# WIP=MULTITF-INDICATOR-PARAMETER-SEARCH-1

STATUS=ACTIVE

## Purpose

Per-timeframe, per-direction parameter search over registered indicator families (DMA, Stochastic, MACD, DNO/oscillator predictor, executable inverse predictors). Not composite signal search, not trading/PnL, OOS locked.

## Predecessor

`OSCILLATOR-PREDICTOR-HISTORICAL-EVENT-STUDY-1` = CLOSED  
Final verdict: `PREDICTOR_EFFECT_WEAK`  
Unique dynamic edge vs controls: `NOT_ESTABLISHED`

## Governance preserved

- BASE_RATE_ASSOCIATION=SUPPORTED
- FORECAST_REALIZATION_EFFECT=SUPPORTED
- DYNAMIC_VS_DNO_QUANTILE=MIXED
- DYNAMIC_VS_ATR=MIXED
- LOW_TF_STABILITY=STABLE_POSITIVE
- HIGH_TF_STABILITY=UNSTABLE
- PROJECT_DYNAMIC_EXTREMA_UNIQUE_EDGE=NOT_ESTABLISHED

## Implementation

Package: `phase3_staging/crypto_trading_bot/research_v2/indicator_parameter_search/`

Run (S13):

```bash
bash _run_parameter_search_s13.sh discovery-only
bash _run_parameter_search_s13.sh validation
```

## Artifacts

`artifacts/MULTITF-INDICATOR-PARAMETER-SEARCH-1/`

Required freeze commits:

- SEARCH_SPEC_FREEZE_COMMIT (before discovery ranking)
- DISCOVERY_FREEZE_COMMIT (before validation)
- FINAL_RESULTS_COMMIT

## Next WIP (not activated)

`MULTITF-COMPOSITE-SIGNAL-SEARCH-1` = PLANNED
