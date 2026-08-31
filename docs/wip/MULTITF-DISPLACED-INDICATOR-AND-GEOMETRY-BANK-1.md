# MULTITF-DISPLACED-INDICATOR-AND-GEOMETRY-BANK-1

STATUS=REVIEW

## Summary

Implemented `MULTITF_INDICATOR_FEATURE_BANK_V1` — causal multi-timeframe feature bank building on `INDICATOR_ENGINE_V1`.

- Package: `phase3_staging/crypto_trading_bot/research_v2/multitf_feature_bank/`
- Artifacts: `artifacts/MULTITF-DISPLACED-INDICATOR-AND-GEOMETRY-BANK-1/`

## Historical presets recovered

| Family | Found | Source |
|--------|-------|--------|
| DMA 3×3, 7×5, 25×5 | YES | `indicator_engine/registry.py`, `RETURN_SUMMARY_v1.json` |
| Stoch 14/3/3 | YES | `STOCH_14_3_3_V1`, displaced shift 3 experimental |
| MACD 12/26/9 | YES | `MACD_12_26_9_V1`, displaced shift 3 experimental |

`DINAPOLI_EXACT_STOCH` / `DINAPOLI_EXACT_MACD`: **NO** — use `PROJECT_DISPLACED_STOCHASTIC` / `PROJECT_DISPLACED_MACD`.

## Parameter set counts

- DMA: 42 (14 curated period×shift × SMA/EMA/WMA)
- Stochastic: 16 (4 configs × 4 shifts)
- MACD: 12 (3 configs × 4 shifts)

## Not performed

- Parameter optimization
- Signal search
- Trading PnL
- OOS opened

## Next step

Independent formula/code review before activating `MULTITF-INDICATOR-PARAMETER-SEARCH-1`.
