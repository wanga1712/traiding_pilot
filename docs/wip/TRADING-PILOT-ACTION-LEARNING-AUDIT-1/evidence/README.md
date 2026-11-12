# Action-Learning Audit Evidence

STATUS=PASS

- `action_learning_audit_v1.json` contains the machine-readable action,
  label-margin, prediction, feature-importance, risk-baseline, and Qwen
  permission audit.
- `action_learning_audit_v1.log` is the exact execution log.
- Producer:
  `phase3_staging/crypto_trading_bot/research_v2/gpu_ai_policy/action_audit.py`.

The audit used existing artifacts only. It did not train CatBoost, invoke Qwen,
write predictions, alter frozen files, or run historical policy variants.

SHA256:

```text
342ee3a68ea9e7a17377103dd13268cb6245092d6d60b88e0fd82dc90f86cd6c  action_learning_audit_v1.json
fc73c89f18f27274bceb6ee45aebb1dc7a284dc0cc4f676acaa6d422ad69ba8d  action_learning_audit_v1.log
```
