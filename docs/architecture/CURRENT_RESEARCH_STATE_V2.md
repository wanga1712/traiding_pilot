# Current research state V2

The completed composite WIP is closed at commit `a5816ad7a42c131fe8e38d95e96cdecafe5eddb1`.
The current WIP is `PROBABILITY-MODEL-TRAINING-DATASET-1` in REVIEW. Its causal
development-only V2 dataset through `2023-06-20 06:08 UTC` passed target-engine,
source-boundary, causal-trace, reproducibility, and feature/target isolation
gates. `TRAINING_DATASET_READY=YES`. No model was trained, and OOS remains locked.

The dataset build runs on S13. Source market data remains authoritative on S7;
the S13 cache is a disposable build cache. Frozen parent artifacts are read
only and are not recomposed.
