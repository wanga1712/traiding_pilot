# PREDICTOR_CONFLUENCE_ENGINE_V1

Causal features describing the **spatial/temporal landscape** of inverse-predictor trigger prices.

Not a WHEN model. No ranking vs true pivots C.

## Source

Uses frozen `INVERSE_PREDICTOR_ENGINE_V1` outputs only (no formula reimplementation).

## Signed distance

`positive = trigger ABOVE current price`

## Valid triggers

Only `EXACT_ANALYTIC` / `NUMERIC_UNIQUE` with a finite price enter clustering.
Other statuses are counted, not converted into prices.

## Clustering

1D adjacent-gap on sorted prices. Join if:

- gap ≤ `threshold_pct` % of midpoint, **OR**
- gap ≤ `threshold_atr` × ATR

Thresholds are registry baselines — not outcome-tuned.

## Views

- **RAW** — all valid predictor parameter sets
- **FAMILY_NORMALIZED** — one nearest-to-market trigger per indicator family

## Temporal

Compare to prior closed-bar snapshot (approach/recede, dispersion delta, cluster size change).

## Cross-TF

Union of within-TF triggers at the same decision time T (closed bars only per TF).
