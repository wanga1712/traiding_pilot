# Indicator formula spec v1

## CONTIGUOUS_SEGMENT_POLICY

A new contiguous segment begins at index `0` or wherever `gap_flags[i] == True`.

`RECURSIVE_STATE_CROSSES_GAP = NO`

No recursive indicator state (EMA, RMA/Wilder, alpha-EMA, DiNapoli K/D, MACD signal recursion) may carry across a segment boundary.

Rolling-window indicators (SMA, WMA, raw stochastic window) naturally respect segment boundaries via contiguous-window checks.

## GAP_RESTART_POLICY

At each segment start:

| Family | Restart behavior |
|--------|------------------|
| EMA (DMA) | Wait `period` bars; seed with SMA of first `period` segment closes; recurse |
| Standard MACD | Recompute fast/slow EMA independently per segment (SMA seed); signal EMA seeded from valid MACD |
| DiNapoli MACD | Restart alpha recursion; `POST_GAP_INIT_CONVENTION=segment_restart_alpha_seed_close0_signal_seed_macd0` |
| DiNapoli Stochastic | Discard prior K/D; wait for FastK window; SMA-seed K then D; recurse |
| ATR/RMA | First post-gap TR = HIGH − LOW only (no stale prior close); seed Wilder RMA after `period` TR values |

Derived features (slopes, crosses, slope-turn) require every source observation to be valid **and** in the same contiguous segment as the current bar.

Display-aligned features apply the same validity rule at `source_index = t − shift`.

---

## STANDARD STOCHASTIC

Parameters: `K_PERIOD`, `K_SMOOTH`, `D_PERIOD` (default 14/3/3).

```
FastK[t] = 100 * (Close[t] - LL_n) / (HH_n - LL_n)
           where LL_n = min(Low[t-n+1:t]), HH_n = max(High[t-n+1:t])
           HH == LL → 50

K[t] = SMA(FastK, K_SMOOTH)
D[t] = SMA(K, D_PERIOD)
```

Initialization: SMA rolling windows; first valid K after `K_PERIOD + K_SMOOTH - 2`; first valid D after warmup chain completes.

Threshold features (80/20) are project-generic, not part of the canonical formula.

---

## DINAPOLI PREFERRED STOCHASTIC

Reference authority: **8 / 3 / 3 modified-moving-average smoothing**, K/D state and crosses.

```
FastK first index     = K_PERIOD - 1          → 7 for 8/3/3
K seed index          = fastk_first + SLOWING - 1  → 9
D seed index          = k_seed_index + D_PERIOD - 1 → 11
First full feature    = d_seed_index + 1      → 12

K[k_seed] = mean(FastK[fastk_first : k_seed+1])
K[t]      = K[t-1] + (FastK[t] - K[t-1]) / SLOWING   for t > k_seed

D[d_seed] = mean(K[k_seed : d_seed+1])
D[t]      = D[t-1] + (K[t] - D[t-1]) / D_PERIOD     for t > d_seed
```

Cross/slope features require previous fully valid K and D in the same segment.

Threshold features (80/20): `THRESHOLD_PROFILE=PROJECT_GENERIC_80_20` — not part of the DiNapoli reference formula.

---

## STANDARD MACD

Parameters: fast EMA period, slow EMA period, signal EMA period (default 12/26/9).

```
MACD[t]   = EMA_fast(Close)[t] - EMA_slow(Close)[t]
SIGNAL[t] = EMA_signal(MACD)[t]
HIST[t]   = MACD[t] - SIGNAL[t]
```

EMA initialization: SMA seed of first `period` closes within the current contiguous segment, then standard recursive EMA.

Each segment recomputes fast, slow, and signal EMA independently.

---

## DINAPOLI MACD REFERENCE

Alpha coefficients (not integer periods):

```
FAST_ALPHA   = 0.213   (equiv ~8.39)
SLOW_ALPHA   = 0.108   (equiv ~17.52)
SIGNAL_ALPHA = 0.199   (equiv ~9.05)
```

Per contiguous segment:

```
fast[s]   = Close[s]
slow[s]   = Close[s]
signal[s] = fast[s] - slow[s]

fast[t]   = FAST_ALPHA * Close[t] + (1-FAST_ALPHA) * fast[t-1]
slow[t]   = SLOW_ALPHA * Close[t] + (1-SLOW_ALPHA) * slow[t-1]
macd[t]   = fast[t] - slow[t]
signal[t] = SIGNAL_ALPHA * macd[t] + (1-SIGNAL_ALPHA) * signal[t-1]
hist[t]   = macd[t] - signal[t]
```

`POST_GAP_INIT_CONVENTION=segment_restart_alpha_seed_close0_signal_seed_macd0`

`STABILIZATION_POLICY=restart_recursive_state_at_each_segment_start_no_vendor_exact_claim`

Do not claim exchange/vendor exact state across missing data.

---

## DMA (SMA / EMA / WMA)

```
SMA[t] = mean(Close[t-n+1:t])
WMA[t] = weighted mean with weights 1..n on Close window
EMA[t] = alpha * Close[t] + (1-alpha) * EMA[t-1]
         alpha = 2/(n+1)
         seed  = SMA(first n closes in segment)
```

EMA is recursive and restarts per contiguous segment.

---

## ATR (Wilder RMA)

```
TR[t] = max(H-L, |H-C[t-1]|, |L-C[t-1]|)   (within segment)
TR[segment_start] = HIGH - LOW              (no stale prior close)

ATR[t] = Wilder RMA(TR, period)
         seed = mean(TR[segment_start : segment_start+period-1])
         then RMA recursion
```
