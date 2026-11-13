from __future__ import annotations

import ast
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import INITIAL_CAPITAL
from .event_backtest import _load_minute_hour_features


ACTION_NAMES = (
    "HOLD",
    "OPEN_HEDGE",
    "CLOSE_HEDGE",
    "AVERAGE_PRIMARY",
    "REDUCE_POSITION",
    "EXIT",
)


def _parse_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = ast.literal_eval(value)
    except (ValueError, SyntaxError):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


def _distribution(values: pd.Series) -> dict[str, float | int | None]:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "p10": None,
            "p90": None,
            "min": None,
            "max": None,
        }
    return {
        "count": int(len(numeric)),
        "mean": float(numeric.mean()),
        "median": float(numeric.median()),
        "p10": float(np.percentile(numeric, 10)),
        "p90": float(np.percentile(numeric, 90)),
        "min": float(numeric.min()),
        "max": float(numeric.max()),
    }


def _counter(series: pd.Series) -> dict[str, int]:
    if series.empty:
        return {}
    return {
        str(key): int(value)
        for key, value in series.fillna("UNKNOWN").value_counts().items()
    }


def _read_run(root: Path, prefix: str) -> dict[str, Any]:
    trades = pd.read_csv(root / f"{prefix}_trades.csv")
    orders = pd.read_csv(root / f"{prefix}_order_trace.csv")
    actions = pd.read_csv(
        root / f"{prefix}_action_trace.csv",
        usecols=[
            "decision_time",
            "catboost_action",
            "catboost_probabilities",
            "hard_risk_reason",
            "applied_action",
            "selection_source",
            "execution_time",
            "execution_price",
            "state_at_decision",
            "state_before_execution",
            "state_after_execution",
            "orders",
            "order_reasons",
        ],
    )
    equity = pd.read_parquet(root / f"{prefix}_equity.parquet")
    for frame, columns in (
        (trades, ("entry_time", "exit_time")),
        (orders, ("time",)),
        (actions, ("decision_time", "execution_time")),
        (equity, ("time",)),
    ):
        for column in columns:
            if column in frame:
                frame[column] = pd.to_datetime(
                    frame[column],
                    utc=True,
                    errors="coerce",
                )
    return {
        "prefix": prefix,
        "trades": trades,
        "orders": orders,
        "actions": actions,
        "equity": equity,
    }


def _price_map(minute_path: Path) -> pd.DataFrame:
    hourly = _load_minute_hour_features(minute_path)
    return hourly.set_index("hour").sort_index()


def _reference_prices(
    timestamps: pd.Series,
    prices: pd.DataFrame,
) -> tuple[pd.Series, pd.Series]:
    hours = pd.to_datetime(timestamps, utc=True).dt.floor("h")
    futures_open = prices["futures_open"].reindex(hours).to_numpy()
    spot_open = prices["spot_open"].reindex(hours).to_numpy()
    return (
        pd.Series(futures_open, index=timestamps.index, dtype=float),
        pd.Series(spot_open, index=timestamps.index, dtype=float),
    )


def _slippage_by_role(
    orders: pd.DataFrame,
    prices: pd.DataFrame,
) -> dict[str, float]:
    executed = orders.loc[orders["executed"] == 1].copy()
    if executed.empty:
        return {}
    futures_ref, spot_ref = _reference_prices(executed["time"], prices)
    fill = pd.to_numeric(executed["notional"], errors="coerce") / pd.to_numeric(
        executed["quantity"],
        errors="coerce",
    ).replace(0, np.nan)
    reference = futures_ref.where(executed["role"] != "SPOT", spot_ref)
    slippage = (fill - reference).abs() * pd.to_numeric(
        executed["quantity"],
        errors="coerce",
    )
    result = (
        pd.DataFrame({"role": executed["role"], "slippage": slippage})
        .groupby("role")["slippage"]
        .sum()
        .to_dict()
    )
    return {str(role): float(value) for role, value in result.items()}


def _action_state_probabilities(row: pd.Series) -> dict[str, float]:
    parsed = _parse_dict(row.get("catboost_probabilities"))
    return {
        str(key): float(value)
        for key, value in parsed.items()
        if isinstance(value, (int, float))
    }


def _position_pnl(
    state: dict[str, Any],
    role: str,
    mark: float,
) -> float:
    position = state.get(role)
    if not isinstance(position, dict):
        return 0.0
    side = int(position.get("side", 0))
    quantity = float(position.get("quantity", 0.0))
    entry = float(position.get("average_entry", 0.0))
    return side * quantity * (float(mark) - entry)


def _position_value(
    state: dict[str, Any],
    role: str,
    key: str,
    default: float = 0.0,
) -> float:
    position = state.get(role)
    if not isinstance(position, dict):
        return default
    value = position.get(key, default)
    return float(value) if value is not None else default


def _match_primary_trade(
    primary_trades: pd.DataFrame,
    entry_time: pd.Timestamp,
) -> pd.Series | None:
    candidates = primary_trades.loc[
        (primary_trades["entry_time"] <= entry_time)
        & (primary_trades["exit_time"] >= entry_time)
    ]
    if candidates.empty:
        return None
    return candidates.sort_values("entry_time").iloc[-1]


def _hedge_cycles(
    run: dict[str, Any],
    prices: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    trades = run["trades"]
    orders = run["orders"]
    actions = run["actions"]
    primary_trades = trades.loc[trades["role"] == "PRIMARY"].copy()
    hedge_trades = trades.loc[trades["role"] == "HEDGE"].copy()
    action_by_execution = {
        row["execution_time"]: row
        for _, row in actions.dropna(subset=["execution_time"]).iterrows()
    }
    rows: list[dict[str, Any]] = []
    for _, hedge in hedge_trades.sort_values("entry_time").iterrows():
        entry_time = pd.Timestamp(hedge["entry_time"])
        exit_time = pd.Timestamp(hedge["exit_time"])
        primary = _match_primary_trade(primary_trades, entry_time)
        open_action = action_by_execution.get(entry_time)
        close_action = action_by_execution.get(exit_time)
        if primary is None or open_action is None or close_action is None:
            continue
        before_open = _parse_dict(open_action.get("state_before_execution"))
        after_open = _parse_dict(open_action.get("state_after_execution"))
        before_close = _parse_dict(close_action.get("state_before_execution"))
        entry_mark = float(open_action.get("execution_price"))
        exit_mark = float(close_action.get("execution_price"))
        primary_pnl_open = _position_pnl(before_open, "primary", entry_mark)
        primary_pnl_close = _position_pnl(before_close, "primary", exit_mark)
        primary_pnl_change = primary_pnl_close - primary_pnl_open
        hedge_gross = float(hedge["gross_pnl"])
        hedge_net = float(hedge["net_pnl"])
        hedge_entry_fee = float(hedge["entry_fees"])
        hedge_exit_fee = float(hedge["exit_fee"])
        hedge_funding = float(hedge["funding_cost"])
        adverse_primary = max(0.0, -primary_pnl_change)
        probabilities = _action_state_probabilities(open_action)
        ranked = sorted(
            probabilities.items(),
            key=lambda item: item[1],
            reverse=True,
        )
        hedge_rank = next(
            (
                index
                for index, (action, _) in enumerate(ranked, start=1)
                if action == "OPEN_HEDGE"
            ),
            None,
        )
        rows.append(
            {
                "portfolio": run["prefix"],
                "primary_entry_time": primary["entry_time"],
                "primary_side": primary["side"],
                "primary_average_entry": float(primary["average_entry"]),
                "primary_margin": float(primary["margin"]),
                "primary_quantity": float(primary["quantity"]),
                "hedge_entry_time": entry_time,
                "hedge_exit_time": exit_time,
                "hedge_side": hedge["side"],
                "hedge_entry_mark": entry_mark,
                "hedge_exit_mark": exit_mark,
                "hedge_open_reason": "CATBOOST_MANAGEMENT_ARGMAX",
                "hedge_open_probability": probabilities.get("OPEN_HEDGE"),
                "hedge_probability_rank": hedge_rank,
                "catboost_selected_action": open_action.get("catboost_action"),
                "selection_source": open_action.get("selection_source"),
                "hedge_margin": float(hedge["margin"]),
                "hedge_quantity": float(hedge["quantity"]),
                "primary_pnl_at_hedge_open": primary_pnl_open,
                "primary_pnl_at_hedge_close": primary_pnl_close,
                "primary_pnl_change_during_hedge": primary_pnl_change,
                "adverse_primary_pnl_during_hedge": adverse_primary,
                "hedge_gross_pnl": hedge_gross,
                "hedge_net_pnl": hedge_net,
                "hedge_entry_fees": hedge_entry_fee,
                "hedge_exit_fee": hedge_exit_fee,
                "hedge_funding": hedge_funding,
                "primary_cycle_entry_fees": float(primary["entry_fees"]),
                "primary_cycle_exit_fee": float(primary["exit_fee"]),
                "primary_cycle_funding": float(primary["funding_cost"]),
                "hedge_holding_hours": float(
                    (exit_time - entry_time).total_seconds() / 3600.0
                ),
                "primary_liquidation_distance_before": _position_value(
                    before_open,
                    "primary",
                    "liquidation_distance_pct",
                ),
                "primary_liquidation_distance_after": _position_value(
                    after_open,
                    "primary",
                    "liquidation_distance_pct",
                ),
                "gross_exposure_before": float(
                    before_open.get("gross_notional", 0.0)
                ),
                "gross_exposure_after": float(
                    after_open.get("gross_notional", 0.0)
                ),
                "net_exposure_before": float(
                    before_open.get("net_notional", 0.0)
                ),
                "net_exposure_after": float(
                    after_open.get("net_notional", 0.0)
                ),
                "primary_cycle_net_pnl": float(primary["net_pnl"]),
                "primary_plus_hedge_cycle_net_pnl": (
                    float(primary["net_pnl"]) + hedge_net
                ),
                "paired_hedged_interval_net_pnl": (
                    primary_pnl_change + hedge_net
                ),
                "paired_unhedged_interval_net_pnl": primary_pnl_change,
                "paired_hedge_delta": hedge_net,
                "hedge_compensation_fraction": (
                    max(0.0, hedge_gross) / adverse_primary
                    if adverse_primary > 0
                    else None
                ),
                "hedge_helped_interval": int(hedge_net > 0),
                "hedge_positive_gross_negative_net": int(
                    hedge_gross > 0 and hedge_net <= 0
                ),
            }
        )
    frame = pd.DataFrame(rows)
    overlap_pairs = 0
    if len(frame):
        for _, group in frame.groupby(["portfolio", "primary_entry_time"]):
            ordered = group.sort_values("hedge_entry_time").reset_index(drop=True)
            for left in range(len(ordered)):
                for right in range(left + 1, len(ordered)):
                    if (
                        ordered.loc[right, "hedge_entry_time"]
                        < ordered.loc[left, "hedge_exit_time"]
                    ):
                        overlap_pairs += 1
    summary = {
        "count": int(len(frame)),
        "hedge_gross_pnl": float(frame["hedge_gross_pnl"].sum()) if len(frame) else 0.0,
        "hedge_net_pnl": float(frame["hedge_net_pnl"].sum()) if len(frame) else 0.0,
        "hedge_fees": (
            float(
                (
                    frame["hedge_entry_fees"]
                    + frame["hedge_exit_fee"]
                ).sum()
            )
            if len(frame)
            else 0.0
        ),
        "hedge_funding": float(frame["hedge_funding"].sum()) if len(frame) else 0.0,
        "positive_net_count": int((frame["hedge_net_pnl"] > 0).sum()) if len(frame) else 0,
        "negative_net_count": int((frame["hedge_net_pnl"] < 0).sum()) if len(frame) else 0,
        "positive_gross_negative_net_count": (
            int(frame["hedge_positive_gross_negative_net"].sum())
            if len(frame)
            else 0
        ),
        "helped_interval_count": (
            int(frame["hedge_helped_interval"].sum()) if len(frame)
            else 0
        ),
        "paired_hedge_delta_sum": (
            float(frame["paired_hedge_delta"].sum()) if len(frame) else 0.0
        ),
        "holding_hours": _distribution(
            frame["hedge_holding_hours"] if len(frame) else pd.Series(dtype=float)
        ),
        "open_probability_rank": _counter(
            frame["hedge_probability_rank"].astype(str)
            if len(frame)
            else pd.Series(dtype=str)
        ),
        "unique_primary_cycles": (
            int(
                frame[["portfolio", "primary_entry_time"]]
                .drop_duplicates()
                .shape[0]
            )
            if len(frame)
            else 0
        ),
        "hedges_per_primary_cycle": _counter(
            frame.groupby(["portfolio", "primary_entry_time"])
            .size()
            .astype(str)
            if len(frame)
            else pd.Series(dtype=str)
        ),
        "overlapping_hedge_interval_pairs": overlap_pairs,
        "paired_independence": (
            "INDEPENDENT" if overlap_pairs == 0 else "OVERLAPPING_CYCLES"
        ),
        "critical_missing_values": {
            column: int(frame[column].isna().sum())
            for column in (
                "primary_entry_time",
                "primary_side",
                "hedge_entry_time",
                "hedge_exit_time",
                "hedge_gross_pnl",
                "hedge_net_pnl",
                "primary_pnl_at_hedge_open",
                "primary_pnl_at_hedge_close",
            )
        }
        if len(frame)
        else {},
        "by_portfolio": {
            str(portfolio): {
                "count": int(len(group)),
                "gross_pnl": float(group["hedge_gross_pnl"].sum()),
                "net_pnl": float(group["hedge_net_pnl"].sum()),
                "positive_net": int((group["hedge_net_pnl"] > 0).sum()),
                "negative_net": int((group["hedge_net_pnl"] < 0).sum()),
            }
            for portfolio, group in frame.groupby("portfolio")
        }
        if len(frame)
        else {},
    }
    return frame, summary


def _attribution(
    run: dict[str, Any],
    prices: pd.DataFrame,
    reported_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    trades = run["trades"]
    orders = run["orders"]
    equity = run["equity"]
    spot_fraction = 0.6 if run["prefix"].endswith("_60") else 0.4
    initial_spot = INITIAL_CAPITAL * spot_fraction
    initial_futures = INITIAL_CAPITAL - initial_spot
    final_spot = float(equity.iloc[-1]["spot_equity"])
    final_futures = float(equity.iloc[-1]["futures_equity"])
    final_equity = float(equity.iloc[-1]["equity"])
    spot_net = final_spot - initial_spot
    role_trades = {
        role: trades.loc[trades["role"] == role]
        for role in ("PRIMARY", "HEDGE")
    }
    fees_by_role = {
        str(role): float(value)
        for role, value in (
            orders.loc[orders["executed"] == 1]
            .groupby("role")["fee"]
            .sum()
            .to_dict()
            .items()
        )
    }
    slippage_by_role = _slippage_by_role(orders, prices)
    executed_spot_notional = float(
        orders.loc[
            (orders["executed"] == 1) & (orders["role"] == "SPOT"),
            "notional",
        ].sum()
    )
    if slippage_by_role.get("SPOT", 0.0) == 0.0 and executed_spot_notional > 0:
        slippage_by_role["SPOT"] = executed_spot_notional * 0.0002
    estimated_slippage_total = sum(slippage_by_role.values())
    reported_slippage_total = (
        float(reported_metrics["slippage"])
        if reported_metrics is not None
        else estimated_slippage_total
    )
    slippage_residual = reported_slippage_total - estimated_slippage_total
    if abs(slippage_residual) > 1e-12 and estimated_slippage_total > 0:
        for role, estimate in list(slippage_by_role.items()):
            slippage_by_role[role] = (
                estimate
                + slippage_residual * estimate / estimated_slippage_total
            )
    isolated_deficit = float(
        pd.to_numeric(
            trades.get(
                "isolated_deficit",
                pd.Series(0.0, index=trades.index),
            ),
            errors="coerce",
        ).fillna(0.0).sum()
    )
    attribution: dict[str, Any] = {
        "final_equity": final_equity,
        "spot_net_pnl": spot_net,
        "spot_fees": fees_by_role.get("SPOT", 0.0),
        "spot_slippage": slippage_by_role.get("SPOT", 0.0),
        "reported_total_slippage": reported_slippage_total,
        "estimated_role_slippage_total": estimated_slippage_total,
        "spot_gross_pnl": (
            spot_net
            + fees_by_role.get("SPOT", 0.0)
            + slippage_by_role.get("SPOT", 0.0)
        ),
        "primary_gross_pnl_fill": float(role_trades["PRIMARY"]["gross_pnl"].sum()),
        "primary_fees": sum(
            float(value)
            for value in (
                role_trades["PRIMARY"]["entry_fees"]
                + role_trades["PRIMARY"]["exit_fee"]
            )
        ),
        "primary_funding": float(role_trades["PRIMARY"]["funding_cost"].sum()),
        "primary_slippage": slippage_by_role.get("PRIMARY", 0.0),
        "primary_net_pnl": float(role_trades["PRIMARY"]["net_pnl"].sum()),
        "hedge_gross_pnl_fill": float(role_trades["HEDGE"]["gross_pnl"].sum()),
        "hedge_fees": sum(
            float(value)
            for value in (
                role_trades["HEDGE"]["entry_fees"]
                + role_trades["HEDGE"]["exit_fee"]
            )
        ),
        "hedge_funding": float(role_trades["HEDGE"]["funding_cost"].sum()),
        "hedge_slippage": slippage_by_role.get("HEDGE", 0.0),
        "hedge_net_pnl": float(role_trades["HEDGE"]["net_pnl"].sum()),
        "isolated_deficit_credit": isolated_deficit,
        "liquidation_net_loss": float(
            (
                role_trades["PRIMARY"].loc[
                    role_trades["PRIMARY"]["reason"] == "LIQUIDATED",
                    "net_pnl",
                ].sum()
                + role_trades["PRIMARY"].loc[
                    role_trades["PRIMARY"]["reason"] == "LIQUIDATED",
                    "isolated_deficit",
                ].sum()
            )
            + (
                role_trades["HEDGE"].loc[
                    role_trades["HEDGE"]["reason"] == "LIQUIDATED",
                    "net_pnl",
                ].sum()
                + role_trades["HEDGE"].loc[
                    role_trades["HEDGE"]["reason"] == "LIQUIDATED",
                    "isolated_deficit",
                ].sum()
            )
        ),
        "futures_net_pnl": final_futures - initial_futures,
    }
    attribution["primary_gross_pnl_reference"] = (
        attribution["primary_gross_pnl_fill"]
        + attribution["primary_slippage"]
    )
    attribution["hedge_gross_pnl_reference"] = (
        attribution["hedge_gross_pnl_fill"]
        + attribution["hedge_slippage"]
    )
    attribution["primary_recomputed_net"] = (
        attribution["primary_gross_pnl_reference"]
        - attribution["primary_slippage"]
        - attribution["primary_fees"]
        - attribution["primary_funding"]
    )
    attribution["hedge_recomputed_net"] = (
        attribution["hedge_gross_pnl_reference"]
        - attribution["hedge_slippage"]
        - attribution["hedge_fees"]
        - attribution["hedge_funding"]
    )
    attribution["accounting_sum"] = (
        INITIAL_CAPITAL
        + attribution["spot_net_pnl"]
        + attribution["primary_net_pnl"]
        + attribution["hedge_net_pnl"]
        + isolated_deficit
    )
    attribution["accounting_error"] = (
        attribution["accounting_sum"] - final_equity
    )
    return attribution


def _churn(
    run: dict[str, Any],
) -> dict[str, Any]:
    trades = run["trades"]
    primary = trades.loc[trades["role"] == "PRIMARY"].copy()
    primary["holding_hours"] = (
        primary["exit_time"] - primary["entry_time"]
    ).dt.total_seconds() / 3600.0
    primary = primary.sort_values("entry_time")
    primary["next_entry"] = primary["entry_time"].shift(-1)
    primary["reentry_hours"] = (
        primary["next_entry"] - primary["exit_time"]
    ).dt.total_seconds() / 3600.0
    primary["direction_flip"] = (
        primary["side"].ne(primary["side"].shift(1)) & primary.index.to_series().ne(primary.index[0])
    )
    actions = run["actions"]
    execution_actions = actions.dropna(subset=["execution_time"]).copy()
    exit_action = {
        row["execution_time"]: row
        for _, row in execution_actions.iterrows()
    }
    exit_sources: Counter[str] = Counter()
    risk_exit_reasons: Counter[str] = Counter()
    for _, trade in primary.iterrows():
        action = exit_action.get(pd.Timestamp(trade["exit_time"]))
        if action is None:
            continue
        if action.get("catboost_action") == "RISK_EXIT":
            exit_sources["RISK_ENGINE"] += 1
            risk_exit_reasons[
                str(action.get("hard_risk_reason") or "UNKNOWN")
            ] += 1
        elif action.get("catboost_action") == "EXIT":
            exit_sources["CATBOOST_MANAGEMENT"] += 1
        else:
            exit_sources[str(action.get("selection_source"))] += 1
    catboost_exit_probabilities = []
    for _, action in execution_actions.iterrows():
        if action.get("catboost_action") != "EXIT":
            continue
        probabilities = _action_state_probabilities(action)
        if "EXIT" in probabilities:
            catboost_exit_probabilities.append(probabilities["EXIT"])
    hold_mapped_skip = int(
        (
            (execution_actions["catboost_action"] == "HOLD")
            & (execution_actions["applied_action"] == "SKIP")
        ).sum()
    )
    orders = run["orders"]
    executed = orders.loc[orders["executed"] == 1].copy()
    executed["day"] = executed["time"].dt.floor("D")
    daily_turnover = executed.groupby("day")["notional"].sum()
    cycle_turnover = (
        pd.to_numeric(primary["average_entry"], errors="coerce")
        * pd.to_numeric(primary["quantity"], errors="coerce")
        + pd.to_numeric(primary["exit_fill"], errors="coerce")
        * pd.to_numeric(primary["quantity"], errors="coerce")
    )
    short_cycle_mask = primary["holding_hours"] <= 1.0
    gross_positive = primary["gross_pnl"] > 0
    net_positive = primary["net_pnl"] > 0
    return {
        "trades": int(len(primary)),
        "holding_hours": _distribution(primary["holding_hours"]),
        "ai_exit_count": int((primary["reason"] == "AI_EXIT").sum()),
        "liquidations": int((primary["reason"] == "LIQUIDATED").sum()),
        "reentry_within_1h": int((primary["reentry_hours"] <= 1.0).sum()),
        "reentry_within_2h": int((primary["reentry_hours"] <= 2.0).sum()),
        "direction_flips": int(primary["direction_flip"].sum()),
        "profitable_before_costs": int(gross_positive.sum()),
        "profitable_after_costs": int(net_positive.sum()),
        "profitable_before_but_not_after": int(
            (gross_positive & ~net_positive).sum()
        ),
        "gross_pnl": _distribution(primary["gross_pnl"]),
        "net_pnl": _distribution(primary["net_pnl"]),
        "fees_per_cycle": _distribution(
            primary["entry_fees"] + primary["exit_fee"]
        ),
        "margin": _distribution(primary["margin"]),
        "daily_turnover": _distribution(daily_turnover),
        "short_cycle_count": int(short_cycle_mask.sum()),
        "short_cycle_turnover": float(cycle_turnover.loc[short_cycle_mask].sum()),
        "short_cycle_turnover_share": (
            float(cycle_turnover.loc[short_cycle_mask].sum() / cycle_turnover.sum())
            if cycle_turnover.sum() > 0
            else 0.0
        ),
        "exit_sources": dict(exit_sources),
        "risk_exit_reasons": dict(risk_exit_reasons),
        "catboost_exit_probability": _distribution(
            pd.Series(catboost_exit_probabilities)
        ),
        "hold_mapped_to_skip_count": hold_mapped_skip,
        "operation_counts": (
            {
                f"{role}:{action}": int(count)
                for (role, action), count in executed.groupby(
                    ["role", "action"]
                ).size().items()
            }
            if not executed.empty
            else {}
        ),
    }


def _run2_hedge_diagnosis(
    run: dict[str, Any],
) -> dict[str, Any]:
    actions = run["actions"]
    rows: list[dict[str, Any]] = []
    for _, action in actions.iterrows():
        probabilities = _action_state_probabilities(action)
        if not probabilities:
            continue
        state = _parse_dict(action.get("state_at_decision"))
        if not isinstance(state.get("primary"), dict):
            continue
        ranked = sorted(
            probabilities.items(),
            key=lambda item: item[1],
            reverse=True,
        )
        rank = next(
            (
                index
                for index, (name, _) in enumerate(ranked, start=1)
                if name == "OPEN_HEDGE"
            ),
            None,
        )
        rows.append(
            {
                "winner": ranked[0][0],
                "runner_up": ranked[1][0] if len(ranked) > 1 else None,
                "open_hedge_probability": probabilities.get("OPEN_HEDGE", 0.0),
                "open_hedge_rank": rank,
                "winner_probability": ranked[0][1],
                "primary_unrealized": (
                    _position_value(state, "primary", "unrealized_pnl")
                ),
                "free_collateral": float(state.get("free_collateral", 0.0)),
                "applied_action": action.get("applied_action"),
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return {
            "management_states": 0,
            "open_hedge_signal_count": 0,
        }
    return {
        "management_states": int(len(frame)),
        "open_hedge_signal_count": int((frame["open_hedge_rank"] == 1).sum()),
        "open_hedge_rank_counts": _counter(
            frame["open_hedge_rank"].astype(str)
        ),
        "winner_counts": _counter(frame["winner"]),
        "runner_up_counts": _counter(frame["runner_up"]),
        "open_hedge_probability": _distribution(frame["open_hedge_probability"]),
        "winner_probability": _distribution(frame["winner_probability"]),
        "winner_when_hedge_rank_2": _counter(
            frame.loc[frame["open_hedge_rank"] == 2, "winner"]
        ),
        "winner_when_hedge_rank_3": _counter(
            frame.loc[frame["open_hedge_rank"] == 3, "winner"]
        ),
        "states_with_free_margin": int((frame["free_collateral"] > 0).sum()),
        "states_primary_adverse": int((frame["primary_unrealized"] < 0).sum()),
        "hedge_probability_by_applied_action": {
            str(action): _distribution(group["open_hedge_probability"])
            for action, group in frame.groupby("applied_action")
        },
    }


def _training_labels(path: Path) -> dict[str, Any]:
    frame = pd.read_parquet(path)
    result: dict[str, Any] = {
        "rows": int(len(frame)),
        "columns": list(frame.columns),
    }
    if "best_action" in frame:
        result["best_action_counts"] = _counter(frame["best_action"])
        if "allowed_OPEN_HEDGE" in frame:
            result["allowed_OPEN_HEDGE"] = int(
                frame["allowed_OPEN_HEDGE"].fillna(False).astype(bool).sum()
            )
        if "allowed_CLOSE_HEDGE" in frame:
            result["allowed_CLOSE_HEDGE"] = int(
                frame["allowed_CLOSE_HEDGE"].fillna(False).astype(bool).sum()
            )
        utility_columns = [
            column
            for column in frame.columns
            if column.startswith("utility_")
        ]
        open_rows = frame.loc[frame["best_action"] == "OPEN_HEDGE"]
        if len(open_rows) and utility_columns:
            utilities = open_rows[utility_columns].apply(
                pd.to_numeric,
                errors="coerce",
            )
            top = utilities.max(axis=1)
            second = utilities.apply(
                lambda row: row.nlargest(2).iloc[-1],
                axis=1,
            )
            gap = top - second
            result["open_hedge_utility_gap"] = _distribution(gap)
            result["open_hedge_gap_le_0_05"] = int((gap <= 0.05).sum())
            result["open_hedge_gap_le_0_05_fraction"] = float(
                (gap <= 0.05).mean()
            )
        if "split" in frame:
            result["best_action_by_split"] = {
                str(split): _counter(group["best_action"])
                for split, group in frame.groupby("split")
            }
    return result


def analyze_attribution(
    *,
    hedged_root: Path,
    unhedged_root: Path,
    minute_path: Path,
    output_root: Path,
    management_samples_path: Path | None = None,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    prices = _price_map(minute_path)
    hedged_summary = json.loads(
        (hedged_root / "event_policy_summary_v1.json").read_text(encoding="utf-8")
    )
    unhedged_summary = json.loads(
        (unhedged_root / "event_policy_summary_v1.json").read_text(encoding="utf-8")
    )
    prefixes = ("RUN1_60", "RUN1_40", "RUN2_60", "RUN2_40")
    hedged_runs = {
        prefix: _read_run(hedged_root, prefix)
        for prefix in prefixes
    }
    unhedged_runs = {
        prefix: _read_run(unhedged_root, prefix)
        for prefix in prefixes
    }
    hedged_metrics = {
        (item["split"], float(item["spot_fraction"])): item
        for item in hedged_summary["metrics"]
    }
    unhedged_metrics = {
        (item["split"], float(item["spot_fraction"])): item
        for item in unhedged_summary["metrics"]
    }
    hedge_frames = []
    attributions: dict[str, Any] = {}
    churn: dict[str, Any] = {}
    for prefix in prefixes:
        split, spot = prefix.split("_")
        key = (split, float(f"0.{spot}"))
        hedges, hedge_summary = _hedge_cycles(hedged_runs[prefix], prices)
        hedge_frames.append(hedges)
        attributions[prefix] = {
            "hedged": _attribution(
                hedged_runs[prefix],
                prices,
                hedged_metrics[key],
            ),
            "unhedged": _attribution(
                unhedged_runs[prefix],
                prices,
                unhedged_metrics[key],
            ),
            "hedge_cycles": hedge_summary,
        }
        churn[prefix] = {
            "hedged": _churn(hedged_runs[prefix]),
            "unhedged": _churn(unhedged_runs[prefix]),
        }
    hedge_frame = pd.concat(hedge_frames, ignore_index=True)
    hedge_frame.to_csv(output_root / "hedge_cycles_v1.csv", index=False)
    comparison = {}
    for prefix in prefixes:
        split, spot = prefix.split("_")
        key = (split, float(f"0.{spot}"))
        hedged = attributions[prefix]["hedged"]
        unhedged = attributions[prefix]["unhedged"]
        hedged_metric = hedged_metrics[key]
        unhedged_metric = unhedged_metrics[key]
        comparison[prefix] = {
            "hedged_equity": hedged["final_equity"],
            "unhedged_equity": unhedged["final_equity"],
            "hedge_effect": hedged["final_equity"] - unhedged["final_equity"],
            "hedged_max_drawdown": float(hedged_metric["max_drawdown"]),
            "unhedged_max_drawdown": float(unhedged_metric["max_drawdown"]),
            "drawdown_effect": float(
                hedged_metric["max_drawdown"]
                - unhedged_metric["max_drawdown"]
            ),
            "hedged_liquidations": int(hedged_metric["liquidations"]),
            "unhedged_liquidations": int(unhedged_metric["liquidations"]),
            "liquidations_prevented": max(
                0,
                int(unhedged_metric["liquidations"])
                - int(hedged_metric["liquidations"]),
            ),
            "hedged_min_equity": float(
                hedged_runs[prefix]["equity"]["equity"].min()
            ),
            "unhedged_min_equity": float(
                unhedged_runs[prefix]["equity"]["equity"].min()
            ),
            "hedged_account_ruined": bool(
                hedged_runs[prefix]["equity"]["equity"].min() <= 0
            ),
            "unhedged_account_ruined": bool(
                unhedged_runs[prefix]["equity"]["equity"].min() <= 0
            ),
        }
    cost_sensitivity = {}
    for prefix in prefixes:
        for mode in ("hedged", "unhedged"):
            attribution = attributions[prefix][mode]
            costs = (
                attribution["spot_fees"]
                + attribution["spot_slippage"]
                + attribution["primary_fees"]
                + attribution["primary_slippage"]
                + attribution["hedge_fees"]
                + attribution["hedge_slippage"]
            )
            cost_sensitivity[f"{prefix}:{mode}"] = {
                "actual_final_equity": attribution["final_equity"],
                "fees_plus_slippage": costs,
                "zero_cost_accounting_counterfactual": (
                    attribution["final_equity"] + costs
                ),
                "double_cost_accounting_counterfactual": (
                    attribution["final_equity"] - costs
                ),
                "note": "Accounting sensitivity only; trading path is not rerun.",
            }
    result = {
        "hedged_root": str(hedged_root.resolve()),
        "unhedged_root": str(unhedged_root.resolve()),
        "attribution_totals": {
            mode: {
                key: float(
                    sum(
                        attributions[prefix][mode][key]
                        for prefix in prefixes
                    )
                )
                for key in (
                    "spot_net_pnl",
                    "spot_gross_pnl",
                    "spot_fees",
                    "spot_slippage",
                    "primary_gross_pnl_reference",
                    "primary_slippage",
                    "primary_fees",
                    "primary_funding",
                    "primary_net_pnl",
                    "hedge_gross_pnl_reference",
                    "hedge_slippage",
                    "hedge_fees",
                    "hedge_funding",
                    "hedge_net_pnl",
                    "isolated_deficit_credit",
                    "liquidation_net_loss",
                    "futures_net_pnl",
                    "final_equity",
                )
            }
            for mode in ("hedged", "unhedged")
        },
        "hedge_count": int(len(hedge_frame)),
        "hedge_effect_comparison": comparison,
        "total_hedge_effect": float(
            sum(item["hedge_effect"] for item in comparison.values())
        ),
        "liquidations_prevented": int(
            sum(item["liquidations_prevented"] for item in comparison.values())
        ),
        "hedge_cycles": {
            "count": int(len(hedge_frame)),
            "gross_pnl": float(hedge_frame["hedge_gross_pnl"].sum()),
            "net_pnl": float(hedge_frame["hedge_net_pnl"].sum()),
            "entry_fees": float(hedge_frame["hedge_entry_fees"].sum()),
            "exit_fees": float(hedge_frame["hedge_exit_fee"].sum()),
            "funding": float(hedge_frame["hedge_funding"].sum()),
            "positive_net": int((hedge_frame["hedge_net_pnl"] > 0).sum()),
            "negative_net": int((hedge_frame["hedge_net_pnl"] < 0).sum()),
            "zero_net": int((hedge_frame["hedge_net_pnl"] == 0).sum()),
            "positive_gross_negative_net": int(
                hedge_frame["hedge_positive_gross_negative_net"].sum()
            ),
            "helped_interval": int(hedge_frame["hedge_helped_interval"].sum()),
            "primary_pnl_change_during_hedges": float(
                hedge_frame["primary_pnl_change_during_hedge"].sum()
            ),
            "paired_hedged_interval_net_pnl": float(
                hedge_frame["paired_hedged_interval_net_pnl"].sum()
            ),
            "paired_unhedged_interval_net_pnl": float(
                hedge_frame["paired_unhedged_interval_net_pnl"].sum()
            ),
            "gross_pnl_distribution": _distribution(
                hedge_frame["hedge_gross_pnl"]
            ),
            "net_pnl_distribution": _distribution(
                hedge_frame["hedge_net_pnl"]
            ),
            "largest_positive_net_pnl": float(
                hedge_frame["hedge_net_pnl"].max()
            ),
            "net_pnl_excluding_largest": float(
                hedge_frame["hedge_net_pnl"].sum()
                - hedge_frame["hedge_net_pnl"].max()
            ),
            "top_3_positive_share": (
                float(
                    hedge_frame["hedge_net_pnl"]
                    .nlargest(3)
                    .sum()
                    / hedge_frame.loc[
                        hedge_frame["hedge_net_pnl"] > 0,
                        "hedge_net_pnl",
                    ].sum()
                )
                if (
                    hedge_frame["hedge_net_pnl"] > 0
                ).any()
                else None
            ),
            "holding_hours": _distribution(hedge_frame["hedge_holding_hours"]),
            "compensation_fraction": _distribution(
                hedge_frame["hedge_compensation_fraction"]
            ),
            "unique_primary_cycles": int(
                hedge_frame[["portfolio", "primary_entry_time"]]
                .drop_duplicates()
                .shape[0]
            ),
            "hedges_per_primary_cycle": _counter(
                hedge_frame.groupby(["portfolio", "primary_entry_time"])
                .size()
                .astype(str)
            ),
            "overlapping_hedge_interval_pairs": (
                attributions["RUN1_60"]["hedge_cycles"][
                    "overlapping_hedge_interval_pairs"
                ]
                + attributions["RUN1_40"]["hedge_cycles"][
                    "overlapping_hedge_interval_pairs"
                ]
            ),
            "paired_independence": (
                "NONOVERLAPPING_CYCLES;NOT_STATISTICALLY_INDEPENDENT"
            ),
            "critical_missing_values": {
                column: int(hedge_frame[column].isna().sum())
                for column in (
                    "primary_entry_time",
                    "primary_side",
                    "hedge_entry_time",
                    "hedge_exit_time",
                    "hedge_gross_pnl",
                    "hedge_net_pnl",
                    "primary_pnl_at_hedge_open",
                    "primary_pnl_at_hedge_close",
                )
            },
        },
        "run2_hedge_diagnosis": _run2_hedge_diagnosis(hedged_runs["RUN2_60"]),
        "attribution": attributions,
        "churn": churn,
        "cost_sensitivity": cost_sensitivity,
        "management_training_labels": (
            _training_labels(management_samples_path)
            if management_samples_path is not None
            else None
        ),
    }
    (output_root / "hedge_attribution_v1.json").write_text(
        json.dumps(result, indent=2, default=str),
        encoding="utf-8",
    )
    return result


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--hedged-root", type=Path, required=True)
    parser.add_argument("--unhedged-root", type=Path, required=True)
    parser.add_argument("--minute-path", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--management-samples", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            analyze_attribution(
                hedged_root=args.hedged_root,
                unhedged_root=args.unhedged_root,
                minute_path=args.minute_path,
                output_root=args.output_root,
                management_samples_path=args.management_samples,
            ),
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
