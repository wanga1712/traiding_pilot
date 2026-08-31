# Economic reconciliation v1

## Identity (completed monetary runs)

```
FINAL_EQUITY
  ≈ START_EQUITY
    + GROSS_TRADING_PNL
    - TOTAL_TRADING_FEES
    + NET_FUNDING
    - SPREAD_COST
    - SLIPPAGE_COST
    - LIQUIDATION_COST
```

Unrealized PnL at test end must be reflected consistently in `final_equity` when the simulator provides it.

## Status values

| Status | Meaning |
|---|---|
| `PASS` | All required fields present; identity holds within tolerance |
| `FAIL` | Required fields present; identity violated |
| `NOT_AVAILABLE` | STRUCTURAL_ONLY, non-COMPLETED status, or incomplete economics |

## Tolerance

- Absolute: `0.02`
- Relative: `1e-6` of expected final equity

## UI rule

A completed execution run with populated economics and `FAIL` must not render as a valid monetary result (reconciliation line shown in red).

## Validator

`crypto_trading_bot.research_v2.trading_runs.reconciliation.reconcile_run`

Schema gate: `validate_run` rejects COMPLETED monetary runs with `FAIL`.
