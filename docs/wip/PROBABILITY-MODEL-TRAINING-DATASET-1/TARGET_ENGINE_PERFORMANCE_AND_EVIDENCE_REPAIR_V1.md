# Target engine performance and evidence repair

Status: REVIEW

The DEVELOPMENT-only V2 dataset completed on S13. The optimized target engine
uses one monotonic-deque preprocessing pass per horizon, preserves earliest-tie
semantics, and censors incomplete or boundary-crossing 1m paths.

- Rows: 143779
- Decision range: 2019-05-12 00:14:59.999999 UTC through 2023-06-20 05:59:59.999999 UTC
- Dense / atomic / composite features: 15 / 284 / 5478
- Atomic / composite NNZ: 1161488 / 11219446
- Complete / gap-censored / boundary-censored target windows: 1002040 / 4207 / 206
- Target engine: 37.238637815 seconds
- Full build: 151.558984337 seconds; peak RSS 3.222625732 GB
- Real regression tests: 22 PASS; tautological tests: 0
- Real causal traces: 5000, all source-resolved and value-matched
- OOS rows materialized: 0
- Model training, PnL, AUC, and feature importance: not run

Canonical large artifacts remain at
`/var/tmp/traiding_pilot_ui_workspace/artifacts/PROBABILITY-MODEL-TRAINING-DATASET-1/full_v2`.
The committed `v2_evidence` directory contains the manifests, registries,
integrity summaries, benchmark, causal audit sample, and completion gates.
