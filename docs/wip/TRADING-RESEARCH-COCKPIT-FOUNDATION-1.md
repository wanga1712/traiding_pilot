# WIP: TRADING-RESEARCH-COCKPIT-FOUNDATION-1

## Status

`REVIEW`

## Goal

Extend the trading UI at `:8055` with a compact **Historical Run Result** panel directly below the chart. Primary question: if a strategy started with $100, what balance did it finish with?

## Scope delivered

- `TRADING_RUN_RESULT_V1` schema + validation
- Null-vs-zero semantics (unknown ≠ zero)
- Economic reconciliation validator (`PASS` | `FAIL` | `NOT_AVAILABLE`)
- `TradingRunRepository` + `FileTradingRunRepository`
- REST API under `/api/trading-runs/...`
- Dash panel: run selector, 6 summary cards, equity curve, cost breakdown, detail tabs
- STRUCTURAL_ONLY protection for WHEN research (no synthetic monetary fields)
- Test fixtures (7 types) + 14 automated tests

## Not in scope (later WIPs)

Futures simulator, fees/funding/spread/slippage/liquidation engines, Bybit downloader, Qwen trading.

## Production data

Default manifest exposes one STRUCTURAL_ONLY research run: `ORIGINAL_DMA_STOCH_STRUCTURAL_V1` (precision/recall metrics only).

Monetary fixtures require `TRADING_RUN_INCLUDE_FIXTURES=1` (test/dev only).

## Artifacts

`artifacts/TRADING-RESEARCH-COCKPIT-FOUNDATION-1/`

## Tests

`phase3_staging/test_trading_run_v1.py` — 14 passed

## RETURN

```
WIP=TRADING-RESEARCH-COCKPIT-FOUNDATION-1
ROADMAP_STATUS=REVIEW
READY_FOR_USER_REVIEW=YES
```

## Next WIP (do not auto-activate)

`BYBIT-FUTURES-DATA-FOUNDATION-AND-LIVE-RECORDER-1`
