# API contract v1 — Trading run results

Base path: `/api/trading-runs`

Repository: `TradingRunRepository` (UI must not read artifact files directly).

## Endpoints

| Method | Path | Response |
|---|---|---|
| GET | `/api/trading-runs` | `{ "runs": [ index rows ] }` |
| GET | `/api/trading-runs/{run_id}` | Full `TRADING_RUN_RESULT_V1` + `reconciliation` |
| GET | `/api/trading-runs/{run_id}/summary` | Header + capital + performance subset + `reconciliation` |
| GET | `/api/trading-runs/{run_id}/equity` | `{ "equity_curve": [...] }` or `{ "equity_curve": null, "status": "NOT_AVAILABLE" }` |
| GET | `/api/trading-runs/{run_id}/trades` | `{ "trades": [...] }` |
| GET | `/api/trading-runs/{run_id}/liquidations` | `{ "liquidations": [...] }` |
| GET | `/api/trading-runs/{run_id}/parameters` | `{ "parameters": {...} }` |

## Index row fields

- `run_id`
- `run_status`
- `created_at`
- `strategy_id`
- `strategy_name`
- `strategy_version`
- `execution_realism_level`

## Null semantics

Missing economics are JSON `null`, never silently coerced to `0` in API responses.

## STRUCTURAL_ONLY

Runs with `execution.execution_realism_level=STRUCTURAL_ONLY` must not expose monetary capital/cost fields. They may include `research_metrics` instead.

## Future writers

`FUTURES-EXECUTION-SIMULATOR-1` writes versioned JSON under `trading_runs_store/` and registers `run_id` in `manifest.json`.
