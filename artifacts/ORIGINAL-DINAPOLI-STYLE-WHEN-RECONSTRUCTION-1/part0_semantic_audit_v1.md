# Part 0 — Semantic audit of REVERSAL-SIGNAL-EVENT-STUDY-1

**WIP:** `ORIGINAL-DINAPOLI-STYLE-WHEN-RECONSTRUCTION-1`  
**Audited study:** `REVERSAL-SIGNAL-EVENT-STUDY-1` (`REVERSAL_SIGNAL_EVENT_STUDY_V1`)  
**Immutable baseline:** `artifacts/REVERSAL-SIGNAL-EVENT-STUDY-1/REVERSAL_SIGNAL_EVENT_STUDY_V1_INITIAL/`  
**Authority:** code in `reversal_signal_study/` + `INDICATOR_ENGINE_V1` + V1_INITIAL manifest

---

## Correction (binding)

`REVERSAL-SIGNAL-EVENT-STUDY-1` is a **valid single-candidate baseline tournament**.

It is **not** a test of the original composite DiNapoli-style strategy.

Therefore:

```
PRICE_BASELINE_BEATEN=NO
```

from that study must **not** be read as evidence that displaced/confluence logic failed.
The original composite hypothesis has **not yet been tested**.

Do not rewrite V1_INITIAL results.

---

## Exact audit answers

```
PREVIOUS_DMA_IMPLEMENTATION=
  INDICATOR_ENGINE_V1 DMA (SMA(period) + display_shift metadata).
  Candidates: DMA_3X3_V1, DMA_7X5_V1, DMA_25X5_V1.
  Signals: PRICE_CROSS_UP_DMA | PRICE_CROSS_DOWN_DMA from signal_primitives
  at the SAME bar index i as close[i] vs SMA[i].
  generate_indicator_pair_signals uses sample.available_at == close_time[i].
  display_shift only sets DISPLAYED_AT; it does NOT enter the cross.

PREVIOUS_DMA_SIGNAL_ALIGNMENT=SOURCE_ALIGNED

PREVIOUS_STOCH_IMPLEMENTATION=
  STOCH_14_3_3_V1 (k=14, k_smooth=3, d=3, display_shift=0).
  Signals evaluated:
    K_CROSS_UP_D | K_CROSS_DOWN_D
    K_CROSS_UP_LEVEL | K_CROSS_DOWN_LEVEL
  (level exit = cross of oversold=20 / overbought=80).
  DISPLACED_STOCHASTIC parameter sets were NOT in the candidate registry.

PREVIOUS_STOCH_WAS_STANDARD_14_3_3=YES
PREVIOUS_DISPLACED_STOCH_EVALUATED=NO

PREVIOUS_MACD_IMPLEMENTATION=
  MACD_12_26_9_V1 (fast=12, slow=26, signal=9, display_shift=0).
  Signals:
    MACD_CROSS_UP_SIGNAL | MACD_CROSS_DOWN_SIGNAL
    HISTOGRAM_CROSS_UP_ZERO | HISTOGRAM_CROSS_DOWN_ZERO
  DISPLACED_MACD parameter sets were NOT in the candidate registry.

PREVIOUS_MACD_WAS_STANDARD_12_26_9=YES
PREVIOUS_DISPLACED_MACD_EVALUATED=NO

RSI_30_70_EVALUATED=YES
  (RSI_14_V1: RSI_CROSS_UP_30 | RSI_CROSS_DOWN_70 as single directional candidates)

STOCH_20_80_EVALUATED=YES
  (via K_CROSS_*_LEVEL using default oversold=20 / overbought=80;
   evaluated as standalone crosses, not as OB/OS-state + confirmation composite)

STOCH_OVERBOUGHT_OVERSOLD_RECROSS_EVALUATED=NO
  (no “was OS/OB then K×D / exit” composite semantics)

MACD_OVERBOUGHT_OVERSOLD_CONCEPT=NOT_APPLICABLE
  (no documented normalized MACD oscillator OB/OS in INDICATOR_ENGINE_V1)

VOLUME_CONTEXT_EVALUATION_VALID=NO
  (context metrics show n_all_near_c=0; family_best VOLUME_CONTEXT=NONE;
   CONTEXT_ENRICHMENT_FOUND=NO; known timestamp→UTC-ns plumbing defect;
   VOLUME_ACCUMULATION_ENGINE_V1 itself not implicated)

PREDICTOR_EVALUATION_VALID=NO
  (full continuous predictor scan deferred; PREDICTOR_BEATS_NORMAL=INCONCLUSIVE;
   registry present but not a completed fair evaluation)

COP_OP_XOP_USED_AS_ACTIVATION_GATE=NO
  (COP/OP/XOP exist in wave/geometry research; NOT used as WHEN SEARCH_FOR_WHEN arm
   in REVERSAL-SIGNAL-EVENT-STUDY-1)

COMPOSITE_DMA_STOCH_MACD_TESTED=NO
VOLATILITY_GATE_USED=NO
```

### Compact flags for RETURN

```
PREVIOUS_STUDY_TESTED_TRUE_DISPLACED_DMA=NO
PREVIOUS_STUDY_TESTED_TRUE_DISPLACED_STOCH=NO
PREVIOUS_STUDY_TESTED_TRUE_DISPLACED_MACD=NO
PREVIOUS_STUDY_TESTED_OB_OS=PARTIAL
  (RSI 30/70 and Stoch level exits as singles; no Stoch OB/OS+cross composite)
PREVIOUS_STUDY_TESTED_GEOMETRY_GATE=NO
PREVIOUS_STUDY_TESTED_VOLATILITY_GATE=NO
PREVIOUS_STUDY_TESTED_COMPOSITE_SIGNAL=NO
```

---

## Part 1 — Display-aligned semantics (definition used going forward)

At decision time `T`:

| Field | Meaning |
|---|---|
| `SOURCE_TIME` | Bar index `i` where the formula is evaluated (source bar) |
| `CALCULATED_AT` | `close_time[i]` of the source bar |
| `AVAILABLE_AT` | Earliest causal use = `CALCULATED_AT` (closed candle) |
| `DISPLAYED_AT` | Chart position = `open_time[i + display_shift]` (engine) / decision bar for study layer |
| `DECISION_TIME` | `T` when the system may fire; requires `DISPLAYED_AT == T` and `AVAILABLE_AT <= T` |

**DISPLAY_ALIGNED:** use the sample with `DISPLAYED_AT = T` and `AVAILABLE_AT <= T`.  
No future information. This is causal because calculation occurred at `i = T − shift`.

**SOURCE_ALIGNED (what previous study used):** primitives at index `i` with `AVAILABLE_AT = close_time[i]`, ignoring chart displacement for the cross.

### Family mapping (this reconstruction)

**DMA (period P, shift S)** at decision bar `j` (`T = close_time[j]`):

- `SOURCE_TIME` = bar `j − S`
- `CALCULATED_AT` = `AVAILABLE_AT` = `close_time[j − S]`
- `DISPLAYED_AT` ≈ chart bar `j` (decision alignment)
- Cross: `close[j]` vs `SMA[j−S]` (and prior bar), not `SMA[j]`

**Stochastic / MACD:** same display-alignment rule for K/D or MACD/signal values.

---

## Evidence pointers

| Claim | Source |
|---|---|
| DMA same-bar cross | `indicator_engine/dma.py` PRICE_CROSS_* vs `ma[i]` |
| Signal time = available_at of source sample | `reversal_signal_study/signals.py` `generate_indicator_pair_signals` |
| Stoch/MACD shift=0 in registry | `candidates.py` + `indicator_engine/registry.py` |
| Displaced sets unused | Registry has `DISPLACED_STOCH_*` / `DISPLACED_MACD_*`; candidates.py does not reference them |
| Context near-C = 0 | `multiple_testing_v1.csv` / manifest `VOLUME_CONTEXT: NONE` |
| No composite / no vol gate / no COP arm | Candidate roles are single DIRECTIONAL_TRIGGER or NON_DIRECTIONAL_CONTEXT |

---

## SEMANTIC_AUDIT_COMPLETE=YES

Proceeding to Parts 1–20 only after this document exists.
