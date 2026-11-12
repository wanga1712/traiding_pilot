# Qwen Policy Comparison

STATUS=PASS

## Comparison protocol

- Same dataset, CatBoost models, execution, fees, funding, slippage, and risk
  engine for both controls.
- Qwen acts only as a validator over causal features, CatBoost probabilities,
  portfolio state, and risk state.
- One scheduled Qwen validation every 336 hours, maximum 26 per portfolio.
- Both 60/40 and 40/60 allocations are tested.
- RUN 1 and RUN 2 remain DEVELOPMENT-only; RUN 2 is not independent OOS.

## Results

| Run | Allocation | CATBOOST_ONLY | CATBOOST_PLUS_QWEN | Qwen added |
|---|---|---:|---:|---:|
| RUN 1 | 60/40 | 342.3452 | 342.3452 | 0.0000 |
| RUN 1 | 40/60 | 228.4057 | 228.4057 | 0.0000 |
| RUN 2 | 60/40 | 299.8139 | 299.8139 | 0.0000 |
| RUN 2 | 40/60 | 200.0139 | 200.0139 | 0.0000 |

`QWEN_ADDED_VALUE=0`.

## Decisions

- Adapter JSON-contract valid: 103/104 requests.
- Policy-accepted Qwen decisions: 94/104.
- Fallbacks: 10, comprising one malformed/truncated JSON response and nine
  low-confidence decisions.
- Qwen action changes versus CatBoost: 0.
- Qwen actions: 86 `OPEN_SHORT`, 17 `OPEN_LONG`, 1 `HOLD`; no action changed
  the frozen CatBoost proposal.
- Actual inference requests: 104.
- Replayed identical request hashes: 26, served from local JSONL cache without
  model inference.
- Median inference latency: 10.49 seconds; P90 40.03 seconds; max 71.69
  seconds.
- Final combined GPU-policy and capital-growth tests: 27 PASS locally and 27
  PASS on S13.

## Conclusion

Qwen is operationally usable but adds no measurable value in this frozen
comparison. It reproduced or vetoed CatBoost proposals but never changed an
executed action. This negative result is preserved without retuning the prompt,
threshold, intervals, or action mapping after observing RUN 2.

All request/response records and model identity are committed. Full policy
outputs remain at:

```text
S13:/var/tmp/traiding_pilot_ui_workspace/gpu_ai_trading_policy_v1/gate6_qwen_v2/
```
