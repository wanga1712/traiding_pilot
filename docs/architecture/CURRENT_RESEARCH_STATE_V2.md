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

Both horizons proceeded separately to
`PROVISIONAL-FUTURES-EXECUTION-SIMULATOR-1`, which is `CLOSED_NEGATIVE`. Entry thresholds
are frozen from DEVELOPMENT OOF probability distributions at Q10/Q90. The
simulator uses one position at a time, 1x leverage, 100% of current equity,
fixed 30m/60m holding periods, 0.00055 taker fee per side, and 0.00010
slippage per side. Starting equity is 100 USDT with no recapitalization; an
equity value at or below zero permanently stops new entries. OOS predictions,
models, features, thresholds, costs, holding periods, and position rules are
immutable in this WIP.

The full frozen simulation classified both horizons `EXECUTION_WEAK`. Before
costs, 30m returned +124.3455% and 60m returned +21.0514%. Under the primary
13 bps provisional round-trip cost assumption, net returns were approximately
-100% for both horizons, and every frozen chronological block was net
negative. The formal `equity <= 0` ruin condition was not reached, but ending
equity was only 0.0000007048 USDT for 30m and 0.0000481767 USDT for 60m.
There was no recapitalization, retraining, threshold optimization, leverage
search, or alteration of the frozen OOS predictions. The correct conclusion is
`MODEL_EDGE_EXISTS=YES` and `CURRENT_EXECUTION_POLICY_NOT_SUPPORTED`: Q10/Q90
entries with fixed 30m/60m holds are not tradable at 13 bps.

`PROBABILITY-TRADING-POLICY-RESEARCH-1` is now in REVIEW. It used only frozen
DEVELOPMENT OOF predictions from the 30m and 60m CatBoost/FS_FULL RAW models.
The exact 1728-candidate search space, stage rules, costs, and execution rules
were frozen before results. The previously examined 2023-2026 OOS is locked:
policy search, validation, result reading, and reexecution counts must remain
zero. Earliest, middle, and latest OOF evaluation folds are discovery,
validation, and one-shot confirmation respectively.

The result is `NO_VALIDATED_POLICY`. Of 1728 frozen discovery candidates, 100
met every discovery gate and the ranking retained 20. None of the 20 met the
validation gates at 13 bps. The strongest validation result still lost
7.0611% net, had -11.7031 bps arithmetic net expectancy, profit factor 0.6449,
and break-even friction only 0.9930 bps. No policy was selected; confirmation
was untouched and its run count remains zero. The proposed next WIP is
`FUTURES-PREDICTIVE-FEATURE-MODEL-V2-1`, but it has not been started.
