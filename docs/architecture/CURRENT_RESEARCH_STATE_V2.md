# Current research state V2

The completed composite WIP is closed at commit `a5816ad7a42c131fe8e38d95e96cdecafe5eddb1`.
The active WIP is `PROBABILITY-MODEL-TRAINING-DATASET-1`. It builds a causal
development-only dataset through `2023-06-20 06:08 UTC` from the frozen
composite survivor bank and canonical S7 data. It does not train models,
calculate PnL/AUC, or read OOS rows.

The dataset build runs on S13. Source market data remains authoritative on S7;
the S13 cache is a disposable build cache. Frozen parent artifacts are read
only and are not recomposed.
