# Capital Growth Experiment 1 - Committed Evidence

This directory contains the compact evidence needed to review
`TRADING-PILOT-CAPITAL-GROWTH-EXPERIMENT-1`. Full runtime parquet data,
equity tables, and all portfolio journals remain on S13.

## Primary evidence

| File | Purpose |
|---|---|
| `summary_v1.json` | Complete machine-readable RUN 1/RUN 2 result |
| `control_comparisons_v1.json` | Eight hedged/unhedged comparisons |
| `frozen_config_v1.json` | Configuration frozen between RUN 1 and RUN 2 |
| `data_preflight_v1.json` | Coverage, gaps, funding, and limitations |
| `artifact_manifest_v1.json` | SHA256 inventory for all S13 artifacts |

## Run evidence

| Directory | Contents |
|---|---|
| `RUN1_DISCOVERY/` | Full portfolio metric CSV, equity curves, representative journals/charts |
| `RUN2_VALIDATION/` | Full portfolio metric CSV, equity curves, representative journals/charts |

`portfolio_metrics.csv` contains the complete per-portfolio report: capital,
PRIMARY/HEDGE PnL, liquidation and emergency exits, holding time, recovery
diagnostics, drawdown, profit factor, fees, funding, slippage, liquidation
fees, and threshold checks.

The representative `A_HOLD_HEDGED_AVG` directory includes the trade and event
journals plus the PRIMARY/HEDGE chart. `A_HOLD_UNHEDGED_AVG` includes the
matching control chart.

## Hashes

```text
frozen_config_v1.json
c7f44d8a022ceb6e882240c5c753dff60c9f0f91fdf5087c554a981db37bff57

summary_v1.json
fa20ccec272e655750dfc80cbafaeaf2ec2d5b36f2c36c91f9664d9ae2cc3a8

artifact_manifest_v1.json
98d44badba76fc558163a663ed28cf6eda8b15b4e7bc6d976583435d695d14fb
```

The S13 manifest verification checked 1,583 files and 281,307,066 bytes. All
recorded size and SHA256 checks passed.

## Final result

Dynamic hedging lost to the matching unhedged control in all eight
comparisons. The best portfolios did not beat Buy & Hold, and the hedged
portfolios produced 65 liquidation events versus 49 for their unhedged
controls.

Invalidated and aborted intermediate runs remain on S13 under explicit
`INVALIDATED_...` or `ABORTED_...` names. They are not final evidence.
