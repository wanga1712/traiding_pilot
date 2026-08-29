# INDICATOR_ENGINE_V1

Deterministic **causal** indicator library for reversal / WHEN research.

## Core rule

Every value answers: **what was knowable at time T?**

| Field | Meaning |
|---|---|
| `CALCULATED_AT` | Close time of the last source bar used in the formula |
| `AVAILABLE_AT` | Earliest causal use time (closed-candle: equals `CALCULATED_AT`) |
| `DISPLAYED_AT` | Optional chart display coordinate (may shift forward) |

**`DISPLAYED_AT` is never information availability.**

Example: DMA 3x3 SMA uses bars through `T`. That value is available at `T` close.
It may be **drawn** at `T+3`, but calculation must not use bars from `T+3`.

## Source authority

Causal history only:

```python
from crypto_trading_bot.research_v2.reversal_events.anti_leakage import get_event_history
from crypto_trading_bot.research_v2.indicator_engine import compute_from_event_history
```

Do **not** feed complete future-containing event windows into causal calculation.

## Versions / registries

- Engine: `INDICATOR_ENGINE_V1`
- Parameter sets: `indicator_parameter_registry_v1.json` (`DMA_3X3_V1`, `MACD_12_26_9_V1`, …)
- Displaced Stoch/MACD presets are marked `PROJECT_EXPERIMENTAL` unless an exact historical authority is documented.

## No BUY/SELL in V1

Only observable primitives (`PRICE_CROSS_UP_DMA`, `K_CROSS_UP_D`, …).

Tournament vs true pivots C belongs to `REVERSAL-SIGNAL-EVENT-STUDY-1`.

## Warmup / gaps

Before sufficient contiguous history: `valid=False`, `value=None`, reason `warmup` or `insufficient_contiguous_history`.
No silent zeros / forward-fill / future fill.
