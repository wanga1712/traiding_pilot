from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SimulationResult:
    trades: pd.DataFrame
    equity: pd.DataFrame
    metrics: dict[str, Any]
    blocks: pd.DataFrame
    yearly: pd.DataFrame
    monthly: pd.DataFrame
    cost_sensitivity: pd.DataFrame


def _profit_factor(pnl: pd.Series) -> float:
    gains = float(pnl[pnl > 0].sum())
    losses = float(-pnl[pnl < 0].sum())
    if losses == 0:
        return float("inf") if gains > 0 else float("nan")
    return gains / losses


def _drawdown(equity: np.ndarray) -> tuple[float, float]:
    values = np.asarray(equity, dtype=np.float64)
    peaks = np.maximum.accumulate(values)
    drawdown_usdt = peaks - values
    drawdown_pct = np.divide(drawdown_usdt, peaks, out=np.zeros_like(values), where=peaks != 0) * 100.0
    return float(drawdown_pct.max(initial=0.0)), float(drawdown_usdt.max(initial=0.0))


def _max_streak(wins: np.ndarray, wanted: bool) -> int:
    best = current = 0
    for value in wins:
        if bool(value) is wanted:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def _funding_crossings(entry: pd.Timestamp, exit_: pd.Timestamp) -> int:
    start_day = entry.floor("D")
    end_day = exit_.floor("D")
    count = 0
    for day in pd.date_range(start_day, end_day, freq="D", tz="UTC"):
        for hour in (0, 8, 16):
            stamp = day + pd.Timedelta(hours=hour)
            count += int(entry < stamp <= exit_)
    return count


def _period_table(trades: pd.DataFrame, key: pd.Series, label: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for period, group in trades.groupby(key, sort=True):
        raw = group["gross_return"].to_numpy(dtype=np.float64)
        net = group["net_return"].to_numpy(dtype=np.float64)
        gross_curve = 100.0 * np.cumprod(1.0 + raw)
        net_curve = 100.0 * np.cumprod(1.0 + net)
        dd_pct, dd_usdt = _drawdown(np.r_[100.0, net_curve])
        rows.append({
            label: str(period),
            "trade_count": int(len(group)),
            "gross_return_percent": float((gross_curve[-1] / 100.0 - 1.0) * 100.0),
            "net_return_percent": float((net_curve[-1] / 100.0 - 1.0) * 100.0),
            "profit_factor": _profit_factor(group["net_pnl_usdt"]),
            "max_drawdown_percent": dd_pct,
            "max_drawdown_usdt_normalized": dd_usdt,
            "ending_equity_normalized_100": float(net_curve[-1]),
        })
    return pd.DataFrame(rows)


def _sensitivity(trades: pd.DataFrame, costs_bps: list[float]) -> tuple[pd.DataFrame, float]:
    raw = trades["gross_return"].to_numpy(dtype=np.float64)

    def ending(cost_bps: float) -> float:
        returns = raw - float(cost_bps) / 10000.0
        return float(100.0 * np.prod(1.0 + returns))

    rows = [
        {
            "round_trip_cost_bps": float(cost),
            "ending_equity_normalized_100": ending(float(cost)),
            "net_return_percent": ending(float(cost)) - 100.0,
        }
        for cost in costs_bps
    ]
    if not len(raw) or ending(0.0) <= 100.0:
        break_even = 0.0
    else:
        low, high = 0.0, 10000.0
        for _ in range(80):
            mid = (low + high) / 2.0
            if ending(mid) > 100.0:
                low = mid
            else:
                high = mid
        break_even = (low + high) / 2.0
    return pd.DataFrame(rows), float(break_even)


def classify_execution(
    gross_return_percent: float,
    net_return_percent: float,
    profit_factor: float,
    block_net_returns: list[float],
    ending_equity_usdt: float,
) -> str:
    if gross_return_percent <= 0:
        return "EXECUTION_NOT_SUPPORTED"
    supported = (
        net_return_percent > 0
        and profit_factor > 1.0
        and sum(float(x) > 0 for x in block_net_returns) >= 2
        and ending_equity_usdt > 100.0
    )
    return "EXECUTION_SUPPORTED" if supported else "EXECUTION_WEAK"


def simulate_strategy(
    predictions: pd.DataFrame,
    bars: pd.DataFrame,
    *,
    horizon_minutes: int,
    short_threshold: float,
    long_threshold: float,
    fee_per_side: float,
    slippage_per_side: float,
    starting_equity: float,
    oos_start: pd.Timestamp,
    oos_end: pd.Timestamp,
    frozen_blocks: list[dict[str, Any]],
    funding_stress_per_crossing: float,
    sensitivity_costs_bps: list[float],
) -> SimulationResult:
    pred = predictions[["row_id", "decision_at", "p_up"]].copy()
    pred["decision_at"] = pd.to_datetime(pred["decision_at"], utc=True)
    pred = pred.sort_values(["decision_at", "row_id"]).reset_index(drop=True)
    bar = bars[["open_time", "open"]].copy()
    bar["open_time"] = pd.to_datetime(bar["open_time"], utc=True)
    if bar["open_time"].duplicated().any():
        raise ValueError("duplicate canonical 1m open_time")
    opens = pd.Series(bar["open"].to_numpy(dtype=np.float64), index=bar["open_time"])

    equity = float(starting_equity)
    minimum_equity = equity
    occupied_until: pd.Timestamp | None = None
    ignored_while_open = 0
    skipped_missing_entry = 0
    skipped_missing_exit = 0
    ruined = False
    ruin_timestamp: str | None = None
    ruin_trade_id: str | None = None
    trade_rows: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = [{"trade_id": None, "timestamp": oos_start, "equity_usdt": equity}]

    for row in pred.itertuples(index=False):
        probability = float(row.p_up)
        direction = "LONG" if probability >= long_threshold else "SHORT" if probability <= short_threshold else None
        if direction is None:
            continue
        decision_at = pd.Timestamp(row.decision_at)
        if occupied_until is not None and decision_at < occupied_until:
            ignored_while_open += 1
            continue
        entry_time = decision_at.ceil("min")
        if entry_time <= decision_at:
            entry_time += pd.Timedelta(minutes=1)
        exit_time = entry_time + pd.Timedelta(minutes=horizon_minutes)
        if entry_time not in opens.index:
            skipped_missing_entry += 1
            continue
        if exit_time not in opens.index:
            skipped_missing_exit += 1
            continue

        entry_raw = float(opens.loc[entry_time])
        exit_raw = float(opens.loc[exit_time])
        sign = 1.0 if direction == "LONG" else -1.0
        entry_fill = entry_raw * (1.0 + sign * slippage_per_side)
        exit_fill = exit_raw * (1.0 - sign * slippage_per_side)
        equity_before = equity
        quantity = equity_before / entry_fill
        gross_pnl = sign * quantity * (exit_raw - entry_raw)
        fill_pnl = sign * quantity * (exit_fill - entry_fill)
        slippage_cost = gross_pnl - fill_pnl
        entry_fee = quantity * entry_fill * fee_per_side
        exit_fee = quantity * exit_fill * fee_per_side
        fee_total = entry_fee + exit_fee
        crossings = _funding_crossings(entry_time, exit_time)
        funding_stress_cost = equity_before * funding_stress_per_crossing * crossings
        net_pnl = fill_pnl - fee_total
        gross_return = gross_pnl / equity_before
        net_return = net_pnl / equity_before
        equity_after = equity_before + net_pnl
        trade_id = f"{horizon_minutes}m-{len(trade_rows) + 1:06d}"
        trade_rows.append({
            "trade_id": trade_id,
            "strategy_horizon": horizon_minutes,
            "row_id": int(row.row_id),
            "signal_decision_at": decision_at,
            "direction": direction,
            "probability": probability,
            "entry_time": entry_time,
            "entry_raw_price": entry_raw,
            "entry_fill_price": entry_fill,
            "exit_time": exit_time,
            "exit_raw_price": exit_raw,
            "exit_fill_price": exit_fill,
            "holding_minutes": horizon_minutes,
            "quantity": quantity,
            "gross_return": gross_return,
            "gross_pnl_usdt": gross_pnl,
            "entry_fee": entry_fee,
            "exit_fee": exit_fee,
            "fee_total": fee_total,
            "slippage_cost": slippage_cost,
            "funding_crossings": crossings,
            "funding_stress_cost": funding_stress_cost,
            "net_return": net_return,
            "net_pnl_usdt": net_pnl,
            "equity_before": equity_before,
            "equity_after": equity_after,
        })
        equity = equity_after
        minimum_equity = min(minimum_equity, equity)
        occupied_until = exit_time
        equity_rows.append({"trade_id": trade_id, "timestamp": exit_time, "equity_usdt": equity})
        if equity <= 0:
            ruined = True
            ruin_timestamp = exit_time.isoformat()
            ruin_trade_id = trade_id
            break

    trades = pd.DataFrame(trade_rows)
    equity_frame = pd.DataFrame(equity_rows)
    if trades.empty:
        raise RuntimeError(f"{horizon_minutes}m strategy produced no executable trades")

    raw_returns = trades["gross_return"].to_numpy(dtype=np.float64)
    gross_ending = float(starting_equity * np.prod(1.0 + raw_returns))
    gross_return_percent = float((gross_ending / starting_equity - 1.0) * 100.0)
    net_return_percent = float((equity / starting_equity - 1.0) * 100.0)
    pf = _profit_factor(trades["net_pnl_usdt"])
    dd_pct, dd_usdt = _drawdown(equity_frame["equity_usdt"].to_numpy(dtype=np.float64))
    trade_net = trades["net_return"].to_numpy(dtype=np.float64)
    sharpe = float(np.sqrt(len(trade_net)) * trade_net.mean() / trade_net.std(ddof=1)) if len(trade_net) > 1 and trade_net.std(ddof=1) > 0 else float("nan")

    block_labels = np.zeros(len(trades), dtype=np.int8)
    for idx, block in enumerate(frozen_blocks, 1):
        start, end = pd.Timestamp(block["start"]), pd.Timestamp(block["end"])
        mask = (trades["signal_decision_at"] >= start) & (trades["signal_decision_at"] <= end)
        block_labels[mask.to_numpy()] = idx
    if np.any(block_labels == 0):
        raise RuntimeError("executed trade outside frozen OOS blocks")
    blocks = _period_table(trades, pd.Series(block_labels, index=trades.index), "block")
    blocks["block"] = blocks["block"].map(lambda x: f"OOS_BLOCK_{x}")
    block_returns = blocks["net_return_percent"].astype(float).tolist()

    yearly = _period_table(trades, trades["entry_time"].dt.year, "year")
    monthly = _period_table(trades, trades["entry_time"].dt.strftime("%Y-%m"), "month")
    sensitivity, break_even = _sensitivity(trades, sensitivity_costs_bps)
    sensitivity.insert(0, "horizon_minutes", horizon_minutes)

    wins = trades["net_pnl_usdt"].to_numpy() > 0
    span_minutes = (oos_end - oos_start).total_seconds() / 60.0 + 15.0
    metrics: dict[str, Any] = {
        "horizon_minutes": horizon_minutes,
        "strategy_id": f"STRATEGY_{horizon_minutes}M_RAW_Q10Q90",
        "total_trades": int(len(trades)),
        "long_trades": int((trades["direction"] == "LONG").sum()),
        "short_trades": int((trades["direction"] == "SHORT").sum()),
        "exposure_percent": float(trades["holding_minutes"].sum() / span_minutes * 100.0),
        "gross_return_percent": gross_return_percent,
        "net_return_percent": net_return_percent,
        "ending_equity_usdt": equity,
        "minimum_equity_usdt": minimum_equity,
        "account_ruined": "YES" if ruined else "NO",
        "ruin_timestamp": ruin_timestamp,
        "ruin_trade_id": ruin_trade_id,
        "trades_before_ruin": int(len(trades) - 1 if ruined else len(trades)),
        "total_fees_usdt": float(trades["fee_total"].sum()),
        "estimated_slippage_usdt": float(trades["slippage_cost"].sum()),
        "funding_stress_cost_usdt_diagnostic": float(trades["funding_stress_cost"].sum()),
        "funding_stress_ending_equity_usdt_diagnostic": float(
            starting_equity
            * np.prod(1.0 + trades["net_return"].to_numpy(dtype=np.float64)
                      - trades["funding_crossings"].to_numpy(dtype=np.float64) * funding_stress_per_crossing)
        ),
        "average_net_return_per_trade": float(trades["net_return"].mean()),
        "median_net_return_per_trade": float(trades["net_return"].median()),
        "win_rate": float(wins.mean()),
        "profit_factor": pf,
        "max_drawdown_percent": dd_pct,
        "max_drawdown_usdt": dd_usdt,
        "sharpe_diagnostic": sharpe,
        "long_net_return_percent_of_start": float(trades.loc[trades.direction == "LONG", "net_pnl_usdt"].sum() / starting_equity * 100.0),
        "short_net_return_percent_of_start": float(trades.loc[trades.direction == "SHORT", "net_pnl_usdt"].sum() / starting_equity * 100.0),
        "best_trade_net_return": float(trades["net_return"].max()),
        "worst_trade_net_return": float(trades["net_return"].min()),
        "consecutive_wins_max": _max_streak(wins, True),
        "consecutive_losses_max": _max_streak(wins, False),
        "gross_positive": "YES" if gross_return_percent > 0 else "NO",
        "net_after_costs_positive": "YES" if net_return_percent > 0 else "NO",
        "break_even_round_trip_cost_bps": break_even,
        "ignored_signals_while_position_open": ignored_while_open,
        "skipped_missing_entry_bar": skipped_missing_entry,
        "skipped_missing_exit_bar": skipped_missing_exit,
    }
    metrics["execution_class"] = classify_execution(gross_return_percent, net_return_percent, pf, block_returns, equity)
    return SimulationResult(trades, equity_frame, metrics, blocks, yearly, monthly, sensitivity)
