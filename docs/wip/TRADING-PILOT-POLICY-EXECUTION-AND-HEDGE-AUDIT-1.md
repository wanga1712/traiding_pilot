# WIP=TRADING-PILOT-POLICY-EXECUTION-AND-HEDGE-AUDIT-1

STATUS=REVIEW
STARTED_AT=2026-11-12
BASE_COMMIT=218390d02019e71bda21122aef56b599d2429ff0
GIT_COMMIT=PENDING
MODE=AUDIT -> REPAIR -> TEST -> HISTORICAL REGRESSION
LIVE_TRADING=NO
MODEL_RETRAINING=NO
QWEN_FINE_TUNING=NO
OOS_OPENED=NO

## Result

The zero HEDGE fills in the saved event-driven run were not caused by an
order-execution failure. In that run CatBoost never selected `OPEN_HEDGE` as
its raw argmax and Qwen never proposed `OPEN_HEDGE`. The previous per-portfolio
`HEDGE_OPEN_EVENT` values of 123, 148, 4, and 5 were false positives caused by
searching serialized management probabilities for the string `OPEN_HEDGE`.
The aggregate later reported 0 actual hedges, so counter semantics were
inconsistent.

Qwen's 11 baseline `CLOSE_HEDGE` proposals were invalid because the old adapter
advertised every action class in every state. They were rejected downstream
with `QWEN_ACTION_INAPPLICABLE_TO_STATE`. State-specific action permissions are
now enforced inside the adapter before policy application.

After fixing timing, risk, state transfer, and execution pricing, the complete
CatBoost-only DEVELOPMENT regression produced 52 real HEDGE fills in RUN1 and
52 closes:

| Allocation | HEDGE signal | Proposed | Approved | Filled | Closed |
|---|---:|---:|---:|---:|---:|
| RUN1 60/40 | 23 | 23 | 23 | 23 | 23 |
| RUN1 40/60 | 29 | 29 | 29 | 29 | 29 |
| RUN2 60/40 | 0 | 0 | 0 | 0 | 0 |
| RUN2 40/60 | 0 | 0 | 0 | 0 | 0 |

RUN2 therefore still has no hedge for a different, quantified reason: there
was no model signal or policy proposal. No order reached margin validation.

## Confirmed defects and repairs

| ID | Defect | Root cause | Evidence | Fix | Regression test |
|---|---|---|---|---|---|
| PEH-001 | Decisions used future information | Features came from `decision_at`, but the same row's earlier `open_time` was both decision and execution time | Baseline `decision_to_execution_seconds` was 0 for all 24,415 decisions | Split `decision_at` from next-bar `execution_time`; pending orders fill at the next available `open` | `test_decision_executes_only_at_next_available_bar_open` |
| PEH-002 | HEDGE and averaging bypassed pre-trade risk sizing | `PolicyAccount.execute()` used free margin directly | `maximum_margin_for_limit` was absent from hedge/average execution | Route PRIMARY, HEDGE, and AVERAGE through independent risk sizing; record pass/rejection reasons | synthetic LONG/SHORT, margin, averaging and limit tests |
| PEH-003 | Drawdown risk was effectively zero | `record_equity()` advanced the peak before drawdown was computed | Old RUN1 reported 0 risk events despite losing positions | Compute drawdown before updating the peak; emergency exit is queued for the next available open | risk-event and causality tests |
| PEH-004 | Qwen received an all-actions contract and incomplete state | Adapter validation used the global action enum; `position_state` collapsed every position to `PRIMARY_OPEN` | 11 invalid `CLOSE_HEDGE` proposals; `HEDGED` could not be represented | Pass and enforce `allowed_actions`; send exact `PRIMARY_OPEN`, `HEDGED`, or `HEDGE_ONLY`, position details, ATR, margin, PnL, and liquidation distance | `test_qwen_action_outside_current_state_falls_back_safely`, `test_qwen_receives_atr_and_state_specific_action_contract` |
| PEH-005 | Execution prices mixed spot and futures sources | Event frame retained spot `open` while only highs/lows were replaced with mark values | Minute parquet contains `futures_open` and mark OHLC | Fill at hourly first `futures_open`; mark state/liquidation at `mark_close` and mark extrema | `test_minute_aggregation_uses_futures_open_and_mark_extrema` |
| PEH-006 | HEDGE counters mixed signals, probability keys, and fills | The metric searched serialized CatBoost JSON for `OPEN_HEDGE` | Per-run false values 123/148/4/5; aggregate actual fills 0 | Separate signal, proposal, approval, rejection, fill, and close counters; use argmax, never dictionary-key presence | historical counter audit |
| PEH-007 | Rejected/no-op decisions looked executed | `_open()` silently returned when PRIMARY existed | Baseline had 3,853 open decisions versus 2,260 completed RUN1 60/40 cycles | Return every order attempt with `executed`, state, reason, risk report, quantity, notional, and fee | order/action trace tests |
| PEH-008 | Emergency exits could use the close after observing the full interval | Emergency `EXIT` executed immediately at the decision close | Old event path called `execute()` inside the detection branch | Queue emergency exit for the next available bar open; liquidation remains checked independently on mark extrema | causality and risk-engine tests |
| PEH-009 | Full Qwen after-fix replay is operationally impractical | Corrected monitoring yields 3,470 unique Qwen-eligible timestamps | Dry-run events and 21-request GPU smoke | Reduced duplicated prompt payload from ~6.0 KB to ~2.9 KB; full replay remains blocked without a separate event-frequency WIP | partial GPU smoke only |

Classification: 9 confirmed defects, 8 fixed, 1 unresolved limitation.
Severity: 1 CRITICAL, 5 HIGH, 3 MEDIUM. No frozen models or research results
were changed.

## Turnover and fee audit

The saved before-fix run had 6,352 primary trade exits/reductions and only
one-hour median holding time. Most exits used `AI_EXIT`: 2,259 in RUN1 60/40,
2,924 in RUN1 40/60, 409 in RUN2 60/40, and 748 in RUN2 40/60.

The reported fees are exact turnover costs, not synthetic capital loss:

| Run | Trade turnover proxy USDT | Fees USDT | 5 bps check USDT |
|---|---:|---:|---:|
| RUN1 60/40 | 201,264.12 | 100.6321 | 100.6321 |
| RUN1 40/60 | 298,878.98 | 149.4395 | 149.4395 |
| RUN2 60/40 | 28,414.15 | 14.2071 | 14.2071 |
| RUN2 40/60 | 50,628.13 | 25.3141 | 25.3141 |
| Total | 579,185.38 | 289.5927 | 289.5927 |

Slippage follows the same identity at 2 bps. Fees exceeded the initial
100 USDT because the account repeatedly entered and exited positions while
nominal position size increased with equity; cumulative turnover, not starting
capital, determines fees.

No saved cycle exceeded two additions. Additions were 0/1/2 only, and the
`cycles_over_two_additions` count is zero.

## Complete after-fix CatBoost regression

| Run | Equity after fix | Max drawdown | Liquidations | Executed orders | Cycles |
|---|---:|---:|---:|---:|---:|
| RUN1 60/40 | 342.6877 | 43.96% | 1 | 3,537 | 1,740 |
| RUN1 40/60 | 228.6087 | 33.82% | 1 | 4,036 | 1,979 |
| RUN2 60/40 | 299.3366 | 60.18% | 1 | 615 | 307 |
| RUN2 40/60 | 199.7637 | 60.13% | 1 | 1,453 | 726 |

Aggregate: 9,641 executed orders, 9,533 PRIMARY orders, 104 HEDGE orders,
4 SPOT orders, 4,752 completed PRIMARY cycles, 495,574.6948 USDT notional
turnover, 247.7008 USDT fees, 99.0795 USDT slippage, and 4 liquidations.

Before-fix references remain immutable:

| Run | CATBOOST_ONLY / event before fix | Qwen event before fix |
|---|---:|---:|
| RUN1 60/40 | 342.3394 | 342.3394 |
| RUN1 40/60 | 228.3672 | 228.3672 |
| RUN2 60/40 | 299.8139 | 299.7707 |
| RUN2 40/60 | 200.0139 | 199.9955 |

The Qwen after-fix full PnL replay is `VALIDATION_BLOCKED_EVENT_VOLUME`.
Continuing without changing frozen thresholds would require about 12 hours of
serial local inference. The partial GPU smoke is evidence of contract validity
only, not a trading result.

## Tests

- Local: `39 passed` in `tests/gpu_ai_policy` plus `tests/capital_growth`.
- S13: `39 passed` in the same suites.
- Covers PRIMARY LONG/SHORT, HEDGE OPEN/CLOSE, HEDGE rejection, averaging limit,
  partial reduction, event deduplication, margin exhaustion, liquidation,
  fees/funding/slippage conservation, no synthetic capital, causal next-open
  execution, futures-open aggregation, and Qwen action/state permissions.
- CatBoost-only historical regression: PASS.
- Full Qwen after-fix PnL regression: UNVERIFIED due event volume.

## Artifacts

- Saved baseline audit:
  `/var/tmp/traiding_pilot_ui_workspace/gpu_ai_trading_policy_v1/event_driven_qwen_v1/execution_audit_v1.json`
- Final CatBoost-only regression:
  `/var/tmp/traiding_pilot_ui_workspace/gpu_ai_trading_policy_v1/policy_execution_hedge_audit_v1/catboost_event_dry_run_final_v1/`
- Partial Qwen GPU smoke:
  `/var/tmp/traiding_pilot_ui_workspace/gpu_ai_trading_policy_v1/policy_execution_hedge_audit_v1/qwen_event_driven_after_fix_v4_compact/`
- Every final regression run includes `action_trace.csv`, `order_trace.csv`,
  `market_events.csv`, `trades.csv`, `decisions.csv`, equity, and metrics.

## RETURN

```text
WIP=TRADING-PILOT-POLICY-EXECUTION-AND-HEDGE-AUDIT-1
STATUS=REVIEW
BASE_COMMIT=218390d
ROOT_CAUSES=NO_CATBOOST_OPEN_HEDGE_SIGNAL_IN_SAVED_RUN;NO_QWEN_OPEN_HEDGE_PROPOSAL;FALSE_PROBABILITY_KEY_COUNTER;INVALID_ALL_ACTION_QWEN_CONTRACT;HEDGE_AVERAGE_RISK_BYPASS;DRAWDOWN_PEAK_ORDER;DECISION_EXECUTION_LOOKAHEAD;SPOT_FUTURES_PRICE_MIX
DEFECTS_CONFIRMED=9
DEFECTS_FIXED=8
HEDGE_SIGNAL_COUNT=BEFORE_FIX_0;AFTER_FIX_52
HEDGE_PROPOSED_COUNT=52
HEDGE_APPROVED_COUNT=52
HEDGE_REJECTED_COUNT=0
HEDGE_FILLED_COUNT=52
HEDGE_CLOSED_COUNT=52
HEDGE_REJECTION_REASONS=NONE;RUN2_HAD_ZERO_SIGNALS_AND_ZERO_PROPOSALS
SYNTHETIC_HEDGE_TESTS=PASS
PRIMARY_TRADES=9533
HEDGE_TRADES=104
TOTAL_EXECUTED_ORDERS=9641
COMPLETED_TRADE_CYCLES=4752
TOTAL_NOTIONAL_TURNOVER=495574.6948
TOTAL_FEES=247.7008
TOTAL_SLIPPAGE=99.0795
AVERAGING_LIMIT_TEST=PASS
CAUSALITY_TESTS=PASS
ACCOUNTING_TESTS=PASS
CATBOOST_ONLY_EQUITY=RUN1_60=342.6877;RUN1_40=228.6087;RUN2_60=299.3366;RUN2_40=199.7637
QWEN_BEFORE_FIX_EQUITY=RUN1_60=342.3394;RUN1_40=228.3672;RUN2_60=299.7707;RUN2_40=199.9955
QWEN_AFTER_FIX_EQUITY=VALIDATION_BLOCKED_EVENT_VOLUME
MAX_DRAWDOWN=0.601827
LIQUIDATIONS=4
OOS_OPENED=NO
MODEL_RETRAINING=NO
LIVE_TRADING=NO
NEXT_WIP=none
```
