# GATE 2 - Causal Dataset

STATUS=PASS

## Dataset

| Field | Value |
|---|---:|
| Version | `GPU_AI_POLICY_DATASET_V1` |
| Decision timeframe | 1H |
| Rows | 17,514 |
| Dense features | 453 |
| Atomic event features | 284 |
| Composite event features | 5,478 |
| Total features | 6,215 |
| Target horizons | 24h / 72h / 168h |
| Target windows complete | 48,240 |
| Target windows censored by gaps | 4,038 |
| Target windows censored at boundary | 264 |
| Target parity | PASS |

## Splits

| Split | Period | Rows |
|---|---|---:|
| TRAIN | 2020-01-01 through 2020-07-01 exclusive | 4,356 |
| SELECTION | 2020-07-01 through 2021-01-01 exclusive | 4,411 |
| LOCKED | 2021 | 8,747 |

The train/selection boundary applies a 168-hour purge and 24-hour embargo.
RUN 1 is 2020. RUN 2 is 2021 and is chronological validation inside
DEVELOPMENT, not independent OOS.

## Included families

- Causal 1H/4H/1D DMA.
- MACD and Stochastic.
- RSI, ADX, ATR, Bollinger Bands, and realized volatility.
- DiNapoli DNO.
- Candle, price-volume, and base market structure.
- Existing inverse predictor event streams.
- Existing composite signal event streams.
- Confirmed ZigZag pivots using confirmation-time availability.
- Portfolio state for 60/40 and 40/60 allocations, HOLD and SWING spot modes,
  PRIMARY/HEDGE exposures, free/used margin, liquidation distance, averaging,
  holding time, fees, funding, and remaining risk.

Missing feature values remain missing; they are not replaced with synthetic
zeros. Event absence remains zero for the frozen sparse event streams.

## Provenance and limitation

Spot 1m came from the canonical S7-to-S13 research cache. Futures, mark-price,
and funding came from the previously isolated S13 capital-growth research
dataset. No exchange download or S7 mutation occurred in this WIP.

The available execution data ends at `2022-01-01` exclusive. Therefore 2022
could not be used as RUN 2 without a new approved data-ingestion WIP.

Evidence files:

- `dataset_manifest_v1.json`
- `dataset_integrity_v1.json`
- `split_manifest_v1.json`
- `feature_registry_v1.json`
- `dataset_full_v2.log`
