# WIP=TRADING-PILOT-GPU-AI-TRADING-POLICY-1

STATUS=REVIEW
PHASE=REVIEW
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

#### GATE 0 result: PASS

| Field | Value |
|---|---|
| Host | `sergey-System-Product-Name` |
| User | `sergey` |
| GPU | NVIDIA GeForce GTX 1660 SUPER |
| Compute capability | 7.5 |
| VRAM | 6,144 MiB |
| Driver | 595.99.02 |
| Driver-reported CUDA | 13.2 |
| Python | 3.12.3 |
| CatBoost | 1.2.10 |
| Training mode | `task_type="GPU"`, `devices="0"` |
| Smoke dataset | 64,000 train / 16,000 validation rows, 24 features |
| Iterations | 120 |
| Validation AUC | 0.87871 |
| Peak observed VRAM | 5,473 MiB |
| Peak observed GPU utilization | 33% |
| Training time | 1.33 seconds |
| Reload | PASS |
| Smoke model SHA256 | `032d8b8c93288242a782544ca70fee43d2dea22b0c017add8b9495afa508e824` |

Evidence is committed under `gate0/`. The smoke model is synthetic and is not
a trading model.

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

#### GATE 1 result: PASS

The repaired simulator passed 19 deterministic tests locally and on an isolated
S13 copy. Evidence is committed under `gate1/`.

Validated paths include explicit Spot/Futures transfer records, isolated
PRIMARY/HEDGE accounting, Spot-aware portfolio stress, a continuously enforced
5% futures-thesis loss limit, margin-based liquidation prices, mark high/low
liquidation, funding/costs, partial fills, min/max order size, and
reinvestment without synthetic capital.

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

## Final results

### GATE 2 - PASS

- `GPU_AI_POLICY_DATASET_V1`: 17,514 causal 1H decisions.
- 453 dense, 284 atomic, and 5,478 composite features; 6,215 total.
- 48,240 complete target windows across 24h, 72h, and 168h.
- 4,038 target windows censored by source gaps and 264 at the data boundary.
- Chronological TRAIN: 4,356 rows; SELECTION: 4,411; LOCKED 2021: 8,747.
- 8,411 train/selection rows pass the 168h purge and 24h embargo gate.
- Target reference parity: PASS.
- Feature values are never zero-filled; unavailable values remain missing.

The execution source ends at `2022-01-01` exclusive. A 2022 RUN 2 would require
a separately authorized futures/mark/funding ingestion path, so the available
chronological validation is 2021. This is DEVELOPMENT reuse, not independent
OOS.

### GATE 3 - PASS with negative predictive evidence

- ENTRY direction model: GPU, selection accuracy 49.91%, logloss 0.92180.
- ENTRY risk model: GPU, 24h excursion MAE 0.02369.
- POSITION_MANAGEMENT model: GPU, selection accuracy 45.89%, logloss 1.10440.
- Peak observed VRAM: 5,473 MiB across the GPU jobs.
- All three models save and reload reproducibly.
- The management training labels contain five observed classes; no selected
  `CLOSE_HEDGE` training example exists, so that class probability is
  unsupported by data.

High-confidence entry predictions do not improve accuracy. The new models do
not establish a predictive edge.

### GATE 4/5 - frozen policy and historical comparison

Representative 60/40, spot HOLD results:

| Strategy | RUN 1 2020 | RUN 2 2021 |
|---|---:|---:|
| BUY_HOLD | 381.86 | 339.31 |
| SMA_BASELINE | 342.35 | 299.81 |
| INDICATORS_ONLY | 342.31 | 299.75 |
| AI_NO_HEDGE | 342.30 | 299.81 |
| AI_HEDGE | 342.36 | 299.81 |
| AI_HEDGE_AVG | 342.35 | 299.81 |

- AI added value versus indicators-only is mixed and at most +0.47 USDT.
- Hedge added value is at most +0.05 USDT in RUN 1 and zero in RUN 2.
- Averaging is negative to negligible.
- All AI variants lose to Buy & Hold.
- AI SWING variants are materially worse, ending RUN 2 between 40.48 and
  60.46 USDT for the tested allocations.
- Best AI drawdown is 38.06% in RUN 1 and 60.06% in RUN 2.
- Best AI representative records one liquidation in each run.

Policy SHA256:
`d296c8107bef0c68fe06b92532026e485b08b194e10ec89a5f3e1b6ab179434c`.

Evidence is committed under `gate2/`, `gate3/`, and `gate4/`; full datasets,
all policy variants, and runtime tables remain on S13.
`runtime_manifest_v1.json` inventories 679 final runtime files totaling
92,056,733 bytes.

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
GPU_NAME=NVIDIA_GTX_1660_SUPER
CUDA_AVAILABLE=YES_DRIVER_13.2
GPU_TRAINING_CONFIRMED=YES_CATBOOST_1.2.10
GPU_VRAM_USED=MAX_5473_MIB
SIMULATOR_ACCOUNTING=PASS
DATASET_ROWS=17514
FEATURE_COUNT=6215_TOTAL;ENTRY_SELECTED_200;MANAGEMENT_SELECTED_201
INDICATOR_FAMILIES_USED=DMA;MACD;STOCHASTIC;RSI;ADX;ATR;BOLLINGER;REALIZED_VOL;DNO;OSC_PREDICTOR;INVERSE;COMPOSITE;ZIGZAG_CONFIRMED;MULTI_TF;VOLUME_STRUCTURE;PORTFOLIO_STATE
ENTRY_MODEL_TRAINED=YES
MANAGEMENT_MODEL_TRAINED=YES
RISK_MODEL_TRAINED=YES
MODEL_SHA256=ENTRY=df5c3eaefaab1dbdf47441e765886e882e24f2373af6dae2df86977e7b49bc86;RISK=ab2955f0efd89565d3833402cdb8425c877c8ed4bac9d34246819cbb405fd45d;MANAGEMENT=3da5206e4099ae0edec19c0485731c33dc0af20bf1848820e714bce62f9fada0
RUN1=2020-01-01..2021-01-01
RUN2=2021-01-01..2022-01-01_DEVELOPMENT_ONLY_NOT_OOS
POLICY_SHA256=d296c8107bef0c68fe06b92532026e485b08b194e10ec89a5f3e1b6ab179434c
BUY_HOLD_FINAL_EQUITY=RUN1_381.86;RUN2_339.31
SMA_FINAL_EQUITY=RUN1_342.35;RUN2_299.81
INDICATORS_FINAL_EQUITY=RUN1_342.31;RUN2_299.75
AI_NO_HEDGE_FINAL_EQUITY=RUN1_342.30;RUN2_299.81
AI_HEDGE_FINAL_EQUITY=RUN1_342.36;RUN2_299.81
AI_HEDGE_AVG_FINAL_EQUITY=RUN1_342.35;RUN2_299.81
AI_ADDED_VALUE=MIXED_-0.005_TO_+0.466_RUN1;+0.068_TO_+0.125_RUN2_HOLD
HEDGE_ADDED_VALUE=MAX_+0.055_RUN1;0_RUN2
AVERAGING_ADDED_VALUE=MIXED_-54.50_TO_+0.023_RUN1;0_RUN2
MAX_DRAWDOWN=BEST_AI_RUN1_38.06%;BEST_AI_RUN2_60.06%
LIQUIDATIONS=BEST_AI_REPRESENTATIVE_1_PER_RUN
TRAINING_GPU_LOG=docs/wip/TRADING-PILOT-GPU-AI-TRADING-POLICY-1/gate3/gate3_training.log
ARTIFACTS=docs/wip/TRADING-PILOT-GPU-AI-TRADING-POLICY-1/gate2;gate3;gate4;runtime_manifest_v1.json;S13:/var/tmp/traiding_pilot_ui_workspace/gpu_ai_trading_policy_v1/
OOS_OPENED=NO
LIVE_TRADING=NO
NEXT_WIP=none
```
