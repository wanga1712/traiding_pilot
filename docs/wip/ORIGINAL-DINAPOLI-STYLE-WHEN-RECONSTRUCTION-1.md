# WIP: ORIGINAL-DINAPOLI-STYLE-WHEN-RECONSTRUCTION-1

## Status

`CLOSED` — User accepted. OOS locked. No PnL. **Not a profitability verdict.**

## Correction

`REVERSAL-SIGNAL-EVENT-STUDY-1` is a **single-candidate baseline** study only. Its `PRICE_BASELINE_BEATEN=NO` does **not** refute the original composite displaced strategy.

## Part 0 audit (complete)

See `artifacts/ORIGINAL-DINAPOLI-STYLE-WHEN-RECONSTRUCTION-1/part0_semantic_audit_v1.md`.

| Flag | Value |
|---|---|
| PREVIOUS_DMA_SIGNAL_ALIGNMENT | SOURCE_ALIGNED |
| PREVIOUS_DISPLACED_STOCH_EVALUATED | NO |
| PREVIOUS_DISPLACED_MACD_EVALUATED | NO |
| COMPOSITE_DMA_STOCH_MACD_TESTED | NO |
| VOLATILITY_GATE_USED | NO |
| COP_OP_XOP_USED_AS_ACTIVATION_GATE | NO |
| VOLUME_CONTEXT_EVALUATION_VALID | NO (plumbing; engine OK) |
| VOLUME_CONTEXT_PIPELINE (this WIP) | **PASS** |

## Frozen system (DISCOVERY → VALIDATION)

- DMA display-aligned **3×3**
- Stoch **14/3/3**, shift **0**, OB/OS **not** required (plain K×D won)
- MACD **12/26/9**, shift **0** (PROJECT_EXPERIMENTAL displacement not selected)
- Confluence: **DMA + STOCH**, window **3**, expiration **5**
- Geometry / vol / volume gates: all **NO_*** (not selected on DISCOVERY score)

## Validation (4H geometry → 1H confirmation)

| System | Precision | Recall | FPR | Score | Remaining wave |
|---|---|---|---|---|---|
| Price baseline (slope sign) | 0.294 | 0.464 | 0.052 | **0.0432** | 0.719 |
| Full / confluence (DMA+Stoch) | **0.471** | 0.377 | 0.047 | 0.0423 | 0.646 |

`PRICE_BASELINE_BEATEN=NO` — composite has better precision and fewer false signals/year, but lower recall and longer median delay; joint score does not beat price.

## Low-activity

- FALSE_SIGNAL_SHARE_LOW_ACTIVITY ≈ **11.5%**
- Regime FPR: LOW **0.017** < NORMAL **0.052** < HIGH **0.071** (false positives are **not** concentrated in low activity under this composite)

## Verdict

`COMPOSITE_NOT_BETTER_THAN_PRICE`

Display-aligned DMA 3×3 + Stoch confluence is a real composite test of the original hypothesis chain (with gates free to turn on). On the registered DISCOVERY freeze, gates did not help the selection score; validation does not beat the price-only WHEN baseline on the joint metric.
