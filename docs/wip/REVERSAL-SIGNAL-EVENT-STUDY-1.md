# WIP=REVERSAL-SIGNAL-EVENT-STUDY-1

STATUS=REVIEW

STARTED_AT=2026-08-29
REVIEW_AT=2026-08-29

## Goal

First real WHEN study: dual pivot-centered + continuous-timeline analysis of causal directional signals vs price baselines; context enrichment separate from direction. OOS locked.

## Results (summary)

- Continuous false-positive scan: **PASS** (ledgers + unmatched counts)
- Causal ledger vs label-match separation: **PASS**
- Price baselines remain competitive; indicators do not clearly dominate pooled delay/FP tradeoff
- RESEARCH_VERDICT=`WHEN_SIGNAL_WEAK`
- Predictor-trigger continuous scan and confluence context snapshots: **deferred (compute)** → INCONCLUSIVE
- Volume/compression context proximity scan returned zero near-C hits on VALIDATION (timestamp/proximity plumbing issue) → CONTEXT_ENRICHMENT_FOUND=NO
- OOS_OPENED=NO

## Artifacts

`artifacts/REVERSAL-SIGNAL-EVENT-STUDY-1/`  
Code: `phase3_staging/crypto_trading_bot/research_v2/reversal_signal_study/`

## Matching rules

Documented in `match.py`: merge_asof nearest preceding/upcoming C; max delay by decision TF; first post-C signal per candidate/event; pre-C separate; unmatched = continuous FP.

## Deferred / known limits

1. Full-history inverse-predictor walks too expensive → not scored this pass (registry kept).
2. Confluence context snapshots deferred.
3. Context near-C enrichment currently reports zero hits on VALIDATION (bug/limitation of proximity join); do not interpret as proof volume is useless.
4. 5m MAE path enrichment skipped for runtime (endpoint metrics only on 5m).

## RETURN

See final assistant message.

## Roadmap

ROADMAP_STATUS=REVIEW  
Do **not** auto-activate next WIP.
