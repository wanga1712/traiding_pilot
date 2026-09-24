# Current research state V2

The completed composite WIP is closed at commit `a5816ad7a42c131fe8e38d95e96cdecafe5eddb1`.
The dataset WIP is CLOSED at `201efd1e1b98056d526baced8042a51887c0218e`.
The current WIP is `PROBABILITY-MODEL-BAKEOFF-1` in ACTIVE status. It trains
fixed model configurations using only the frozen DEVELOPMENT V2 artifacts and
chronological walk-forward folds. DEVELOPMENT reuse bias is explicit. OOS,
execution simulation, and PnL remain locked.

The dataset build runs on S13. Source market data remains authoritative on S7;
the S13 cache is a disposable build cache. Frozen parent artifacts are read
only and are not recomposed.
