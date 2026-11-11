# GATE 4/5 - Frozen Policy and Historical Comparison

STATUS=PASS

POLICY_SHA256=
`d296c8107bef0c68fe06b92532026e485b08b194e10ec89a5f3e1b6ab179434c`

RUN 1 covers 2020. RUN 2 covers 2021 and is chronological DEVELOPMENT
validation, not independent OOS. Both use identical fees, funding, slippage,
mark-price liquidation, margin, and order constraints.

## Best comparison, 60/40 with spot HOLD

| Strategy | RUN 1 | RUN 2 |
|---|---:|---:|
| BUY_HOLD | 381.86 | 339.31 |
| SMA_BASELINE | 342.35 | 299.81 |
| INDICATORS_ONLY | 342.31 | 299.75 |
| AI_NO_HEDGE | 342.30 | 299.81 |
| AI_HEDGE | 342.36 | 299.81 |
| AI_HEDGE_AVG | 342.35 | 299.81 |

## Added-value conclusions

- AI versus indicators-only: mixed from `-0.005` to `+0.466` USDT across
  allocation/mode pairs in RUN 1 and `+0.068` to `+0.125` in HOLD RUN 2.
  This is not material added value.
- Hedging versus AI without hedge: at most `+0.055` USDT in RUN 1 and zero in
  RUN 2. Hedging is not economically supported.
- Averaging versus AI hedge: mixed from `-54.50` to `+0.023` USDT in RUN 1 and
  zero in RUN 2. Averaging is not supported.
- Every AI variant lost to the matching Buy & Hold baseline.
- AI SWING was materially worse than AI HOLD and lost 39.5%-59.5% in RUN 2.

## Risk and costs

- Best RUN 1 AI drawdown: 38.06%.
- Best RUN 2 AI drawdown: 60.06%.
- Best AI representative had one liquidation in each run.
- RUN 1 AI fee cost was substantially higher than SMA/indicators-only because
  the management model produced frequent actions.

## Evidence

- `backtest_summary_v1.json`
- `portfolio_metrics_v1.csv`
- `impact_summary_v1.json`
- `policy_manifest_v1.json`
- Equity charts for A/B and HOLD/SWING in both runs.
- Representative AI_HEDGE_AVG 60/HOLD equity, trades, and decisions.
- `gate4_backtest.log`, `gate4_analytics.log`, and
  `gate5_tests_s13.log`.

The full runtime directory remains at
`S13:/var/tmp/traiding_pilot_ui_workspace/gpu_ai_trading_policy_v1/`.
