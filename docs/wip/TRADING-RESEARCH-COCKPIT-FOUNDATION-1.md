# WIP: TRADING-RESEARCH-COCKPIT-FOUNDATION-1

## Status

`CLOSED` — deployed to S13, runtime visual acceptance PASS (2026-08-31).

## Deploy

- URL: `http://10.8.0.13:8055/`
- Commit: `fd4524ce0cb13f43574f8f50bbad6d257a9ed68b`
- Production manifest: `ORIGINAL_DMA_STOCH_STRUCTURAL_V1` only (STRUCTURAL_ONLY)
- Fixtures: `TRADING_RUN_INCLUDE_FIXTURES=1` test-only; disabled in production

## Runtime acceptance

- Chart + ZigZag controls: PASS
- Historical run panel below chart: PASS
- STRUCTURAL_ONLY monetary suppression: PASS
- Empty state readable: PASS
- Fixture API smoke (completed/running/recon-fail/zero-liq/unknown-liq): PASS

## Screenshots

`artifacts/TRADING-RESEARCH-COCKPIT-FOUNDATION-1/screenshots/`

## GIT_COMMIT

fd4524ce0cb13f43574f8f50bbad6d257a9ed68b

## NEXT_WIP (do not auto-activate)

PROVISIONAL-FUTURES-EXECUTION-SIMULATOR-1
