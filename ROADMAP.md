# Research Roadmap

**PROJECT AUTHORITY** for the research sequence of this repository.

Every substantial research/development phase must correspond to a WIP registered here.
Do not invent ad hoc primary WIPs outside this document.
Do not create competing roadmap authorities elsewhere.

Individual WIP reports: [`docs/wip/`](docs/wip/)  
Template: [`docs/wip/WIP_TEMPLATE.md`](docs/wip/WIP_TEMPLATE.md)

---

## Current primary WIP

| Field | Value |
|---|---|
| **WIP** | `REVERSAL-EVENT-DATASET-1` |
| **STATUS** | **REVIEW** |
| **PHASE** | 2 — Reversal Event Dataset |
| **Note** | REVERSAL_EVENT_DATASET_V1 built; awaiting user acceptance before CLOSED |

Previous: `WAVE-DATASET-FREEZE-1` → **CLOSED** (`WAVE_ENGINE_V1` / `WAVE_DATASET_V1`).

---

## Project principle

The project is organized around four fundamental questions:

1. **STRUCTURE / WAVE ENGINE** — What constitutes a meaningful market wave?
2. **WHERE?** — Given current wave geometry, where is the next meaningful movement likely to extend?
3. **WHEN?** — When has the previous movement actually ended and a new movement causally begun?
4. **EXECUTION / RISK** — Can that signal be traded profitably after leverage, fees, funding, slippage, liquidation rules, and real execution constraints?

### Critical separation

**WHERE ≠ WHEN**

A calculated price area is **not** itself an entry signal.

The old strategy conflated WHERE with WHEN. The new system must keep them separate:

`WHERE → WAIT → WHEN → ONE ENTRY`

---

## WIP status model

Every roadmap item has exactly one status:

| Status | Meaning |
|---|---|
| `PLANNED` | Not started |
| `ACTIVE` | Current primary implementation/research work |
| `BLOCKED` | Cannot continue until a documented dependency is resolved |
| `REVIEW` | Implementation finished; awaiting evidence / user review |
| `CLOSED` | Accepted and complete |
| `CLOSED_NEGATIVE` | Experiment completed correctly; hypothesis not supported |
| `SUPERSEDED` | Replaced by a later explicitly referenced approach |

Failed hypotheses are preserved as `CLOSED_NEGATIVE`, never deleted.
Superseded approaches remain historically visible.

---

## Global work rule

Before starting any new **primary** WIP:

1. Read this `ROADMAP.md`
2. Verify dependency status
3. Mark selected WIP `ACTIVE`
4. Commit / update roadmap state
5. Execute **only** that WIP
6. Produce evidence / artifacts
7. Produce RETURN report under `docs/wip/<WIP-ID>.md`
8. Mark WIP `REVIEW`
9. After acceptance: `CLOSED` or `CLOSED_NEGATIVE`
10. Record result summary and `GIT_COMMIT`
11. Identify `NEXT_WIP` from this roadmap
12. Only then begin the next WIP

Do **not** leave completed WIPs as `ACTIVE`.  
Do **not** start later phases merely because code is easy to write.

### Parallel work exception

`BYBIT-FUTURES-DATA-FOUNDATION-AND-LIVE-RECORDER-1` may start early because microstructure history cannot be recovered later. Use an official status (`PLANNED` / `ACTIVE` / …) and document that it is parallel. It must not change or block the current primary research WIP unless collector reliability requires intervention.

---

## Research rules (anti-overfitting / anti-leakage)

1. Never optimize a detector using the same target it later evaluates.
2. Every parameter search must identify: **DISCOVERY** / **VALIDATION** / **HOLDOUT/OOS** where applicable.
3. No future data may enter causal features.
4. Display displacement is not information availability.
5. Failed hypotheses stay recorded.
6. Do not tune ZigZag to maximize strategy PnL after freeze.
7. Do not select indicators using full-history performance.
8. Do not introduce ML before deterministic feature baselines exist.
9. Do not introduce leverage optimization before realistic liquidation and fee simulation exists.
10. Never call structural target reach a trading win rate.

---

## Artifact governance

Every WIP must state where its artifacts live.  
Research artifacts should have immutable WIP/version identifiers.  
**Do not overwrite prior experiment artifacts.**

Preferred pattern:

`artifacts/<WIP-ID>/`

or the project-consistent equivalent (e.g. S13 `/var/tmp/traiding_pilot_ui_workspace/<experiment>/`).

Every WIP report must list: artifact path, row counts, time range, parameters, Git commit, runtime/server if relevant.

---

## Git governance

At WIP closure:

- Working tree must be understood.
- Commit project code/docs required for the WIP.
- Record `GIT_COMMIT=<sha>` in both `ROADMAP.md` and `docs/wip/<WIP-ID>.md`.
- Runtime data / Parquet / large research outputs must **not** be committed unless intentionally appropriate.

---

## User review gate

A coder saying **PASS** does **not** automatically close a WIP.

If visual / business / research interpretation is required → `STATUS=REVIEW` and return evidence to the user.

Only after accepted outcome → `CLOSED` or `CLOSED_NEGATIVE`.

Especially mandatory for: chart/UI behavior, geometry interpretation, strategy conclusions, model selection, real trading readiness.

---

## Dependency chain

```
ZIGZAG-NORMALIZATION-AND-DINAPOLI-RETEST-1
↓
WAVE-DATASET-FREEZE-1
↓
REVERSAL-EVENT-DATASET-1
↓
REVERSAL-INDICATOR-ENGINE-1
↓
VOLUME-ACCUMULATION-FEATURES-1
↓
INVERSE-INDICATOR-PREDICTOR-ENGINE-1
↓
PREDICTOR-CONFLUENCE-FEATURES-1
↓
REVERSAL-SIGNAL-EVENT-STUDY-1
↓
BYBIT-FUTURES-DATA-FOUNDATION-AND-LIVE-RECORDER-1
↓
HISTORICAL-FUTURES-BACKFILL-1
↓
FUTURES-VOLUME-OI-ORDERFLOW-FEATURES-1
↓
LIQUIDATION-PRESSURE-MAP-1
↓
REVERSAL-CONFLUENCE-STUDY-1
↓
REVERSAL-MODEL-V1
↓
FUTURES-RISK-AND-ENTRY-ENGINE-1
↓
FUTURES-EXECUTION-SIMULATOR-1
↓
OLD-VS-NEW-STRATEGY-RECONSTRUCTION-1
↓
WALK-FORWARD-BACKTEST-1
↓
LIVE-SHADOW-TRADING-1
↓
REAL-EXECUTION-READINESS-1
```

---

## Historical baselines (completed before roadmap authority)

### WIP=EXPERT-MANUAL-ANNOTATION-BASELINE-1

STATUS=CLOSED

PHASE=Pre-roadmap / Expert geometry

GOAL:  
Manual expert wave annotation on ETHUSDT for reconstruction targets.

WHY:  
Need a human geometric ground truth before automated ZigZag.

DEPENDS_ON:  
none

INPUTS:  
ETHUSDT OHLCV; expert chart UI

EXPECTED_OUTPUTS:  
Persisted annotation points (gold set includes `fc08e5a8-…`)

ACCEPTANCE_GATE:  
Annotation set available for reconstruction search

ARTIFACTS:  
S13 `/var/tmp/expert_annotation_fc08e5a8_points.csv` (and annotation store)

GIT_COMMIT:  
PENDING (pre-roadmap)

RESULT_SUMMARY:  
Gold expert set ~111 points on 4H used for classic ZigZag reconstruction.

NEXT_WIP:  
CLASSIC-ZIGZAG-EXPERT-GEOMETRY-RECONSTRUCTION-1

---

### WIP=CLASSIC-ZIGZAG-EXPERT-GEOMETRY-RECONSTRUCTION-1

STATUS=CLOSED

PHASE=Pre-roadmap / Wave engine candidates

GOAL:  
Recover classic ZigZag parameters matching expert pivots (percent / absolute / ATR grids).

WHY:  
Need a deterministic wave engine before DiNapoli tests.

DEPENDS_ON:  
EXPERT-MANUAL-ANNOTATION-BASELINE-1

INPUTS:  
Expert points; ETHUSDT 4H

EXPECTED_OUTPUTS:  
Frozen ZigZag config candidate

ACCEPTANCE_GATE:  
Holdout match quality sufficient to freeze a candidate

ARTIFACTS:  
`/var/tmp/traiding_pilot_ui_workspace/zigzag_reconstruction/`

GIT_COMMIT:  
PENDING (pre-roadmap)

RESULT_SUMMARY:  
Frozen `ZIGZAG_GEOMETRY_ENGINE_V1` = percent **1.5% / depth 3 / backstep 0**. Holdout F1 ≈ 0.886; parameter stability flagged UNSTABLE but visually usable.

NEXT_WIP:  
CLASSIC-ZIGZAG-LIVE-CHART-1

---

### WIP=CLASSIC-ZIGZAG-LIVE-CHART-1

STATUS=CLOSED

PHASE=Pre-roadmap / Visualization

GOAL:  
Render live ZigZag on the expert LWC chart without viewport thrash.

WHY:  
Human inspection of wave engine on arbitrary TF.

DEPENDS_ON:  
CLASSIC-ZIGZAG-EXPERT-GEOMETRY-RECONSTRUCTION-1

INPUTS:  
Frozen percent ZigZag defaults; chart engine

EXPECTED_OUTPUTS:  
SHOW ZIGZAG + APPLY controls

ACCEPTANCE_GATE:  
Browser acceptance PASS

ARTIFACTS:  
`visualization/zigzag_live.py`, LWC integration

GIT_COMMIT:  
PENDING (pre-roadmap)

RESULT_SUMMARY:  
Live ZigZag confirmed on chart; pivots + current unconfirmed leg.

NEXT_WIP:  
DINAPOLI-COP-OP-XOP-4H-VALIDATION-1

---

### WIP=DINAPOLI-COP-OP-XOP-4H-VALIDATION-1

STATUS=CLOSED

PHASE=Pre-roadmap / Geometry Validation (4H only)

GOAL:  
Test whether COP/OP/XOP (0.618/1/1.618) relate to next ZigZag endpoint on 4H.

WHY:  
Original DiNapoli geometric hypothesis before multitf.

DEPENDS_ON:  
CLASSIC-ZIGZAG-LIVE-CHART-1

INPUTS:  
Percent ZigZag 1.5%/D3/B0; ETHUSDT 4H

EXPECTED_OUTPUTS:  
R distribution, reach rates, baselines, live SHOW DINAPOLI

ACCEPTANCE_GATE:  
Reported validation metrics + live UI

ARTIFACTS:  
`/var/tmp/traiding_pilot_ui_workspace/dinapoli_4h_validation/`

GIT_COMMIT:  
PENDING (pre-roadmap)

RESULT_SUMMARY:  
R median ≈ 1.03; COP/OP/XOP reach ≈ 0.76/0.52/0.27; signal **MODERATE**. Ratios not sharp multimodal peaks. Ready for multitf.

NEXT_WIP:  
DINAPOLI-COP-OP-XOP-MULTITIMEFRAME-SWEEP-1

---

### WIP=DINAPOLI-COP-OP-XOP-MULTITIMEFRAME-SWEEP-1

STATUS=CLOSED_NEGATIVE

PHASE=Pre-roadmap / Geometry Validation (fixed ZZ)

GOAL:  
With **identical** percent ZigZag across TFs, find where COP/OP/XOP geometry is most pronounced.

WHY:  
TF as independent variable (no per-TF ZigZag tuning).

DEPENDS_ON:  
DINAPOLI-COP-OP-XOP-4H-VALIDATION-1

INPUTS:  
Fixed ZZ 1.5%/D3/B0; TFs 5m…1D

EXPECTED_OUTPUTS:  
Multitf tables, control-ratio densities, bootstrap CIs

ACCEPTANCE_GATE:  
Reported rankings + control comparison

ARTIFACTS:  
`/var/tmp/traiding_pilot_ui_workspace/dinapoli_multitf_sweep/` — labeled **FIXED_ZZ_BASELINE_V1** (immutable)

GIT_COMMIT:  
PENDING (pre-roadmap)

RESULT_SUMMARY:  
**NEGATIVE for Fibonacci-specific modes.** R≈1 on all TFs; path reach consistent; densities at 0.618/1/1.618 not special vs controls. Fixed ZZ pathological on 5m–1H (TOO_DENSE) and 1D (MOVE_TOO_LARGE). Best research TF among comparable: **2H**. Forced next step: ZigZag normalization.

NEXT_WIP:  
ZIGZAG-NORMALIZATION-AND-DINAPOLI-RETEST-1

---

### WIP=PROJECT-RESEARCH-ROADMAP-AND-WIP-GOVERNANCE-1

STATUS=CLOSED

PHASE=Governance

GOAL:  
Establish `ROADMAP.md` as project authority; WIP template; status/closure/anti-leakage rules.

WHY:  
Prevent ad hoc phase skipping and loss of negative results.

DEPENDS_ON:  
none (meta)

INPUTS:  
Completed geometry WIPs; project principle WHERE≠WHEN

EXPECTED_OUTPUTS:  
`ROADMAP.md`, `docs/wip/*`, README link

ACCEPTANCE_GATE:  
Roadmap lists all phases; current WIP visible; template + rules documented

ARTIFACTS:  
this file; `docs/wip/`

GIT_COMMIT:  
ea6e7e83b0ede9793a62a2fe5dfdc2d067573b26

RESULT_SUMMARY:  
Roadmap authority established. Primary research WIP remains Phase 0 normalization retest (REVIEW).

NEXT_WIP:  
Accept/close `ZIGZAG-NORMALIZATION-AND-DINAPOLI-RETEST-1`, then `WAVE-DATASET-FREEZE-1`

---

## PHASE 0 — Geometry Validation

### WIP=ZIGZAG-NORMALIZATION-AND-DINAPOLI-RETEST-1

STATUS=CLOSED

PHASE=0 — Geometry Validation

GOAL:  
Normalize ZigZag wave significance across timeframes and finish the original geometry question. Determine whether R≈1 persists after normalization; whether 0.618/1.000/1.618 have special predictive significance; whether structure is better described by a continuous next-wave magnitude distribution.

WHY:  
Fixed-percent multitf was confounded by pathological pivot density; cannot cleanly compare TFs or close Fibonacci hypothesis without normalized swings.

DEPENDS_ON:  
DINAPOLI-COP-OP-XOP-MULTITIMEFRAME-SWEEP-1 CLOSED_NEGATIVE

INPUTS:  
ETHUSDT TFs 5m…1D; FIXED_ZZ_BASELINE_V1 (immutable); ATR / vol-percent ZigZag families

EXPECTED_OUTPUTS:  
Normalized ZZ config; retest of R / COP-OP-XOP / controls; classification freeze note

ACCEPTANCE_GATE:  
Do not proceed to market-context research until reported and closed. If Fibonacci-specific attraction unsupported → **do not** continue tuning Fibonacci ratios; preserve negative result.

ARTIFACTS:  
`/var/tmp/traiding_pilot_ui_workspace/dinapoli_normalized_retest/`  
Report: `docs/wip/ZIGZAG-NORMALIZATION-AND-DINAPOLI-RETEST-1.md`

GIT_COMMIT:  
PENDING

RESULT_SUMMARY:  
**Accepted CLOSED (experiment succeeded; Fibonacci-specific hypothesis unsupported).**  
`DINAPOLI_SPECIFIC_RATIOS_SUPPORTED=NO`; COP/OP/XOP ratio special = NO/NO/NO.  
`LEG_PERSISTENCE_SUPPORTED=YES`; `CONTINUOUS_WAVE_DISTRIBUTION_SUPPORTED=YES`.  
R median across TFs ≈ 1. No reproducible special density at 0.618/1.000/1.618 vs controls.  
Freeze: `DINAPOLI_SPECIFIC_RATIOS_NOT_SUPPORTED`. Retain wave geometry, R≈1 baseline, empirical R distribution.  
No single global ATR; group configs. `GEOMETRY_COMPARABLE_ACROSS_TF=NO`. 1H flagged MARGINAL_TOO_DENSE.

NEXT_WIP:  
WAVE-DATASET-FREEZE-1

---

## PHASE 1 — Wave Engine Freeze

### WIP=WAVE-DATASET-FREEZE-1

STATUS=CLOSED

PHASE=1 — Wave Engine Freeze

GOAL:  
Freeze deterministic wave construction. Persist `WAVE_ENGINE_VERSION`, ZigZag type, normalization method, parameters. Generate full historical `Z0→Zn` with leg attributes (times, prices, direction, move_abs/pct/atr, duration, R vs preceding structures).

WHY:  
Downstream WHEN/WHERE research needs an immutable wave dataset.

DEPENDS_ON:  
ZIGZAG-NORMALIZATION-AND-DINAPOLI-RETEST-1 CLOSED

INPUTS:  
Accepted normalized (group) ZigZag freeze decision from Phase 0

EXPECTED_OUTPUTS:  
Versioned wave parquet/CSV + parameter manifest (`WAVE_ENGINE_V1` / `WAVE_DATASET_V1`)

ACCEPTANCE_GATE:  
Parameters frozen; **must not** later be optimized to improve trading PnL; STATUS→REVIEW for user acceptance before CLOSED

ARTIFACTS:  
S13 `/var/tmp/traiding_pilot_ui_workspace/wave_dataset_v1/`  
Local manifests: `artifacts/WAVE-DATASET-FREEZE-1/`  
Report: `docs/wip/WAVE-DATASET-FREEZE-1.md`

GIT_COMMIT:  
841ffa24dde1793dc4f98e9b379b6d2a879e32aa

RESULT_SUMMARY:  
**CLOSED.** `WAVE_ENGINE_V1` + `WAVE_DATASET_V1` accepted. Decisions: `DINAPOLI_SPECIFIC_RATIOS_NOT_SUPPORTED`, `WAVE_GEOMETRY_SUPPORTED`, `LEG_PERSISTENCE_SUPPORTED`, `R_IS_CONTINUOUS_TARGET`, `LEG_PERSISTENCE_BASELINE_V1` (R_BASELINE=1.0). Do not modify WAVE_DATASET_V1.

NEXT_WIP:  
REVERSAL-EVENT-DATASET-1

---

## PHASE 2 — Reversal Event Dataset

### WIP=REVERSAL-EVENT-DATASET-1

STATUS=REVIEW

PHASE=2 — Reversal Event Dataset

GOAL:  
Turn historical wave pivots into causal reversal-study events. True pivot C is retrospective label only. Synchronized causal windows from 4H/1H/15m/5m (and other TFs if Phase 0 justifies).

WHY:  
Enable WHEN studies without leakage from future bars.

DEPENDS_ON:  
WAVE-DATASET-FREEZE-1 CLOSED

INPUTS:  
Frozen `WAVE_DATASET_V1` (immutable)

EXPECTED_OUTPUTS:  
`REVERSAL_EVENT_DATASET_V1` + schema registry + anti-leakage API

ACCEPTANCE_GATE:  
WAVE_DATASET_V1 unchanged; causal vs retrospective columns separated; anti-leakage tests PASS; STATUS→REVIEW before CLOSED

ARTIFACTS:  
S13 `/var/tmp/traiding_pilot_ui_workspace/reversal_event_dataset_v1/`  
`artifacts/REVERSAL-EVENT-DATASET-1/`  
`docs/wip/REVERSAL-EVENT-DATASET-1.md`

GIT_COMMIT:  
9d4d6e53d5602d96750a8a95deb118492ff86af3

RESULT_SUMMARY:  
**REVIEW.** REVERSAL_EVENT_DATASET_V1 frozen on S13. 9992 events from WAVE_DATASET_V1 (unchanged). Schema registry + anti-leakage API/tests PASS. Chronological 60/20/20 partitions with outcome-boundary purge (19 purged). Incomplete multi-TF context marked, not dropped. Do **not** activate indicator engine until CLOSED.

NEXT_WIP:  
REVERSAL-INDICATOR-ENGINE-1 (only after CLOSED)

---

## PHASE 3 — Indicator Engine

### WIP=REVERSAL-INDICATOR-ENGINE-1

STATUS=PLANNED

PHASE=3 — Indicator Engine

GOAL:  
One deterministic causal indicator library. First priority: DiNapoli-style DMA 3x3 / 7x5 / 25x5, Stochastic + displaced, MACD + displaced; then standard momentum/trend/volatility/candle families. Mandatory time semantics: `CALCULATED_AT` / `AVAILABLE_AT` / `DISPLAYED_AT`.

WHY:  
Shared causal feature substrate for WHEN signals.

DEPENDS_ON:  
REVERSAL-EVENT-DATASET-1

INPUTS:  
OHLCV per TF; displacement rules

EXPECTED_OUTPUTS:  
Indicator library + availability timestamps

ACCEPTANCE_GATE:  
Displacement never creates future leakage; unit tests for time semantics

ARTIFACTS:  
`artifacts/REVERSAL-INDICATOR-ENGINE-1/` (planned)

GIT_COMMIT:  
PENDING

RESULT_SUMMARY:  
PENDING

NEXT_WIP:  
VOLUME-ACCUMULATION-FEATURES-1

---

## PHASE 4 — Volume and Accumulation Engine

### WIP=VOLUME-ACCUMULATION-FEATURES-1

STATUS=PLANNED

PHASE=4 — Volume and Accumulation

GOAL:  
Mathematically describe volume, compression, and accumulation (relative volume, z-scores, range duration/width, ATR/vol contraction, bars/volume inside range, false breakouts, rejection/breakout strength).

WHY:  
Market-context features after geometry freeze.

DEPENDS_ON:  
REVERSAL-INDICATOR-ENGINE-1

INPUTS:  
OHLCV volume; event windows

EXPECTED_OUTPUTS:  
Causal volume/accumulation feature tables

ACCEPTANCE_GATE:  
Features causal; no futures enrichment required yet

ARTIFACTS:  
`artifacts/VOLUME-ACCUMULATION-FEATURES-1/` (planned)

GIT_COMMIT:  
PENDING

RESULT_SUMMARY:  
PENDING

NEXT_WIP:  
INVERSE-INDICATOR-PREDICTOR-ENGINE-1

---

## PHASE 5 — Inverse Indicator Predictor Engine

### WIP=INVERSE-INDICATOR-PREDICTOR-ENGINE-1

STATUS=PLANNED

PHASE=5 — Inverse Predictors

GOAL:  
Build our own predictors: at what future **PRICE** would an indicator signal? DMA / Stochastic / MACD / RSI / oscillator predictors where feasible. Output `PREDICTOR_PRICE`, `CALCULATED_AT`, validity/invalidation semantics.

WHY:  
WHERE-layer structure without proprietary DiNapoli code recovery.

DEPENDS_ON:  
VOLUME-ACCUMULATION-FEATURES-1  
(also needs indicator engine)

INPUTS:  
Causal indicator definitions

EXPECTED_OUTPUTS:  
Predictor price series + invalidation rules

ACCEPTANCE_GATE:  
No attempt to recover proprietary DiNapoli code; own inverse formulas validated for causality

ARTIFACTS:  
`artifacts/INVERSE-INDICATOR-PREDICTOR-ENGINE-1/` (planned)

GIT_COMMIT:  
PENDING

RESULT_SUMMARY:  
PENDING

NEXT_WIP:  
PREDICTOR-CONFLUENCE-FEATURES-1

---

## PHASE 6 — Predictor Confluence

### WIP=PREDICTOR-CONFLUENCE-FEATURES-1

STATUS=PLANNED

PHASE=6 — Predictor Confluence

GOAL:  
Measure whether independent predicted reversal levels cluster (`PREDICTOR_COUNT`, cluster width, distance, counts within 0.10/0.25/0.50%).

WHY:  
Test association of tight WHERE clusters with subsequent real reversals.

DEPENDS_ON:  
INVERSE-INDICATOR-PREDICTOR-ENGINE-1

INPUTS:  
Predictor price outputs; reversal events

EXPECTED_OUTPUTS:  
Confluence feature table + association study

ACCEPTANCE_GATE:  
Association tested without claiming WHEN entry

ARTIFACTS:  
`artifacts/PREDICTOR-CONFLUENCE-FEATURES-1/` (planned)

GIT_COMMIT:  
PENDING

RESULT_SUMMARY:  
PENDING

NEXT_WIP:  
REVERSAL-SIGNAL-EVENT-STUDY-1

---

## PHASE 7 — WHEN — Single Signal Tournament

### WIP=REVERSAL-SIGNAL-EVENT-STUDY-1

STATUS=PLANNED

PHASE=7 — WHEN (core)

GOAL:  
For every retrospective true pivot C, find earliest causally available reversal signals. Measure delay, price distance, FPR, remaining expected wave, MAE/MFE, target reach. Separate winners: earliest, lowest FPR, lowest MAE, best MFE/MAE, best target reach, most stable, best by TF.

WHY:  
Core WHEN question; must not conflate with WHERE.

DEPENDS_ON:  
PREDICTOR-CONFLUENCE-FEATURES-1

INPUTS:  
Event dataset; indicator + predictor signals

EXPECTED_OUTPUTS:  
Tournament tables by criterion

ACCEPTANCE_GATE:  
Not ranked only by accuracy; multi-criteria winners reported

ARTIFACTS:  
`artifacts/REVERSAL-SIGNAL-EVENT-STUDY-1/` (planned)

GIT_COMMIT:  
PENDING

RESULT_SUMMARY:  
PENDING

NEXT_WIP:  
BYBIT-FUTURES-DATA-FOUNDATION-AND-LIVE-RECORDER-1  
(or continue if recorder already ACTIVE in parallel)

---

## PHASE 8 — Bybit Futures Data Foundation

### WIP=BYBIT-FUTURES-DATA-FOUNDATION-AND-LIVE-RECORDER-1

STATUS=PLANNED

PHASE=8 — Futures Data Foundation

GOAL:  
Start and maintain permanent ETHUSDT Linear Perpetual public live collection on **S7**: `publicTrade`, `tickers`, `allLiquidation`, `orderbook.50`. Parquet/ZSTD for HF; PostgreSQL for metadata/health/research results only.

WHY:  
Microstructure history is non-recoverable if not recorded.

DEPENDS_ON:  
May start early (parallel exception); conceptually after/alongside Phase 7 for research use

INPUTS:  
Bybit public WS; S7 host

EXPECTED_OUTPUTS:  
Live recorder + health metrics

ACCEPTANCE_GATE:  
Stable capture; no trading API key required

ARTIFACTS:  
S7 data roots (to be documented at start)

GIT_COMMIT:  
PENDING

RESULT_SUMMARY:  
PENDING

NEXT_WIP:  
HISTORICAL-FUTURES-BACKFILL-1

---

## PHASE 9 — Historical Futures Backfill

### WIP=HISTORICAL-FUTURES-BACKFILL-1

STATUS=PLANNED

PHASE=9 — Historical Backfill

GOAL:  
Backfill as much ETHUSDT perpetual history as possible from official Bybit sources first; produce DATA GAP MATRIX; paid sources only with explicit user decision.

WHY:  
Research needs history beyond live recorder start.

DEPENDS_ON:  
BYBIT-FUTURES-DATA-FOUNDATION-AND-LIVE-RECORDER-1

INPUTS:  
Official Bybit historical APIs/downloads

EXPECTED_OUTPUTS:  
Backfilled datasets + gap matrix

ACCEPTANCE_GATE:  
Gap matrix complete; no purchase without user decision

ARTIFACTS:  
`artifacts/HISTORICAL-FUTURES-BACKFILL-1/` (planned)

GIT_COMMIT:  
PENDING

RESULT_SUMMARY:  
PENDING

NEXT_WIP:  
FUTURES-VOLUME-OI-ORDERFLOW-FEATURES-1

---

## PHASE 10 — Futures Market Features

### WIP=FUTURES-VOLUME-OI-ORDERFLOW-FEATURES-1

STATUS=PLANNED

PHASE=10 — Futures Features

GOAL:  
Causal OI / funding / basis / trade / orderbook features.

WHY:  
Microstructure context for WHEN/WHERE confluence.

DEPENDS_ON:  
HISTORICAL-FUTURES-BACKFILL-1

INPUTS:  
Futures datasets

EXPECTED_OUTPUTS:  
Feature tables with availability timestamps

ACCEPTANCE_GATE:  
Causal only; documented definitions

ARTIFACTS:  
`artifacts/FUTURES-VOLUME-OI-ORDERFLOW-FEATURES-1/` (planned)

GIT_COMMIT:  
PENDING

RESULT_SUMMARY:  
PENDING

NEXT_WIP:  
LIQUIDATION-PRESSURE-MAP-1

---

## PHASE 11 — Liquidation Engine

### WIP=LIQUIDATION-PRESSURE-MAP-1

STATUS=PLANNED

PHASE=11 — Liquidation Engine

GOAL:  
(A) Actual liquidation aggregates; (B) estimated liquidation pressure with exchange-correct rules for 10x–50x long/short — not crude 1/leverage. Validate estimated clusters vs subsequent actual bursts.

WHY:  
Adverse excursion / cascade risk for futures strategy.

DEPENDS_ON:  
FUTURES-VOLUME-OI-ORDERFLOW-FEATURES-1

INPUTS:  
Liquidation events; mark/OI/volume

EXPECTED_OUTPUTS:  
Actual + estimated maps; validation study

ACCEPTANCE_GATE:  
Exchange-correct formulas; validation reported

ARTIFACTS:  
`artifacts/LIQUIDATION-PRESSURE-MAP-1/` (planned)

GIT_COMMIT:  
PENDING

RESULT_SUMMARY:  
PENDING

NEXT_WIP:  
REVERSAL-CONFLUENCE-STUDY-1

---

## PHASE 12 — Reversal Confluence

### WIP=REVERSAL-CONFLUENCE-STUDY-1

STATUS=PLANNED

PHASE=12 — Reversal Confluence

GOAL:  
Combine only individually validated signal families (geometry, indicators, predictors, confluence, volume, accumulation, OI, funding, basis, order flow, liquidations). Avoid brute-force combinatorial overfitting.

WHY:  
Test whether combinations improve WHEN detection.

DEPENDS_ON:  
LIQUIDATION-PRESSURE-MAP-1  
(and prior validated feature WIPs)

INPUTS:  
Validated feature families only

EXPECTED_OUTPUTS:  
Confluence study with anti-overfit protocol

ACCEPTANCE_GATE:  
No kitchen-sink search; discovery/validation split enforced

ARTIFACTS:  
`artifacts/REVERSAL-CONFLUENCE-STUDY-1/` (planned)

GIT_COMMIT:  
PENDING

RESULT_SUMMARY:  
PENDING

NEXT_WIP:  
REVERSAL-MODEL-V1

---

## PHASE 13 — Reversal Model V1

### WIP=REVERSAL-MODEL-V1

STATUS=PLANNED

PHASE=13 — ML V1

GOAL:  
ML only after deterministic features validated. Explicit probabilistic/regression targets (not generic candles→BUY/SELL). Start with Logistic / Ridge / CatBoost / LightGBM.

WHY:  
Structured learning on validated features.

DEPENDS_ON:  
REVERSAL-CONFLUENCE-STUDY-1

INPUTS:  
Frozen feature sets; event labels

EXPECTED_OUTPUTS:  
Model cards + OOS metrics

ACCEPTANCE_GATE:  
No RL in V1; neural only if simpler models hit a real ceiling

ARTIFACTS:  
`artifacts/REVERSAL-MODEL-V1/` (planned)

GIT_COMMIT:  
PENDING

RESULT_SUMMARY:  
PENDING

NEXT_WIP:  
FUTURES-RISK-AND-ENTRY-ENGINE-1

---

## PHASE 14 — Trading / Risk Engine

### WIP=FUTURES-RISK-AND-ENTRY-ENGINE-1

STATUS=PLANNED

PHASE=14 — Risk / Entry

GOAL:  
Strategy principle: WHERE → WAIT → WHEN → **one entry** (no averaging ladder). Pre-trade: size, margin, liquidation price, distance vs empirical MAE; reject or reduce leverage if incompatible.

WHY:  
Separate execution risk from signal research.

DEPENDS_ON:  
REVERSAL-MODEL-V1

INPUTS:  
Signals; MAE distributions by class; exchange risk params

EXPECTED_OUTPUTS:  
Risk gate library + decision logs

ACCEPTANCE_GATE:  
No averaging in primary new strategy; liquidation distance check mandatory

ARTIFACTS:  
`artifacts/FUTURES-RISK-AND-ENTRY-ENGINE-1/` (planned)

GIT_COMMIT:  
PENDING

RESULT_SUMMARY:  
PENDING

NEXT_WIP:  
FUTURES-EXECUTION-SIMULATOR-1

---

## PHASE 15 — Futures Execution Simulator

### WIP=FUTURES-EXECUTION-SIMULATOR-1

STATUS=PLANNED

PHASE=15 — Execution Simulator

GOAL:  
Realistic futures simulation at 3x/5x/7x/10x with fees, funding, spread, slippage, mark-price liquidation, maintenance margin, risk tiers, liquidation fee.

WHY:  
Spot candle close is not a futures execution model.

DEPENDS_ON:  
FUTURES-RISK-AND-ENTRY-ENGINE-1

INPUTS:  
Risk engine; futures market data

EXPECTED_OUTPUTS:  
Simulator + leverage grids

ACCEPTANCE_GATE:  
Mark-price liquidation path; fees/funding included

ARTIFACTS:  
`artifacts/FUTURES-EXECUTION-SIMULATOR-1/` (planned)

GIT_COMMIT:  
PENDING

RESULT_SUMMARY:  
PENDING

NEXT_WIP:  
OLD-VS-NEW-STRATEGY-RECONSTRUCTION-1

---

## PHASE 16 — Old Strategy Reconstruction

### WIP=OLD-VS-NEW-STRATEGY-RECONSTRUCTION-1

STATUS=PLANNED

PHASE=16 — Old vs New

GOAL:  
Reconstruct historical manual strategy (zone → pending → x10 → averaging up to ~50% margin) vs new WHERE→WAIT→WHEN→one entry. Mandatory metric: `OLD_LIQUIDATED_BUT_TARGET_LATER_REACHED`.

WHY:  
Quantify why the old strategy failed.

DEPENDS_ON:  
FUTURES-EXECUTION-SIMULATOR-1

INPUTS:  
Identical periods/data; both strategy definitions

EXPECTED_OUTPUTS:  
Head-to-head metrics (WR, expectancy, PF, DD, liquidations, fees, funding, MAE/MFE)

ACCEPTANCE_GATE:  
Mandatory liquidation-vs-later-target metric present

ARTIFACTS:  
`artifacts/OLD-VS-NEW-STRATEGY-RECONSTRUCTION-1/` (planned)

GIT_COMMIT:  
PENDING

RESULT_SUMMARY:  
PENDING

NEXT_WIP:  
WALK-FORWARD-BACKTEST-1

---

## PHASE 17 — Walk-Forward Validation

### WIP=WALK-FORWARD-BACKTEST-1

STATUS=PLANNED

PHASE=17 — Walk-Forward

GOAL:  
TRAIN → VALIDATE → FREEZE → FUTURE TEST; then rolling walk-forward. Final metrics: expectancy, PF, max DD, return/DD, Sharpe, Sortino, liquidations, P95 MAE, fees, funding, OOS return.

WHY:  
No final result from train=test history.

DEPENDS_ON:  
OLD-VS-NEW-STRATEGY-RECONSTRUCTION-1

INPUTS:  
Frozen strategy; simulator

EXPECTED_OUTPUTS:  
Walk-forward report

ACCEPTANCE_GATE:  
Explicit freeze before future test

ARTIFACTS:  
`artifacts/WALK-FORWARD-BACKTEST-1/` (planned)

GIT_COMMIT:  
PENDING

RESULT_SUMMARY:  
PENDING

NEXT_WIP:  
LIVE-SHADOW-TRADING-1

---

## PHASE 18 — Live Shadow Trading

### WIP=LIVE-SHADOW-TRADING-1

STATUS=PLANNED

PHASE=18 — Shadow

GOAL:  
Frozen strategy on live data without money; persist every decision before outcome known; no retrospective rewriting.

WHY:  
Bridge from backtest to operational reality.

DEPENDS_ON:  
WALK-FORWARD-BACKTEST-1

INPUTS:  
Live recorder; frozen strategy

EXPECTED_OUTPUTS:  
Shadow decision log + outcomes

ACCEPTANCE_GATE:  
Pre-outcome persistence proven

ARTIFACTS:  
`artifacts/LIVE-SHADOW-TRADING-1/` (planned)

GIT_COMMIT:  
PENDING

RESULT_SUMMARY:  
PENDING

NEXT_WIP:  
REAL-EXECUTION-READINESS-1

---

## PHASE 19 — Real Execution Gate

### WIP=REAL-EXECUTION-READINESS-1

STATUS=PLANNED

PHASE=19 — Real Execution Gate

GOAL:  
Determine readiness for any real-money pilot (API reliability, latency, spread, slippage, fees, funding, order lifecycle, restart/recovery). **Do not enable trading automatically.** Real-money activation always requires separate explicit user decision.

WHY:  
Final safety gate.

DEPENDS_ON:  
LIVE-SHADOW-TRADING-1

INPUTS:  
Shadow ops evidence; exchange connectivity tests

EXPECTED_OUTPUTS:  
Readiness checklist + go/no-go recommendation

ACCEPTANCE_GATE:  
User explicit decision required for any live money

ARTIFACTS:  
`artifacts/REAL-EXECUTION-READINESS-1/` (planned)

GIT_COMMIT:  
PENDING

RESULT_SUMMARY:  
PENDING

NEXT_WIP:  
none (end of planned chain)

---

## WIP index

| WIP ID | Status | Phase |
|---|---|---|
| EXPERT-MANUAL-ANNOTATION-BASELINE-1 | CLOSED | Historical |
| CLASSIC-ZIGZAG-EXPERT-GEOMETRY-RECONSTRUCTION-1 | CLOSED | Historical |
| CLASSIC-ZIGZAG-LIVE-CHART-1 | CLOSED | Historical |
| DINAPOLI-COP-OP-XOP-4H-VALIDATION-1 | CLOSED | Historical |
| DINAPOLI-COP-OP-XOP-MULTITIMEFRAME-SWEEP-1 | CLOSED_NEGATIVE | Historical |
| PROJECT-RESEARCH-ROADMAP-AND-WIP-GOVERNANCE-1 | CLOSED | Governance |
| ZIGZAG-NORMALIZATION-AND-DINAPOLI-RETEST-1 | CLOSED | 0 |
| WAVE-DATASET-FREEZE-1 | CLOSED | 1 |
| REVERSAL-EVENT-DATASET-1 | REVIEW | 2 |
| REVERSAL-INDICATOR-ENGINE-1 | PLANNED | 3 |
| VOLUME-ACCUMULATION-FEATURES-1 | PLANNED | 4 |
| INVERSE-INDICATOR-PREDICTOR-ENGINE-1 | PLANNED | 5 |
| PREDICTOR-CONFLUENCE-FEATURES-1 | PLANNED | 6 |
| REVERSAL-SIGNAL-EVENT-STUDY-1 | PLANNED | 7 |
| BYBIT-FUTURES-DATA-FOUNDATION-AND-LIVE-RECORDER-1 | PLANNED | 8 |
| HISTORICAL-FUTURES-BACKFILL-1 | PLANNED | 9 |
| FUTURES-VOLUME-OI-ORDERFLOW-FEATURES-1 | PLANNED | 10 |
| LIQUIDATION-PRESSURE-MAP-1 | PLANNED | 11 |
| REVERSAL-CONFLUENCE-STUDY-1 | PLANNED | 12 |
| REVERSAL-MODEL-V1 | PLANNED | 13 |
| FUTURES-RISK-AND-ENTRY-ENGINE-1 | PLANNED | 14 |
| FUTURES-EXECUTION-SIMULATOR-1 | PLANNED | 15 |
| OLD-VS-NEW-STRATEGY-RECONSTRUCTION-1 | PLANNED | 16 |
| WALK-FORWARD-BACKTEST-1 | PLANNED | 17 |
| LIVE-SHADOW-TRADING-1 | PLANNED | 18 |
| REAL-EXECUTION-READINESS-1 | PLANNED | 19 |
