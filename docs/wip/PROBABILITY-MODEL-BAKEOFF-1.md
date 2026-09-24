# PROBABILITY-MODEL-BAKEOFF-1

Status: ACTIVE

Parent dataset authority: `201efd1e1b98056d526baced8042a51887c0218e`.

This WIP compares prior baseline, Logistic L2, LightGBM, and CatBoost using only
the frozen DEVELOPMENT V2 dataset. Validation is chronological: F1→F2,
F1+F2→F3, and F1+F2+F3→F4. Seven frozen direction targets and four frozen
feature sets are evaluated with fixed configurations. No model may access OOS,
and no PnL or execution simulation is in scope.

`DEVELOPMENT_REUSE_BIAS=YES` and
`DEVELOPMENT_MODEL_METRICS_INDEPENDENT_OOS=NO` are permanent qualifications.
