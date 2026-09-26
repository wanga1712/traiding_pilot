# Current research state V2

The completed composite WIP is closed at commit `a5816ad7a42c131fe8e38d95e96cdecafe5eddb1`.
The dataset WIP is CLOSED at `201efd1e1b98056d526baced8042a51887c0218e`.
The probability-model bakeoff is CLOSED at accepted authority
`860c4683bd93593e204656a903c29776b0e75225`. It selected only the frozen
CatBoost/FS_FULL RAW candidates for the 30m and 60m horizons.

`INDEPENDENT-OOS-MODEL-EVALUATION-1` is CLOSED. Its one-shot independent OOS
exam covered 109224 canonical 15m decisions from
`2023-06-20T06:14:59.999999Z` through `2026-07-31T23:59:59.999999Z`. The
frozen 30m and 60m CatBoost/FS_FULL RAW models both classified
`OOS_SUPPORTED`: each improved full-period log loss and Brier score against
its frozen DEVELOPMENT prior, and each improved log loss in all three frozen
chronological blocks. The improvements are small probability-quality results,
not evidence of trading profitability.

All model, feature, time-causality, and target-leakage integrity gates pass.
There was no retraining, calibration, model selection, OOS tuning, execution
simulation, or PnL. The OOS exam is not compromised. Full runtime artifacts
remain on S13; small and medium evidence is committed with the WIP report.

Both horizons proceed separately to
`PROVISIONAL-FUTURES-EXECUTION-SIMULATOR-1`, which is ACTIVE. Entry thresholds
are frozen from DEVELOPMENT OOF probability distributions at Q10/Q90. The
simulator uses one position at a time, 1x leverage, 100% of current equity,
fixed 30m/60m holding periods, 0.00055 taker fee per side, and 0.00010
slippage per side. Starting equity is 100 USDT with no recapitalization; an
equity value at or below zero permanently stops new entries. OOS predictions,
models, features, thresholds, costs, holding periods, and position rules are
immutable in this WIP.
