# UI layout v1 — Historical run result panel

Location: **below** Lightweight Charts (`#lwc-chart`), above seed bar.

## Vertical stack

1. **RUN selector** — dropdown + metadata row (`RUN_ID`, `STATUS`, `CREATED_AT`, `STRATEGY_VERSION`)
2. **Header** — strategy name, period, status badge, execution realism badge
3. **Six summary cards** — START, FINAL, RETURN, TRADES, MAX DD, LIQUIDATIONS
4. **Equity curve** — Plotly line chart or `EQUITY CURVE NOT AVAILABLE`
5. **Cost reconciliation** — gross PnL minus fees/funding/spread/slippage/liquidation = NET PnL
6. **Detail tabs** — TRADES | COSTS | LIQUIDATIONS | RUN PARAMETERS

## Empty state

`NO EXECUTION RUN AVAILABLE` when manifest has no runs (production default).

## RUNNING

Banner only — no partial equity presented as final.

## STRUCTURAL_ONLY

Research metrics (precision/recall/FPR/remaining wave) in secondary grid. No monetary cards.

## Visual hierarchy

Primary: start balance → final balance → net return → max drawdown → trades → liquidations.

Win rate / profit factor: secondary row below reconciliation.

## Colors (dark theme)

- Positive: `#26a69a`
- Negative: `#ef5350`
- Running/warning: `#ffb74d`
- Unknown: `#787b86` (em dash, not zero)
