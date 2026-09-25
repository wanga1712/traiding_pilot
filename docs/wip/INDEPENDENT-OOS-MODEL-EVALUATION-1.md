# INDEPENDENT-OOS-MODEL-EVALUATION-1

Status: **ACTIVE**

Parent model authority: `860c4683bd93593e204656a903c29776b0e75225`

Parent dataset authority: `201efd1e1b98056d526baced8042a51887c0218e`

This WIP performs the first and only independent OOS evaluation of the frozen
30m and 60m CatBoost/FS_FULL RAW probability models. OOS boundaries,
methodology, feature schema, target semantics, frozen DEVELOPMENT priors,
temporal blocks, bootstrap, and classification gates are fixed before any OOS
payload read. No model fitting, calibration, feature research, threshold
selection, execution simulation, or PnL is allowed.

The WIP remains ACTIVE until the one-shot evaluation and integrity audit are
complete. The next WIP is not active.
