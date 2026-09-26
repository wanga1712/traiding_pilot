from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PolicyResult:
    trades: pd.DataFrame
    equity: pd.DataFrame
    metrics: dict[str, Any]


def direction_at(p30: float, p60: float, candidate: dict[str, Any]) -> int:
    source = candidate["entry_source"]
    long30 = p30 >= candidate.get("long_threshold_30m", np.inf)
    short30 = p30 <= candidate.get("short_threshold_30m", -np.inf)
    long60 = p60 >= candidate.get("long_threshold_60m", np.inf)
    short60 = p60 <= candidate.get("short_threshold_60m", -np.inf)
    if source == "30M_ONLY":
        return 1 if long30 else -1 if short30 else 0
    if source == "60M_ONLY":
        return 1 if long60 else -1 if short60 else 0
    if source == "BOTH_AGREE":
        return 1 if long30 and long60 else -1 if short30 and short60 else 0
    raise ValueError(f"unknown entry source: {source}")


def should_exit(direction: int, p30: float, p60: float, candidate: dict[str, Any]) -> bool:
    source = candidate["entry_source"]
    family = candidate["exit_family"]
    if family == "CONFIDENCE_LOSS":
        return direction_at(p30, p60, candidate) != direction
    if family == "NEUTRAL_CROSS":
        if source == "30M_ONLY":
            return p30 <= 0.5 if direction == 1 else p30 >= 0.5
        if source == "60M_ONLY":
            return p60 <= 0.5 if direction == 1 else p60 >= 0.5
        return (p30 <= 0.5 or p60 <= 0.5) if direction == 1 else (p30 >= 0.5 or p60 >= 0.5)
    if family == "REVERSE_THRESHOLD":
        if source == "30M_ONLY":
            return p30 <= candidate["short_threshold_30m"] if direction == 1 else p30 >= candidate["long_threshold_30m"]
        if source == "60M_ONLY":
            return p60 <= candidate["short_threshold_60m"] if direction == 1 else p60 >= candidate["long_threshold_60m"]
        if direction == 1:
            return p30 <= candidate["short_threshold_30m"] and p60 <= candidate["short_threshold_60m"]
        return p30 >= candidate["long_threshold_30m"] and p60 >= candidate["long_threshold_60m"]
    raise ValueError(f"unknown exit family: {family}")


def _profit_factor(returns: np.ndarray) -> float:
    gains = float(returns[returns > 0].sum())
    losses = float(-returns[returns < 0].sum())
    if losses == 0:
        return float("inf") if gains > 0 else float("nan")
    return gains / losses


def _ending(raw: np.ndarray, cost_bps: float) -> float:
    return float(100.0 * np.prod(1.0 + raw - cost_bps / 10000.0))


def break_even_cost_bps(raw: np.ndarray) -> float:
    if not len(raw) or _ending(raw, 0.0) <= 100.0:
        return 0.0
    low, high = 0.0, 10000.0
    for _ in range(80):
        mid = (low + high) / 2.0
        if _ending(raw, mid) > 100.0:
            low = mid
        else:
            high = mid
    return float((low + high) / 2.0)


def simulate_policy(
    decisions: pd.DataFrame,
    opens: pd.Series,
    candidate: dict[str, Any],
    *,
    fee_per_side: float = 0.00055,
    slippage_per_side: float = 0.00010,
    starting_equity: float = 100.0,
) -> PolicyResult:
    frame = decisions[["row_id", "decision_at", "p30", "p60"]].copy()
    frame["decision_at"] = pd.to_datetime(frame["decision_at"], utc=True)
    frame = frame.sort_values(["decision_at", "row_id"]).reset_index(drop=True)
    if frame["decision_at"].duplicated().any():
        raise ValueError("duplicate decision_at")
    price = opens.copy()
    price.index = pd.to_datetime(price.index, utc=True)
    if price.index.duplicated().any():
        raise ValueError("duplicate canonical 1m open")

    persistence = int(candidate["entry_persistence_decisions"])
    min_hold = pd.Timedelta(minutes=int(candidate["minimum_hold_minutes"]))
    max_hold = pd.Timedelta(minutes=int(candidate["maximum_hold_minutes"]))
    cooldown = pd.Timedelta(minutes=int(candidate["cooldown_minutes"]))
    equity = float(starting_equity)
    min_equity = equity
    peak = equity
    max_dd = 0.0
    position: dict[str, Any] | None = None
    cooldown_until: pd.Timestamp | None = None
    prior_signal = 0
    streak = 0
    invalid_gap_count = 0
    incomplete_open_position_count = 0
    exposure_minutes = 0.0
    rows: list[dict[str, Any]] = []
    curve = [{"trade_id": None, "timestamp": frame.iloc[0]["decision_at"], "equity_usdt": equity}]

    def fill_time_after(ts: pd.Timestamp) -> pd.Timestamp:
        value = ts.ceil("min")
        return value if value > ts else value + pd.Timedelta(minutes=1)

    def close(exit_time: pd.Timestamp, exit_reason: str) -> bool:
        nonlocal equity, min_equity, peak, max_dd, position, cooldown_until, invalid_gap_count, exposure_minutes
        assert position is not None
        if exit_time not in price.index:
            invalid_gap_count += 1
            return False
        direction = int(position["direction"])
        raw_exit = float(price.loc[exit_time])
        exit_fill = raw_exit * (1.0 - direction * slippage_per_side)
        raw_entry = float(position["entry_raw_price"])
        entry_fill = float(position["entry_fill_price"])
        quantity = float(position["quantity"])
        gross_return = direction * (raw_exit - raw_entry) / raw_entry
        fill_pnl = direction * quantity * (exit_fill - entry_fill)
        exit_fee = quantity * exit_fill * fee_per_side
        net_pnl = fill_pnl - float(position["entry_fee"]) - exit_fee
        before = equity
        equity = before + net_pnl
        net_return = net_pnl / before
        trade_id = f"POLICY-{len(rows) + 1:06d}"
        holding = (exit_time - position["entry_time"]).total_seconds() / 60.0
        exposure_minutes += holding
        rows.append({
            "trade_id": trade_id, "row_id": position["row_id"],
            "signal_decision_at": position["decision_at"],
            "direction": "LONG" if direction == 1 else "SHORT",
            "entry_time": position["entry_time"], "entry_raw_price": raw_entry,
            "entry_fill_price": entry_fill, "exit_time": exit_time,
            "exit_raw_price": raw_exit, "exit_fill_price": exit_fill,
            "exit_reason": exit_reason, "holding_minutes": holding,
            "quantity": quantity, "gross_return": gross_return,
            "net_return": net_return, "net_pnl_usdt": net_pnl,
            "entry_fee": position["entry_fee"], "exit_fee": exit_fee,
            "equity_before": before, "equity_after": equity,
        })
        min_equity = min(min_equity, equity)
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100.0)
        curve.append({"trade_id": trade_id, "timestamp": exit_time, "equity_usdt": equity})
        cooldown_until = exit_time + cooldown
        position = None
        return True

    for row in frame.itertuples(index=False):
        decision_at = pd.Timestamp(row.decision_at)
        signal = direction_at(float(row.p30), float(row.p60), candidate)
        if signal != 0 and signal == prior_signal:
            streak += 1
        elif signal != 0:
            streak = 1
        else:
            streak = 0
        prior_signal = signal

        if position is not None:
            cap_time = position["entry_time"] + max_hold
            if cap_time <= decision_at:
                if not close(cap_time, "MAX_HOLD"):
                    break
            elif decision_at >= position["entry_time"] + min_hold and should_exit(
                int(position["direction"]), float(row.p30), float(row.p60), candidate
            ):
                if not close(fill_time_after(decision_at), candidate["exit_family"]):
                    break

        if equity <= 0 or position is not None or signal == 0 or streak < persistence:
            continue
        entry_time = fill_time_after(decision_at)
        if cooldown_until is not None and entry_time < cooldown_until:
            continue
        if entry_time not in price.index:
            invalid_gap_count += 1
            continue
        raw_entry = float(price.loc[entry_time])
        entry_fill = raw_entry * (1.0 + signal * slippage_per_side)
        quantity = equity / entry_fill
        position = {
            "row_id": int(row.row_id), "decision_at": decision_at,
            "direction": signal, "entry_time": entry_time,
            "entry_raw_price": raw_entry, "entry_fill_price": entry_fill,
            "quantity": quantity, "entry_fee": quantity * entry_fill * fee_per_side,
        }

    if position is not None:
        # Stage boundaries are information barriers. Do not read the next fold
        # merely to settle a position opened near the end of this fold.
        incomplete_open_position_count = 1
        position = None

    trades = pd.DataFrame(rows)
    equity_frame = pd.DataFrame(curve)
    if trades.empty:
        raw = np.array([], dtype=np.float64)
        net = np.array([], dtype=np.float64)
        long_count = short_count = 0
    else:
        raw = trades["gross_return"].to_numpy(dtype=np.float64)
        net = trades["net_return"].to_numpy(dtype=np.float64)
        long_count = int((trades["direction"] == "LONG").sum())
        short_count = int((trades["direction"] == "SHORT").sum())
    gross_return = (_ending(raw, 0.0) - 100.0) if len(raw) else 0.0
    stage_minutes = max((frame.iloc[-1]["decision_at"] - frame.iloc[0]["decision_at"]).total_seconds() / 60.0 + 15.0, 1.0)
    metrics = {
        **candidate,
        "trade_count": int(len(trades)), "long_count": long_count, "short_count": short_count,
        "exposure_percent": exposure_minutes / stage_minutes * 100.0,
        "gross_return_percent": gross_return,
        "net_return_percent": (equity / starting_equity - 1.0) * 100.0,
        "arithmetic_net_expectancy_bps_per_trade": float(net.mean() * 10000.0) if len(net) else 0.0,
        "median_net_return_bps_per_trade": float(np.median(net) * 10000.0) if len(net) else 0.0,
        "profit_factor": _profit_factor(net),
        "win_rate": float((net > 0).mean()) if len(net) else 0.0,
        "max_drawdown_percent": max_dd,
        "break_even_round_trip_cost_bps": break_even_cost_bps(raw),
        "ending_equity": equity, "minimum_equity_usdt": min_equity,
        "account_ruined": "YES" if equity <= 0 else "NO",
        "invalid_gap_fill_count": invalid_gap_count,
        "incomplete_open_position_count": incomplete_open_position_count,
        "overlapping_position_count": 0, "averaging_count": 0,
    }
    return PolicyResult(trades, equity_frame, metrics)


def discovery_eligible(m: dict[str, Any]) -> bool:
    return bool(m["trade_count"] >= 50 and m["gross_return_percent"] > 0 and m["net_return_percent"] > 0 and m["arithmetic_net_expectancy_bps_per_trade"] > 0 and m["profit_factor"] > 1.0 and m["break_even_round_trip_cost_bps"] >= 15 and m["account_ruined"] == "NO" and m["invalid_gap_fill_count"] == 0)


def validation_eligible(m: dict[str, Any]) -> bool:
    return bool(m["trade_count"] >= 30 and m["gross_return_percent"] > 0 and m["net_return_percent"] > 0 and m["arithmetic_net_expectancy_bps_per_trade"] > 0 and m["profit_factor"] > 1.0 and m["break_even_round_trip_cost_bps"] >= 13 and m["account_ruined"] == "NO" and m["invalid_gap_fill_count"] == 0)
