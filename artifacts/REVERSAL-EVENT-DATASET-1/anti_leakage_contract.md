# Anti-leakage contract — REVERSAL_EVENT_DATASET_V1

## Separation of truth

- **TRUE_PIVOT** (`true_pivot_time`, `true_pivot_price`, `pivot_type`) is a **retrospective label**.
- **DETECTABLE_REVERSAL** is produced only by future signal WIPs using causal history.

Algorithms must never be given TRUE_PIVOT before it is causally observable.

## Event windows vs feature availability

Event bar tables may contain rows **after** C so that signal delay and outcomes can be evaluated.

**Presence of future rows does not grant access.**

Causal research MUST use:

```text
get_event_history(event_id, timeframe, decision_time)
```

which returns only bars with:

```text
close_time <= decision_time   # closed-candle default
```

## Higher-timeframe unfinished bars

At decision time `T`, a higher-TF candle that has `open_time <= T < close_time` is **not finished**.

Closed-candle features must **not** treat that candle as available.

Partial-bar features, if ever added, must be a separate explicit feature family.

## Displacement

For every future indicator/predictor value distinguish:

| Field | Meaning |
|---|---|
| `CALCULATED_AT` | When the formula was evaluated |
| `AVAILABLE_AT` | Earliest causal use time |
| `DISPLAYED_AT` | Optional chart display time (may be shifted) |

**`DISPLAYED_AT` is never information availability.**

Example: a DMA visually plotted at `T+3` does **not** mean information from `T+3` was available at `T`.

## Column classes

See `event_schema_registry_v1.csv`:

- `CAUSAL_RAW_INPUT`
- `RETROSPECTIVE_LABEL`
- `OUTCOME`
- `IDENTITY`
- `DIAGNOSTIC`

Never feed `RETROSPECTIVE_LABEL` / `OUTCOME` / alignment diagnostics (`bars_from_true_pivot`, `price_relative_to_C_*`) into deployable models by default.

## Feature interface

```text
compute_feature(history_available_at_t) ->
  value, calculated_at, available_at, displayed_at?, source_timeframe, feature_version
```

No feature implementation may read the full event window directly.
