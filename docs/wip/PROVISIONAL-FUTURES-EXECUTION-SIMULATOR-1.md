# PROVISIONAL-FUTURES-EXECUTION-SIMULATOR-1

Status: **REVIEW**

Mode: `FROZEN-PROBABILITY-TO-PNL-1`

Parent OOS result: `5e498326d0f0ca747e042f29e4bf681cb7efb8e6`

Policy freeze commit: `910bb4cf774e47fefeaea12452a959cd00ef58cd`

Implementation commit: `36ed546f970675f3dad66507a7bfe97591465dc2`

Result commit: `5079c3df5d5d7f629a3249e0f0617163ae5733ac`

## Result

Both frozen probability streams have positive gross returns before costs, but
neither survives the frozen provisional 13 bps round-trip friction. The 30m
strategy compounds 100 USDT to 224.35 USDT at zero cost and to approximately
0.00000070 USDT under the primary cost model. The 60m strategy compounds to
121.05 USDT at zero cost and to approximately 0.00004818 USDT after primary
costs. Both therefore classify `EXECUTION_WEAK`: the gross signal is positive,
but execution costs consume it and every frozen OOS block has negative net
return.

| Metric | 30m | 60m |
|---|---:|---:|
| Long / short trades | 6629 / 8422 | 4217 / 7111 |
| Total trades | 15051 | 11328 |
| Exposure | 27.5599% | 41.4854% |
| Gross return | +124.3455% | +21.0514% |
| Net return | -99.9999993% | -99.9999518% |
| Ending equity | 0.0000007048 USDT | 0.0000481767 USDT |
| Minimum equity | 0.0000007048 USDT | 0.0000478246 USDT |
| Fees | 80.3432 USDT | 79.2735 USDT |
| Estimated slippage | 14.6079 USDT | 14.4134 USDT |
| Win rate | 36.3763% | 40.0335% |
| Profit factor | 0.2197 | 0.3478 |
| Max drawdown | 99.9999993% | 99.9999522% |
| Break-even round-trip cost | 0.5369 bps | 0.1686 bps |
| Classification | `EXECUTION_WEAK` | `EXECUTION_WEAK` |

The formal ruin condition is exactly `EQUITY_USDT <= 0`. Neither equity path
crossed zero, so `ACCOUNT_RUINED=NO` for both strategies and there is no ruin
timestamp or ruin trade ID. No capital was injected. Economically, both
accounts are effectively depleted, but the frozen rule does not permit adding
an unstated minimum-tradable-equity threshold after results are visible.

## Frozen chronological blocks

Every block lost almost all normalized equity after costs:

| Horizon | Block | Trades | Gross return | Net return | Normalized ending equity |
|---|---|---:|---:|---:|---:|
| 30m | 1 | 5264 | +21.5162% | -99.8710% | 0.1290 |
| 30m | 2 | 4971 | +149.6027% | -99.6117% | 0.3883 |
| 30m | 3 | 4816 | -26.0337% | -99.8594% | 0.1406 |
| 60m | 1 | 3762 | +3.7387% | -99.2229% | 0.7771 |
| 60m | 2 | 3803 | +8.8520% | -99.2272% | 0.7728 |
| 60m | 3 | 3763 | +7.1994% | -99.1978% | 0.8022 |

The passive ETH reference over the same OOS span was +7.8124%; the cash
reference was 0%. These references were not optimization objectives.

## Frozen policy and costs

- Threshold source: DEVELOPMENT OOF only, SHA256
  `dc3c90f88513a5023299ae6b19d9b8cef102c65d0cfcc402a153cf44f698b862`.
- 30m thresholds: short `0.4650778653995327`, long `0.55051926907757`.
- 60m thresholds: short `0.4696675122191984`, long `0.5445806653710086`.
- Threshold method: fixed linear Q10/Q90; OOS threshold searches: `0`.
- Entry: first canonical 1m open strictly after decision time.
- Exit: exact canonical 1m open after 30 or 60 minutes.
- One position per horizon, 1x leverage, 100% of current equity; no averaging,
  pyramiding, grid, martingale, stop, or take-profit.
- Taker fee: 0.00055 per side; slippage: 0.00010 per side; primary nominal
  round trip: 13 bps.
- Exact historical funding: `NO`. The fixed 1 bp funding-crossing diagnostic
  was reported separately and was not used to choose a result.

The fixed cost sensitivity confirms that the edge cannot tolerate ordinary
friction. At 5 bps, normalized ending equity is 0.1208 for 30m and 0.4193 for
60m; at the primary 13 bps it is approximately 0.000000705 and 0.00004821.

## Integrity

All authority and execution integrity gates pass:

- Parent OOS, OOS prediction, DEVELOPMENT OOF, and both model hashes: `PASS`.
- Model retrains: `0`; calibrator: `NO`; feature research: `0`.
- Future execution leakage: `0`; overlapping positions: `0`; averaging: `0`.
- Invalid gap fills: `0`; missing entry bars: `0`; missing exit bars: `0`.
- External recapitalizations: `0`.
- Independent post-run checks passed for entry timing, fixed holding periods,
  accounting reconciliation, equity continuity, threshold/direction mapping,
  non-overlap, and the formal ruin condition for both horizons.
- Local tests: 5 simulator tests and 4 parent OOS regression tests passed.

## Evidence

Small and medium result artifacts are in
`docs/wip/PROVISIONAL-FUTURES-EXECUTION-SIMULATOR-1/results/`. Large immutable
trade and equity tables remain on S13 under:

`/var/tmp/traiding_pilot_ui_workspace/artifacts/PROVISIONAL-FUTURES-EXECUTION-SIMULATOR-1/`

| Artifact | Rows | Bytes | SHA256 |
|---|---:|---:|---|
| `execution_trades_30m_v1.parquet` | 15051 | 2846385 | `43018eb3d8e3dfe738cf5c8612f1ba7d09c794283e0d2c7706b332bffde1d0cd` |
| `execution_equity_30m_v1.parquet` | 15052 | 380483 | `d252c96ad945167a818c8db95823f4afb651456447772255c3725a2e99f66f9b` |
| `execution_trades_60m_v1.parquet` | 11328 | 2163011 | `b9459fe21a892e63445ef27de006ce400b9d259ec095d63e358a7d7e34e810b9` |
| `execution_equity_60m_v1.parquet` | 11329 | 288325 | `16729acab602b1c718c1836b5e943331e6ee614c9c9db1d8897d46b3ac51d1e7` |

This WIP is ready for review. No next WIP has been started.
