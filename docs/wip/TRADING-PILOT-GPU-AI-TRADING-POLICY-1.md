# WIP=TRADING-PILOT-GPU-AI-TRADING-POLICY-1

STATUS=ACTIVE
PHASE=GATE_0_GPU_PREFLIGHT
STARTED_AT=2026-11-11
MODE=REPAIR -> DATASET -> GPU TRAINING -> BACKTEST
MODEL=NEW_TRAIN_FROM_SCRATCH
COMPUTE=S13_CUDA_REQUIRED
INITIAL_CAPITAL=100 USDT
ASSET=ETHUSDT
FUTURES=10X_ISOLATED_HEDGE_MODE
LIVE_TRADING=DISABLED
OOS_OPENED=NO

## Authorization

- `USER_AUTHORIZATION=YES`
- Training and isolated research changes on S13 are authorized.
- S7 remains read-only.
- Frozen models, frozen research results, OOS, and confirmation sets are
  immutable.
- The completed `TRADING-PILOT-CAPITAL-GROWTH-EXPERIMENT-1` remains
  `REVIEW`; its results are an immutable negative baseline.
- No real trading, deployment, service restart, or automatic follow-up WIP.

## Goal

Build a new causal ETHUSDT dataset from existing project indicators, train new
CatBoost entry and position-management models from scratch on CUDA, connect
them to a corrected historical simulator, and determine whether the learned
policy adds value over Buy & Hold, the prior SMA baseline, and indicators-only
controls after all modeled costs.

The prior SMA20/SMA50 strategy is not a substitute for the AI model.

## Stage gates

### GATE 0 - S13 and CUDA

- Verify S13 identity.
- Record GPU model, driver, VRAM, CUDA, Python, CatBoost, and PyTorch state.
- Execute a real small CatBoost training job with `task_type="GPU"`.
- Record GPU use and model-load evidence.

Stop with `GPU_BLOCKED` if CUDA training is not genuinely available. CPU
substitution requires separate user approval.

### GATE 1 - Simulator repair

- Add explicit Spot <-> Futures transfers during 60/40 and 40/60 rebalancing.
- Separate Spot, PRIMARY, HEDGE, free margin, used margin, realized and
  unrealized accounting.
- Include current Spot exposure in pre-trade and continuous risk checks.
- Enforce the 5% planned thesis-risk limit continuously, not only on entry.
- Validate mark-price liquidation, funding, fees, slippage, partial fills, and
  order-size limits.
- Prevent hedge-profit double counting and synthetic capital creation.
- Pass independent deterministic scenario tests before training the policy.

### GATE 2 - Dataset

- Build a new versioned DEVELOPMENT-only dataset with `available_at`.
- Use existing causal implementations where available: DMA, MACD,
  Stochastic, ADX/ATR/volatility, DiNapoli/DNO, confirmed ZigZag, inverse
  predictors, composite signals, volume/structure, and multi-timeframe
  features.
- Include portfolio state, margin, exposure, liquidation distance, holding
  time, costs, averaging count, and remaining risk.
- Build 24h, 72h, and 168h targets for direction, MFE/MAE, risk-limit hit,
  liquidation, recovery, recovery time, and counterfactual action outcomes.
- Use chronological splits with purge and embargo. Future data is allowed only
  for labels, never decision-time features.
- Produce feature manifest, dataset SHA256, coverage, exclusions, leakage
  checks, and reproducibility evidence.

### GATE 3 - GPU models

- Train a new ENTRY model from scratch on GPU.
- Train a new POSITION_MANAGEMENT model from scratch on GPU for `HOLD`,
  `OPEN_HEDGE`, `CLOSE_HEDGE`, `AVERAGE_PRIMARY`, `REDUCE`, and `EXIT`.
- Freeze model files, parameters, seeds, feature order, calibration, metrics,
  and GPU logs.
- Verify reproducible load and causal inference.
- Record a negative result without policy tuning if predictive baselines are
  not exceeded.

### GATE 4 - Policy

- Map model outputs to `OPEN_LONG`, `OPEN_SHORT`, `HOLD`, `OPEN_HEDGE`,
  `CLOSE_HEDGE`, `AVERAGE_PRIMARY`, `REDUCE_POSITION`, `EXIT`, and `SKIP`.
- Journal model probabilities, indicator state, risk forecast, expected
  after-cost PnL, margin, and rejection reasons.
- Enforce capital, leverage, liquidation, margin, hedging, and averaging
  constraints independently of the model.

### GATE 5 - Historical runs

- RUN 1: DEVELOPMENT walk-forward training and bounded policy selection.
- Freeze models, policy, risk rules, and SHA256.
- RUN 2: later chronological DEVELOPMENT validation without changes.
- Do not represent re-use of 2020-2021 as independent OOS.
- Return `VALIDATION_BLOCKED` if no sufficient allowed period exists.

## Comparisons

All new variants use identical data, execution, and cost assumptions:

- `BUY_HOLD`
- `SMA_BASELINE`
- `INDICATORS_ONLY`
- `AI_NO_HEDGE`
- `AI_HEDGE`
- `AI_HEDGE_AVG`

Both 60/40 and 40/60 capital allocations are required.

## Safety

- No live orders or API trading keys.
- No S7 mutation.
- S13 mutation only in an isolated experiment workspace.
- No OOS or confirmation access.
- No frozen model or result overwrite.
- No next WIP activated automatically.

## RETURN

```text
WIP=TRADING-PILOT-GPU-AI-TRADING-POLICY-1
STATUS=REVIEW
GPU_NAME=
CUDA_AVAILABLE=
GPU_TRAINING_CONFIRMED=
GPU_VRAM_USED=
SIMULATOR_ACCOUNTING=
DATASET_ROWS=
FEATURE_COUNT=
INDICATOR_FAMILIES_USED=
ENTRY_MODEL_TRAINED=
MANAGEMENT_MODEL_TRAINED=
MODEL_SHA256=
RUN1=
RUN2=
POLICY_SHA256=
BUY_HOLD_FINAL_EQUITY=
SMA_FINAL_EQUITY=
INDICATORS_FINAL_EQUITY=
AI_NO_HEDGE_FINAL_EQUITY=
AI_HEDGE_FINAL_EQUITY=
AI_HEDGE_AVG_FINAL_EQUITY=
AI_ADDED_VALUE=
HEDGE_ADDED_VALUE=
AVERAGING_ADDED_VALUE=
MAX_DRAWDOWN=
LIQUIDATIONS=
TRAINING_GPU_LOG=
ARTIFACTS=
OOS_OPENED=NO
LIVE_TRADING=NO
NEXT_WIP=none
```
