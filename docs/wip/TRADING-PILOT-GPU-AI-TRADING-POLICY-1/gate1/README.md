# GATE 1 - Simulator Repair Evidence

STATUS=PASS

## Environment

| Component | Version |
|---|---|
| S13 identity | `sergey@sergey-System-Product-Name` |
| Python | 3.12.3 |
| pytest | 9.2.0 |
| pandas | 3.0.6 |
| numpy | 2.5.3 |
| CatBoost | 1.2.10 |

## Test result

```text
19 passed in 3.93s
```

The suite ran from an isolated copy under:

```text
S13:/var/tmp/traiding_pilot_ui_workspace/gpu_ai_trading_policy_v1/gate1/
```

The complete log and source SHA256 inventory are committed beside this file.

## Repairs validated

- Explicit Spot <-> Futures transfer records with conservation checks.
- Separate Spot, PRIMARY, HEDGE, free collateral, used margin, unrealized PnL,
  realized PnL, and cost accounting.
- Spot exposure included in total portfolio stress loss.
- The 5% planned-risk limit applied to the futures thesis without incorrectly
  charging passive Spot market exposure to the active trade.
- Continuous thesis-loss monitoring on mark price, with risk exit before the
  liquidation check.
- Position liquidation price derived from accumulated margin and average entry.
- Mark-price high/low liquidation checks with isolated-loss treatment.
- Funding, fee, slippage, partial-fill, minimum-notional, and maximum-notional
  paths.
- Hedge-profit realization counted once; reinvestment only moves available
  collateral and cannot create equity.
- Causality check proving decisions occur only after the completed source bar.

## Deterministic scenarios

- Known 60/40 and 40/60 transfer balances preserve total capital.
- A profitable hedge close leaves futures equity unchanged at the same mark.
- Reinvesting that realized profit as averaging margin creates no new equity.
- A requested 200 USDT notional with a 50 USDT cap fills exactly 50 and records
  150 unfilled.
- A mark-price extreme below the calculated liquidation price triggers
  liquidation.
- An adverse move beyond the continuous 5% thesis limit triggers `RISK_EXIT`
  before liquidation.
- A bar-volume-derived order below the minimum notional is skipped.
- Post-cycle rebalancing emits an explicit transfer record.

## Limitations retained

- Intrabar liquidation uses mark OHLC, not order-book depth.
- Maintenance margin remains a fixed low-notional research assumption.
- Partial fill capacity is derived from a conservative fraction of bar volume.
- Spot trading fees are accounted separately from futures trading fees.
