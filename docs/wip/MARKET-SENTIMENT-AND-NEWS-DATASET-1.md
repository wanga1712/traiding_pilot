# WIP=MARKET-SENTIMENT-AND-NEWS-DATASET-1

STATUS=PLANNED
REGISTRATION=PROPOSED
ACTIVATED=NO

STARTED_AT=
CLOSED_AT=
MODE=RESEARCH / DATA-ONLY / NO RETRAIN / OOS LOCKED

## Goal

Create an independent, reproducible historical feature dataset of market fear,
greed, and news context for ETHUSDT crash-risk research.

The dataset is intended as input to a separately approved
`Crash Risk Predictor V1` training WIP. This WIP does not train or evaluate a
trading model.

## Context

The existing frozen probability models and research results remain unchanged.
Current operational diagnostics and repairs are not research inputs for this
dataset. The WIP remains `PLANNED/PROPOSED` until explicit activation.

## Inputs to investigate after activation

- Alternative.me historical Fear & Greed data
- CoinMarketCap historical market metrics where licensing and history permit
- GDELT news/publication history
- Approved causal ETHUSDT market data available through the project's S7 data
  authority

Only sources whose historical availability, publication semantics, licensing,
and redistribution rights can be documented may be used.

## Tasks

1. Verify historical access, coverage, latency semantics, and licensing for
   Alternative.me, CoinMarketCap, and GDELT.
2. Define and freeze an independent project Fear & Greed Index V1 on a 0-100
   scale using causal market features available at the decision timestamp.
3. Build a news record layer with at minimum:
   `published_at`, `first_seen_at`, `source`, `asset`, `topic`,
   `sentiment`, and `event_type`.
4. Deduplicate exact articles, canonical URLs, syndicated reprints, and
   materially identical stories while preserving the earliest causal sighting.
5. Compute historical features from information available at or before each
   decision timestamp.
6. Prepare drawdown labels over 7-, 30-, 60-, and 90-day horizons.
7. Implement look-ahead, publication-delay, first-seen, gap, and coverage
   controls.
8. Persist a versioned dataset, schema, manifest, per-file SHA256, coverage
   report, and validation evidence.

## Causal and anti-leakage rules

- A news item cannot enter features before `first_seen_at`, regardless of its
  nominal historical publication time.
- Retrospective publication timestamps must be separated from actual discovery
  timestamps when the source does not preserve them.
- Crash labels are never available to feature construction or index
  normalization.
- The Fear & Greed V1 formula and source priority are frozen before drawdown
  outcomes are examined.
- No parameter may be tuned using future drawdown results.
- Existing OOS and confirmation sets remain closed.
- Splits must be documented before any model-oriented WIP consumes the dataset.

## Constraints

- Do not modify existing CatBoost models or parameters.
- Do not open frozen OOS or confirmation datasets.
- Do not modify S7, S13, or existing research artifacts.
- Do not tune parameters against future crash outcomes.
- Do not run model training, backtesting, or live trading.
- Do not activate this WIP until the current operational WIP is accepted and
  the user explicitly activates this research WIP.
- Do not overwrite prior news, market, or research artifacts.

## Expected outputs

- `MARKET_SENTIMENT_AND_NEWS_DATASET_V1`
- Data source/access matrix
- Fear & Greed Index V1 specification
- News deduplication registry
- Causal feature table
- Drawdown label table for 7/30/60/90 days
- Coverage/missingness report
- Look-ahead validation report
- Manifest and SHA256 evidence

## Acceptance criteria

- Historical data coverage and source limitations are explicit.
- All features are causally reproducible at the decision timestamp.
- News duplicates/syndication rate is measured before and after deduplication.
- Labels and features are physically and logically separated.
- The output is deterministic from immutable source snapshots.
- No research result, model, S7/S13 resource, OOS, or confirmation set changes.
- Dataset is ready for separate review before Crash Risk Predictor V1 training.

## RETURN

```text
WIP=MARKET-SENTIMENT-AND-NEWS-DATASET-1
STATUS=PLANNED
DATA_COVERAGE=
NEWS_COVERAGE=
INDEX_COVERAGE=
DATASET_ROWS=
NEWS_COUNT=
MISSING_RATE=
DUPLICATE_RATE=
CAUSALITY_TESTS=
ARTIFACT_HASHES=
LIMITATIONS=
```

## Decision

Proposed only. Not activated.

## Roadmap update

ROADMAP_STATUS_UPDATED=YES

NEXT_WIP=none
