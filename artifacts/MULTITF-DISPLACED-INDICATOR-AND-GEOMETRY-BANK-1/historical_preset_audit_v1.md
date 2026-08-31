# Historical preset audit

## DMA presets found
- 3×3 display-aligned SMA — `indicator_engine/registry.py:DMA_3X3_V1` (DINAPOLI_STYLE)
- 7×5 — `DMA_7X5_V1`
- 25×5 — `DMA_25X5_V1`
- Reconstruction freeze: `RETURN_SUMMARY_v1.json` BEST_DMA_PERIOD_SHIFT 3/3

## Stochastic presets found
- 14/3/3 shift 0 — `STOCH_14_3_3_V1` (STANDARD)
- 14/3/3 shift 3 — `DISPLACED_STOCH_14_3_3_SHIFT3_V1` (PROJECT_EXPERIMENTAL)
- No proprietary DiNapoli-exact stochastic source — use PROJECT_DISPLACED_STOCHASTIC

## MACD presets found
- 12/26/9 shift 0 — `MACD_12_26_9_V1`
- 12/26/9 shift 3 — `DISPLACED_MACD_12_26_9_SHIFT3_V1` (PROJECT_EXPERIMENTAL)
- No DiNapoli-exact MACD source — use PROJECT_DISPLACED_MACD

## Sources
- dma_3x3: `phase3_staging/crypto_trading_bot/research_v2/indicator_engine/registry.py:DMA_3X3_V1`
- dma_7x5: `phase3_staging/crypto_trading_bot/research_v2/indicator_engine/registry.py:DMA_7X5_V1`
- dma_25x5: `phase3_staging/crypto_trading_bot/research_v2/indicator_engine/registry.py:DMA_25X5_V1`
- stoch_14_3_3: `phase3_staging/crypto_trading_bot/research_v2/indicator_engine/registry.py:STOCH_14_3_3_V1`
- displaced_stoch_shift3: `phase3_staging/crypto_trading_bot/research_v2/indicator_engine/registry.py:DISPLACED_STOCH_14_3_3_SHIFT3_V1`
- macd_12_26_9: `phase3_staging/crypto_trading_bot/research_v2/indicator_engine/registry.py:MACD_12_26_9_V1`
- displaced_macd_shift3: `phase3_staging/crypto_trading_bot/research_v2/indicator_engine/registry.py:DISPLACED_MACD_12_26_9_SHIFT3_V1`
- reconstruction_freeze: `artifacts/ORIGINAL-DINAPOLI-STYLE-WHEN-RECONSTRUCTION-1/RETURN_SUMMARY_v1.json`