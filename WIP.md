# WIP - TRADING-PILOT-GPU-AI-TRADING-POLICY-1

STATUS=REVIEW
PHASE=REVIEW
STARTED_AT=2026-11-11
ADDENDUM_AUTHORIZED_AT=2026-11-12
REVIEWED_AT=2026-11-12
MODE=REPAIR -> DATASET -> GPU TRAINING -> BACKTEST
INITIAL_CAPITAL=100 USDT
ASSET=ETHUSDT
LEVERAGE=10X_ISOLATED
HEDGE_MODE=ENABLED_IN_SIMULATOR
LIVE_TRADING=DISABLED

## Outcome

All gates completed without opening OOS or changing frozen research artifacts.

- CatBoost 1.2.10 trained on the S13 GTX 1660 SUPER with `task_type="GPU"`.
- Peak VRAM observed: 5,473 MiB of 6,144 MiB.
- Simulator repair passed 22 tests locally and 22 on S13.
- New dataset: 17,514 causal 1H decisions and 6,215 features.
- Entry model accuracy: 49.91%; management accuracy: 45.89%.
- All AI variants lost to the matching Buy & Hold baseline.
- AI added value over indicators-only is mixed and at most +0.47 USDT.
- Hedge and averaging added value is negligible or negative.
- Best AI drawdown: 38.06% in RUN 1 and 60.06% in RUN 2.
- Qwen `qwen2.5:7b` was tested through Ollama without retraining.
- Qwen made 104 inference decisions and changed zero CatBoost actions.
- `CATBOOST_PLUS_QWEN` added 0.00 USDT in all four run/allocation pairs.

The correct conclusion is `NO_MATERIAL_VALIDATED_EDGE`. The negative result is
preserved.

## Important data limitation

Available futures/mark/funding and 1m execution data end at `2022-01-01`
exclusive. RUN 2 is therefore 2021 chronological DEVELOPMENT validation, not
independent OOS. Extending into 2022 requires a separately authorized
futures/mark/funding ingestion WIP through the canonical data route.

## Safety

- No live orders, API trading keys, deployment, or service restart.
- No S7 mutation.
- S13 mutation stayed in the isolated experiment workspace.
- OOS and confirmation remained closed.
- Frozen CatBoost models and research artifacts were not changed.
- Previous capital-growth WIP remains `REVIEW`.
- No next WIP was activated automatically.

## Evidence

- `docs/wip/TRADING-PILOT-GPU-AI-TRADING-POLICY-1/gate0/`
- `docs/wip/TRADING-PILOT-GPU-AI-TRADING-POLICY-1/gate1/`
- `docs/wip/TRADING-PILOT-GPU-AI-TRADING-POLICY-1/gate2/`
- `docs/wip/TRADING-PILOT-GPU-AI-TRADING-POLICY-1/gate3/`
- `docs/wip/TRADING-PILOT-GPU-AI-TRADING-POLICY-1/gate4/`
- `docs/wip/TRADING-PILOT-GPU-AI-TRADING-POLICY-1/qwen_preflight/`
- `docs/wip/TRADING-PILOT-GPU-AI-TRADING-POLICY-1/qwen_results/`
- `docs/wip/TRADING-PILOT-GPU-AI-TRADING-POLICY-1/runtime_manifest_v1.json`
- Full runtime: `S13:/var/tmp/traiding_pilot_ui_workspace/gpu_ai_trading_policy_v1/`

## RETURN

```text
WIP=TRADING-PILOT-GPU-AI-TRADING-POLICY-1
STATUS=REVIEW
LOCAL_BRANCH=wip/trading-pilot-gpu-ai-trading-policy-1
BASE_MAIN=e044daaa470dabfbb6102232e2cb5a8866d90039
GPU_NAME=NVIDIA_GTX_1660_SUPER
CUDA_AVAILABLE=YES_DRIVER_13.2
GPU_TRAINING_CONFIRMED=YES
GPU_VRAM_USED=MAX_5473_MIB
CATBOOST_GPU_TRAINED=YES
QWEN_MODEL_ID=qwen2.5:7b
QWEN_PARAMETER_COUNT=7.6B
QWEN_RUNTIME=OLLAMA_LOCAL_HTTP
QWEN_GPU_VRAM=4748056984_BYTES
QWEN_POLICY_USED=YES
QWEN_DECISIONS_COUNT=104
SIMULATOR_ACCOUNTING=PASS
DATASET_ROWS=17514
FEATURE_COUNT=6215
ENTRY_MODEL_TRAINED=YES
MANAGEMENT_MODEL_TRAINED=YES
RUN1=2020
RUN2=2021_DEVELOPMENT_ONLY
POLICY_SHA256=9891c1dad6ff49a316f66c07a63c8f9740dbc4532c12bdb43ab373a6e5cecaec
BUY_HOLD_FINAL_EQUITY=RUN1_381.86;RUN2_339.31
SMA_FINAL_EQUITY=RUN1_342.35;RUN2_299.81
INDICATORS_FINAL_EQUITY=RUN1_342.31;RUN2_299.75
AI_NO_HEDGE_FINAL_EQUITY=RUN1_342.30;RUN2_299.81
AI_HEDGE_FINAL_EQUITY=RUN1_342.36;RUN2_299.81
AI_HEDGE_AVG_FINAL_EQUITY=RUN1_342.35;RUN2_299.81
CATBOOST_ONLY_FINAL_EQUITY=RUN1_60_342.3452;RUN1_40_228.4057;RUN2_60_299.8139;RUN2_40_200.0139
CATBOOST_PLUS_QWEN_FINAL_EQUITY=RUN1_60_342.3452;RUN1_40_228.4057;RUN2_60_299.8139;RUN2_40_200.0139
QWEN_ADDED_VALUE=0.00
AI_ADDED_VALUE=MIXED_NOT_MATERIAL
HEDGE_ADDED_VALUE=NO_MATERIAL_EDGE
AVERAGING_ADDED_VALUE=NEGATIVE_OR_NONE
BEATS_BUY_AND_HOLD=NO
OOS_OPENED=NO
LIVE_TRADING=NO
NEXT_WIP=none
```
