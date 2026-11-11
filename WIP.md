# WIP - TRADING-PILOT-GPU-AI-TRADING-POLICY-1

STATUS=ACTIVE
PHASE=GATE_2_DATASET
STARTED_AT=2026-11-11
MODE=REPAIR -> DATASET -> GPU TRAINING -> BACKTEST
MODEL=NEW_TRAIN_FROM_SCRATCH
INITIAL_CAPITAL=100 USDT
ASSET=ETHUSDT
LEVERAGE=10X_ISOLATED
HEDGE_MODE=ENABLED_IN_SIMULATOR
LIVE_TRADING=DISABLED

## Authorization and governance

- `USER_AUTHORIZATION=YES`
- S13 training and isolated research mutation are authorized.
- S7 remains read-only.
- OOS and confirmation remain locked.
- Frozen models and research artifacts remain immutable.
- `TRADING-PILOT-CAPITAL-GROWTH-EXPERIMENT-1` remains `REVIEW`.
- No other primary WIP was `ACTIVE` at activation.

## Current phase

GATE 0 and GATE 1 passed. CatBoost trained on CUDA and the repaired simulator
passed 19 deterministic tests locally and on S13. GATE 2 now builds the causal
DEVELOPMENT dataset.

## Immutable negative baseline

`TRADING-PILOT-CAPITAL-GROWTH-EXPERIMENT-1` remains unchanged at evidence
commit `4b15f3d7cb678a5d349d744584cd80c47b4a2c21` and handoff commit
`e044daaa470dabfbb6102232e2cb5a8866d90039`. Its SMA20/SMA50 policy and
negative result must not be overwritten or presented as the new AI strategy.

## Required gates

- GATE 0: genuine CUDA training.
- GATE 1: accounting, margin, liquidation, risk, and causality tests.
- GATE 2: leakage-free reproducible DEVELOPMENT dataset.
- GATE 3: reproducible GPU ENTRY and POSITION_MANAGEMENT models.
- GATE 4: constrained AI policy.
- GATE 5: frozen RUN 1 and chronological RUN 2.

## RETURN

```text
WIP=TRADING-PILOT-GPU-AI-TRADING-POLICY-1
STATUS=ACTIVE
PHASE=GATE_2_DATASET
LOCAL_BRANCH=wip/trading-pilot-gpu-ai-trading-policy-1
BASE_MAIN=e044daaa470dabfbb6102232e2cb5a8866d90039
INITIAL_CAPITAL=100
LEVERAGE=10
HEDGE_MODE=ENABLED_IN_SIMULATOR
GPU_NAME=NVIDIA_GTX_1660_SUPER
CUDA_AVAILABLE=YES_DRIVER_13.2
GPU_TRAINING_CONFIRMED=YES_CATBOOST_1.2.10
GPU_VRAM_USED=MAX_5473_MIB
SIMULATOR_ACCOUNTING=PASS
DATASET_ROWS=pending
ENTRY_MODEL_TRAINED=pending
MANAGEMENT_MODEL_TRAINED=pending
RUN1=pending
RUN2=pending
OOS_OPENED=NO
LIVE_TRADING=NO
NEXT_WIP=none
```
