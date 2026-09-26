# PROBABILITY-TRADING-POLICY-RESEARCH-1

Status: **ACTIVE**

Mode: `DEVELOPMENT-OOF-LOW-TURNOVER-POLICY-1`

## Purpose

Determine whether the frozen 30m and 60m CatBoost/FS_FULL RAW probability
models can support a causal, low-turnover policy after 13 bps round-trip
friction. This is policy research on DEVELOPMENT OOF predictions. It performs
no model retraining, calibration, feature changes, old-OOS retesting, or live
trading.

## Authorities and locks

- Frozen model authority: `860c4683bd93593e204656a903c29776b0e75225`.
- DEVELOPMENT OOF artifact:
  `/var/tmp/traiding_pilot_ui_workspace/artifacts/PROBABILITY-MODEL-BAKEOFF-1/walkforward_predictions_v1.parquet`.
- OOF SHA256: `dc3c90f88513a5023299ae6b19d9b8cef102c65d0cfcc402a153cf44f698b862`.
- Full OOF artifact rows: `9782279`.
- Old OOS lock: `2023-06-20T06:14:59.999999Z` through
  `2026-07-31T23:59:59.999999Z`.
- Old-OOS policy search, validation, and reexecution counters are frozen at 0.

Only the selected 30m and 60m model/config rows are aligned by causal decision
row. The intersection contains 107647 decisions. The unchanged chronological
OOF folds map to discovery, validation, and confirmation.

## Frozen protocol

The exact candidate grid contains 1728 combinations:

- entry source: `30M_ONLY`, `60M_ONLY`, `BOTH_AGREE`;
- confidence quantile: `0.950`, `0.975`, `0.990`, `0.995`;
- entry persistence decisions: `1`, `2`;
- cooldown minutes: `0`, `60`, `240`;
- exit family: `NEUTRAL_CROSS`, `REVERSE_THRESHOLD`, `CONFIDENCE_LOSS`;
- minimum hold minutes: `15`, `30`;
- maximum hold safety cap minutes: `60`, `120`, `240`, `480`.

Quantile thresholds are derived on discovery only and carried unchanged to
later stages. Costs are 0.00055 taker fee and 0.00010 slippage per side. The
account starts at 100 USDT, uses 1x leverage and 100% of current equity, allows
one position, and forbids overlap, averaging, pyramiding, martingale, grids,
stops, take-profit grids, leverage search, and recapitalization.

Signals are evaluated at `DECISION_AT`. Entry and dynamic-exit fills use the
first canonical 1m open strictly after the decision. A safety-cap exit uses the
first canonical 1m open at or after the cap time. Any required missing bar
makes the action invalid; gaps are never bridged. To preserve the absolute OOS
lock, price data are read only through `2023-06-20T06:08:00Z`. A trade whose
required fill is outside that DEVELOPMENT price boundary is invalid/skipped.

Discovery runs all candidates, applies the frozen eligibility gates, and
retains exactly the top 20 by expectancy, profit factor, lower drawdown, then
trade count. Validation runs only those retained candidates with its frozen
gates and ranking. If none survive, the result is `NO_VALIDATED_POLICY` and
confirmation remains unread. If a winner exists, its full specification and
metrics must be committed before the one permitted confirmation run.

## Frozen split manifest

| Stage | Original fold | Start | End | Aligned rows |
|---|---|---|---|---:|
| POLICY_DISCOVERY | WFV_1 | 2020-05-21 01:44:59.999999+00:00 | 2021-05-31 02:59:59.999999+00:00 | 35772 |
| POLICY_VALIDATION | WFV_2 | 2021-05-31 03:14:59.999999+00:00 | 2022-06-10 04:29:59.999999+00:00 | 35949 |
| POLICY_CONFIRMATION | WFV_3 | 2022-06-10 04:44:59.999999+00:00 | 2023-06-20 04:59:59.999999+00:00 | 35926 |

Runtime artifact root:
`/var/tmp/traiding_pilot_ui_workspace/artifacts/PROBABILITY-TRADING-POLICY-RESEARCH-1/`.

Result: **PENDING**.
