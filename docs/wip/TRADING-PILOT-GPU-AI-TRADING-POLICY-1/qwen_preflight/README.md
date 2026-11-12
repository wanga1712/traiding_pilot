# Qwen Runtime Preflight

STATUS=PASS

## Runtime

| Field | Value |
|---|---|
| Runtime | Ollama local HTTP |
| Model ID | `qwen2.5:7b` |
| Digest | `845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e` |
| Parameters | 7.6B |
| Quantization | Q4_K_M |
| Context | 32,768 trained; 4,096 loaded |
| GPU | NVIDIA GTX 1660 SUPER |
| Loaded VRAM | 4,748,056,984 bytes, reported as 4.7 GB |

The model was already resident in Ollama. No reinstall, reload, fine-tuning,
or LoRA was performed.

## Contract test

- Three identical causal requests.
- Action deterministic: 3/3.
- Confidence deterministic: 3/3.
- Full JSON text deterministic: 3/3.
- Contract validation: 3/3 PASS.
- Median latency: 5.879 seconds.
- Observed latency range: 4.598-38.815 seconds.

The first unstructured probe returned confidence as `61` instead of `0.61`;
this exposed that Ollama's structured-output schema did not enforce numeric
bounds. The adapter now independently validates and normalizes 0-100 to 0-1.

## Safety

- Prompts contain only supplied causal features, CatBoost predictions, and
  portfolio/risk state.
- Future target prefixes are rejected before inference.
- Unknown keys, actions, directions, non-finite confidence, inconsistent
  direction/action pairs, and malformed JSON are rejected.
- Invalid or low-confidence responses fall back to the frozen CatBoost action.
- Risk Engine remains authoritative after every Qwen response.

LoRA/QLoRA was not attempted: the base model already occupies roughly 4.7 GB
of 6.1 GB VRAM, while CatBoost training previously peaked at 5.47 GB. The
models must run serially on this GPU.

Files:

- `qwen_contract_preflight_v1.json`
- `qwen_contract_test_v1.jsonl`
- `qwen_preflight_v2.log`
