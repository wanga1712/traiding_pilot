# Test matrix v1 — TRADING-RESEARCH-COCKPIT-FOUNDATION-1

| Gate | Test | Status |
|---|---|---|
| Schema validation PASS | `test_schema_validation_pass_completed_fixture` | PASS |
| Null-vs-zero semantics | `test_null_vs_zero_semantics` | PASS |
| Economic reconciliation PASS | `test_economic_reconciliation_pass` | PASS |
| Reconciliation failure detection | `test_reconciliation_failure_detection` | PASS |
| Run-status handling (RUNNING) | `test_run_status_running_not_final` | PASS |
| STRUCTURAL_ONLY monetary suppression | `test_structural_only_monetary_suppression` | PASS |
| Equity series rendering | `test_equity_series_rendering` | PASS |
| Empty-state rendering | `test_empty_state_rendering` | PASS |
| Trades null-field tolerance | `test_trades_null_field_tolerance` | PASS |
| Liquidation unavailable vs zero | `test_liquidation_unavailable_vs_zero` | PASS |
| Existing chart regression | `test_existing_chart_layout_regression` | PASS |
| API tests | `test_api_endpoints`, `test_repository_list_and_api_shape` | PASS |

Fixtures (test-only, `TRADING_RUN_INCLUDE_FIXTURES=1`):

1. `FIXTURE_COMPLETED_REALISTIC_V1`
2. `FIXTURE_RUNNING_V1`
3. `FIXTURE_STRUCTURAL_ORIGINAL_DMA_STOCH_V1`
4. `FIXTURE_FAILED_V1`
5. `FIXTURE_RECON_FAIL_V1`
6. `FIXTURE_ZERO_LIQ_V1`
7. `FIXTURE_UNKNOWN_LIQ_V1`

Run: `cd phase3_staging && PYTHONPATH=. pytest test_trading_run_v1.py --noconftest -q`
