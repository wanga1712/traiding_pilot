# Current research state V2

The completed composite WIP is closed at commit `a5816ad7a42c131fe8e38d95e96cdecafe5eddb1`.
The dataset WIP is CLOSED at `201efd1e1b98056d526baced8042a51887c0218e`.
The probability-model bakeoff is CLOSED at accepted authority
`860c4683bd93593e204656a903c29776b0e75225`. It selected only the frozen
CatBoost/FS_FULL RAW candidates for the 30m and 60m horizons.

The current WIP is `INDEPENDENT-OOS-MODEL-EVALUATION-1` in ACTIVE status. It
performs one fixed, one-shot independent OOS exam of those two candidates.
There is no retraining, calibration, model selection, execution simulation, or
PnL in this WIP. The OOS period, feature schema, targets, baselines, temporal
blocks, bootstrap, and classification rules must be frozen before payload
access. The next WIP must not start automatically.

Compute runs on S13. Source market data remains authoritative on S7; the S13
cache is disposable and must be lineage-checked before scoring. Frozen parent
dataset and model artifacts are read only.
