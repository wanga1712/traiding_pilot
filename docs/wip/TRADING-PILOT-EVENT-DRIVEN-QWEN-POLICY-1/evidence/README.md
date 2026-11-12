# Event-Driven Qwen Policy Evidence

STATUS=PASS

## Event flow

- Triggered market/position/risk events: 4,123.
- Suppressed by hysteresis/dedup/cooldown: 3,871.
- Qwen-eligible events: 329.
- Actual Qwen calls after same-timestamp grouping/cache: 275.
- Qwen action changes: 6.
- Fallbacks: 22.
- Actual hedge opens: 0.
- Hedge-close events: 0.
- Risk events: 6.

All six Qwen action changes were `SKIP -> REDUCE_POSITION` in RUN 2: five
under the 40/60 allocation and one under 60/40. No hedge was open in this
event-driven run, so `CLOSE_HEDGE` proposals were invalid and safely rejected.

## Comparison

| Run | Allocation | CatBoost only | Qwen 336h | Qwen event-driven | Event added |
|---|---|---:|---:|---:|---:|
| RUN 1 | 60/40 | 342.3394 | 342.3452 | 342.3394 | 0.0000 |
| RUN 1 | 40/60 | 228.3672 | 228.4057 | 228.3672 | 0.0000 |
| RUN 2 | 60/40 | 299.8139 | 299.8139 | 299.7707 | -0.0432 |
| RUN 2 | 40/60 | 200.0139 | 200.0139 | 199.9955 | -0.0184 |

Total event-driven Qwen added value: `-0.0616 USDT`.
Total previous 336-hour Qwen added value: `+0.0443 USDT`.

Neither result is economically material. Event-driven Qwen changed real
actions, but the changes slightly reduced final equity. It also proposed
`REDUCE_POSITION`, an action with no training examples, which reinforces the
audit finding that the CatBoost management target is incomplete.

## Runtime

- Qwen model: `qwen2.5:7b`, digest
  `845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e`.
- Timeout: 30 seconds.
- Median latency: 12.84 seconds.
- P90 latency: 17.03 seconds.
- Liquidations across event portfolios: 6.
- Worst max drawdown: 60.07%.

## Files

- `event_run/event_policy_summary_v1.json`
- `event_run/policy_metrics_v1.csv`
- `event_run/qwen_event_requests_*.jsonl`
- `event_run/*_market_events.csv`
- `event_run/*_qwen_events.csv`
- `control/event_policy_summary_v1.json`
- `comparison/event_policy_comparison_v1.*`
- `comparison/*_comparison.png`

No OOS, live trading, model training, or Qwen fine-tuning occurred.
