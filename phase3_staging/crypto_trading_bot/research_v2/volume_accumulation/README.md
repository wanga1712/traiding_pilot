# VOLUME_ACCUMULATION_ENGINE_V1

Causal market-context features for later WHEN research.

## Neutral terminology

Use: BALANCE, COMPRESSION, RANGE, VOLUME_CONCENTRATION, PRICE_ACCEPTANCE, REJECTION, EXPANSION, EXHAUSTION.

Do **not** treat ACCUMULATION / DISTRIBUTION as ground truth from chart appearance.

## Causal access

```python
from crypto_trading_bot.research_v2.volume_accumulation import compute_market_context
```

Uses `get_event_history` / closed-candle filtering. Never uses `true_pivot_*`, `next_pivot`, or `R`.

## Engines frozen as inputs

- `WAVE_DATASET_V1`
- `REVERSAL_EVENT_DATASET_V1`
- `INDICATOR_ENGINE_V1` (reuse ATR/basic helpers; do not change semantics)

## Warmup / gaps

Insufficient history → `valid=False`, `invalid_reason=INVALID_WARMUP`.  
Gap crossing where continuity required → `insufficient_contiguous_history`.  
No fabricated zeros / forward-fill.

## Streaming

Stateful compression/duration features: `BATCH_RESULT == STREAMING_RESULT` (prefix recompute).

## Not in this WIP

WHEN tournament, ML, OI/funding/orderflow, PnL.
