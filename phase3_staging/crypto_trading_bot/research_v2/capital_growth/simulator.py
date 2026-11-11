from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

import numpy as np
import pandas as pd

from .accounting import FuturesAccount, Position, SpotAccount, TransferLedger
from .config import PortfolioConfig
from .risk import maximum_margin_for_limit, risk_report


@dataclass
class SimulationResult:
    portfolio: str
    trades: pd.DataFrame
    events: pd.DataFrame
    equity: pd.DataFrame
    metrics: dict[str, Any]
    config: dict[str, Any]


def _pnl_at(position: Position, price: float) -> float:
    return position.side * position.quantity * (float(price) - position.average_entry)


def _max_drawdown(values: list[float]) -> float:
    if not values:
        return 0.0
    peak = values[0]
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak)
    return worst


def _equity(futures: FuturesAccount, spot: SpotAccount, mark: float) -> float:
    return float(spot.equity(mark) + futures.equity(mark))


def _affordable_margin(free_collateral: float, leverage: float, fee_rate: float) -> float:
    return max(0.0, float(free_collateral)) / ((1.0 + float(leverage) * float(fee_rate)) * (1.0 + 1e-12))


def _order_notional_capacity(signal: dict[str, Any], price: float, execution: Any) -> float:
    bar_liquidity = (
        max(0.0, float(signal.get("volume") or 0.0))
        * float(price)
        * float(execution.max_bar_participation_rate)
    )
    return max(0.0, min(float(execution.max_order_notional), bar_liquidity))


def simulate_portfolio(
    frame: pd.DataFrame,
    funding: pd.DataFrame,
    decisions: list[tuple[int, dict]],
    config: PortfolioConfig,
) -> SimulationResult:
    if frame.empty:
        raise ValueError("cannot simulate empty frame")
    required = {
        "open_time",
        "open",
        "high",
        "low",
        "close",
        "futures_open",
        "mark_high",
        "mark_low",
        "mark_close",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"missing simulator columns: {sorted(missing)}")

    first_price = float(frame.iloc[0]["futures_open"])
    spot_budget = config.initial_capital * config.spot_fraction
    futures_budget = config.initial_capital * (1.0 - config.spot_fraction)
    spot = SpotAccount(cash=spot_budget)
    futures = FuturesAccount(free_collateral=futures_budget)
    transfers = TransferLedger()
    exec_cfg = config.execution
    strategy = config.strategy

    trades: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = []
    state = "FLAT"
    thesis_direction = 0
    primary_opened_at: pd.Timestamp | None = None
    hedge_cycles = 0
    hedge_close_streak = 0
    next_average_level = 0
    cycle_number = 0
    cycle_peak_equity = config.initial_capital
    cycle_peak_futures_equity = futures_budget
    liquidated = 0
    risk_exits = 0
    emergency_closes = 0
    funding_by_minute = {
        pd.Timestamp(t).floor("min"): float(rate)
        for t, rate in zip(funding["funding_time"], funding["funding_rate"])
        if pd.notna(rate)
    }
    decision_by_index = dict(decisions)
    daily_close = (
        frame.set_index("open_time")["close"]
        .astype(float)
        .resample("1D")
        .last()
        .dropna()
    )

    if config.spot_mode == "HOLD":
        spot.buy_to_target(
            first_price,
            spot_budget,
            fee_rate=exec_cfg.taker_fee_per_side,
            slippage=exec_cfg.slippage_per_side,
        )

    def emit(time: pd.Timestamp, event: str, **data: Any) -> None:
        events.append({"time": pd.Timestamp(time).isoformat(), "event": event, "state": state, **data})

    def account_snapshot(time: pd.Timestamp, mark: float) -> dict[str, Any]:
        primary = futures.primary
        hedge = futures.hedge
        return {
            "time": time,
            "equity": _equity(futures, spot, mark),
            "state": state,
            "spot_cash": spot.cash,
            "spot_eth": spot.eth,
            "spot_equity": spot.equity(mark),
            "futures_free_collateral": futures.free_collateral,
            "futures_used_margin": futures.margin_used(),
            "primary_margin": primary.margin if primary is not None else 0.0,
            "hedge_margin": hedge.margin if hedge is not None else 0.0,
            "primary_unrealized": primary.unrealized(mark) if primary is not None else 0.0,
            "hedge_unrealized": hedge.unrealized(mark) if hedge is not None else 0.0,
            "transfers_spot_to_futures": transfers.spot_to_futures,
            "transfers_futures_to_spot": transfers.futures_to_spot,
        }

    def role_position(role: str) -> Position | None:
        return futures.primary if role == "PRIMARY" else futures.hedge

    def recovery_estimate(time: pd.Timestamp, direction: int) -> dict[str, Any]:
        history = daily_close[daily_close.index < time].tail(366)
        if len(history) < 40:
            return {
                "recovery_p50_hours": None,
                "recovery_p90_hours": None,
                "recovery_unresolved_rate": None,
                "recovery_sample_count": 0,
            }
        if direction > 0:
            reference = history.rolling(30, min_periods=10).max().shift(1)
            excursion = 1.0 - history / reference
            current_reference = float(history.tail(30).max())
            current_excursion = max(0.0, 1.0 - float(history.iloc[-1]) / current_reference)
            adverse = excursion >= max(0.05, current_excursion)
            recovered = history >= reference
        else:
            reference = history.rolling(30, min_periods=10).min().shift(1)
            excursion = history / reference - 1.0
            current_reference = float(history.tail(30).min())
            current_excursion = max(0.0, float(history.iloc[-1]) / current_reference - 1.0)
            adverse = excursion >= max(0.05, current_excursion)
            recovered = history <= reference
        starts = np.flatnonzero(adverse.fillna(False).to_numpy())
        durations: list[float] = []
        unresolved = 0
        for start in starts:
            found = None
            for index in range(start + 1, len(history)):
                if bool(recovered.iloc[index]):
                    found = index
                    break
            if found is None:
                unresolved += 1
            else:
                durations.append((found - start) * 24.0)
        return {
            "recovery_p50_hours": float(np.percentile(durations, 50)) if durations else None,
            "recovery_p90_hours": float(np.percentile(durations, 90)) if durations else None,
            "recovery_unresolved_rate": unresolved / len(starts) if len(starts) else 0.0,
            "recovery_sample_count": len(starts),
        }

    def close_role(time: pd.Timestamp, role: str, price: float, reason: str) -> bool:
        nonlocal state
        position = role_position(role)
        if position is None:
            return False
        row = futures.close_position(
            role,
            time=time,
            price=price,
            slippage=exec_cfg.slippage_per_side,
            fee_rate=exec_cfg.taker_fee_per_side,
            reason=reason,
        )
        trades.append(row)
        state = "HEDGE_CLOSED" if role == "HEDGE" and futures.primary is not None else "EXITED"
        emit(time, f"{role}_CLOSED", **row)
        return True

    def rebalance(time: pd.Timestamp, price: float) -> None:
        if not config.rebalance_after_cycle or futures.primary is not None or futures.hedge is not None:
            return
        equity_before = _equity(futures, spot, price)
        total = _equity(futures, spot, price)
        target_spot = total * config.spot_fraction
        current_spot = spot.equity(price)
        if current_spot > target_spot + 1e-9:
            proceeds = spot.sell_to_target(
                price,
                target_spot,
                fee_rate=exec_cfg.taker_fee_per_side,
                slippage=exec_cfg.slippage_per_side,
            )
            excess = max(0.0, min(spot.cash, spot.equity(price) - target_spot))
            transferred = transfers.transfer_spot_to_futures(
                spot,
                futures,
                time=time,
                amount=excess,
                purpose="POST_CYCLE_REBALANCE",
            )
            emit(
                time,
                "REBALANCED",
                transferred_to_futures=transferred,
                proceeds=proceeds,
            )
        elif current_spot < target_spot - 1e-9:
            need = target_spot - current_spot
            transfer = transfers.transfer_futures_to_spot(
                spot,
                futures,
                time=time,
                amount=min(need, futures.free_collateral),
                purpose="POST_CYCLE_REBALANCE",
            )
            if config.spot_mode == "HOLD":
                spot.buy_to_target(
                    price,
                    target_spot,
                    fee_rate=exec_cfg.taker_fee_per_side,
                    slippage=exec_cfg.slippage_per_side,
                )
            emit(time, "REBALANCED", transferred_to_spot=transfer)
        equity_after = _equity(futures, spot, price)
        if equity_after > equity_before + 1e-8:
            raise RuntimeError(
                f"rebalance created equity without market movement: {equity_before} -> {equity_after}"
            )

    def finish_cycle(time: pd.Timestamp, price: float, *, reason: str) -> None:
        nonlocal state, thesis_direction, primary_opened_at, hedge_cycles, hedge_close_streak, next_average_level, cycle_peak_equity, cycle_peak_futures_equity
        if futures.hedge is not None:
            close_role(time, "HEDGE", price, f"{reason}_HEDGE_CLOSE")
        if futures.primary is not None:
            close_role(time, "PRIMARY", price, reason)
        state = "RISK_EXIT" if reason.startswith("RISK") else "EXITED"
        thesis_direction = 0
        primary_opened_at = None
        hedge_cycles = 0
        hedge_close_streak = 0
        next_average_level = 0
        cycle_peak_equity = _equity(futures, spot, price)
        cycle_peak_futures_equity = futures.equity(price)
        if reason != "RUN_END":
            rebalance(time, price)
        emit(time, "CYCLE_FINISHED", reason=reason)

    def open_primary(time: pd.Timestamp, price: float, direction: int, signal: dict) -> None:
        nonlocal state, thesis_direction, primary_opened_at, hedge_cycles, hedge_close_streak, next_average_level, cycle_number, cycle_peak_equity, cycle_peak_futures_equity
        requested_desired = futures_budget * exec_cfg.primary_budget_fraction
        capacity_notional = _order_notional_capacity(signal, price, exec_cfg)
        if capacity_notional < exec_cfg.min_order_notional:
            emit(
                time,
                "PRIMARY_SKIPPED",
                reason="ORDER_NOTIONAL_LIMIT",
                capacity_notional=capacity_notional,
            )
            return
        desired = min(requested_desired, capacity_notional / exec_cfg.leverage)
        entry_report_risk = replace(
            config.risk,
            max_loss_fraction_total_equity=(
                config.risk.max_loss_fraction_total_equity
                * strategy.primary_risk_headroom_fraction
            ),
        )
        margin, report = maximum_margin_for_limit(
            futures,
            spot,
            price=price,
            side=direction,
            desired_margin=desired,
            execution=exec_cfg,
            risk=entry_report_risk,
        )
        margin = min(
            margin,
            _affordable_margin(futures.free_collateral, exec_cfg.leverage, exec_cfg.taker_fee_per_side),
        )
        if margin <= 1e-6 or margin * exec_cfg.leverage < exec_cfg.min_order_notional:
            emit(time, "PRIMARY_SKIPPED", reason="RISK_LIMIT", risk=report)
            return
        position = futures.open_position(
            "PRIMARY",
            side=direction,
            time=time,
            price=price,
            margin=margin,
            slippage=exec_cfg.slippage_per_side,
            fee_rate=exec_cfg.taker_fee_per_side,
            leverage=exec_cfg.leverage,
            max_notional=capacity_notional,
            min_notional=exec_cfg.min_order_notional,
        )
        position.metadata.update(recovery_estimate(time, direction))
        cycle_number += 1
        thesis_direction = direction
        primary_opened_at = time
        hedge_cycles = 0
        hedge_close_streak = 0
        next_average_level = 0
        cycle_peak_equity = _equity(futures, spot, price)
        cycle_peak_futures_equity = futures.equity(price)
        state = "PRIMARY_OPEN"
        emit(
            time,
            "PRIMARY_OPENED",
            cycle=cycle_number,
            side="LONG" if direction > 0 else "SHORT",
            margin=margin,
            quantity=position.quantity,
            requested_margin=requested_desired,
            filled_notional=position.metadata["filled_notional"],
            unfilled_notional=position.metadata["unfilled_notional"],
            risk=report,
        )

    def open_hedge(time: pd.Timestamp, price: float, signal: dict) -> None:
        nonlocal state, hedge_cycles, hedge_close_streak
        if futures.primary is None or not config.hedge_enabled or hedge_cycles >= strategy.max_hedge_cycles:
            return
        side = -futures.primary.side
        adverse = (
            futures.primary.average_entry - signal["close"]
            if futures.primary.side > 0
            else signal["close"] - futures.primary.average_entry
        )
        atr = signal.get("atr") or 0.0
        fast = signal.get("fast")
        contra_confirmed = (
            fast is not None
            and (
                (futures.primary.side > 0 and signal["close"] < fast)
                or (futures.primary.side < 0 and signal["close"] > fast)
            )
        )
        if atr <= 0 or adverse < strategy.hedge_atr_mult * atr or not contra_confirmed:
            return
        capacity_notional = _order_notional_capacity(signal, price, exec_cfg)
        if capacity_notional < exec_cfg.min_order_notional:
            emit(
                time,
                "HEDGE_SKIPPED",
                reason="ORDER_NOTIONAL_LIMIT",
                capacity_notional=capacity_notional,
            )
            return
        primary_notional = futures.primary.notional(price)
        reserve_cap = futures_budget * exec_cfg.hedge_budget_fraction
        for fraction in strategy.hedge_fractions:
            desired = min(
                reserve_cap,
                primary_notional * fraction / exec_cfg.leverage,
                capacity_notional / exec_cfg.leverage,
            )
            desired = min(
                desired,
                _affordable_margin(futures.free_collateral, exec_cfg.leverage, exec_cfg.taker_fee_per_side),
            )
            margin, report = maximum_margin_for_limit(
                futures,
                spot,
                price=price,
                side=side,
                desired_margin=desired,
                execution=exec_cfg,
                risk=config.risk,
            )
            if margin <= 1e-6 or margin * exec_cfg.leverage < exec_cfg.min_order_notional:
                continue
            position = futures.open_position(
                "HEDGE",
                side=side,
                time=time,
                price=price,
                margin=margin,
                slippage=exec_cfg.slippage_per_side,
                fee_rate=exec_cfg.taker_fee_per_side,
                leverage=exec_cfg.leverage,
                max_notional=capacity_notional,
                min_notional=exec_cfg.min_order_notional,
            )
            hedge_cycles += 1
            hedge_close_streak = 0
            state = "HEDGED"
            emit(
                time,
                "HEDGE_OPENED",
                side="LONG" if side > 0 else "SHORT",
                fraction=fraction,
                margin=margin,
                quantity=position.quantity,
                filled_notional=position.metadata["filled_notional"],
                unfilled_notional=position.metadata["unfilled_notional"],
                risk=report,
            )
            return
        emit(time, "HEDGE_SKIPPED", reason="RISK_OR_MARGIN")

    def average_primary(time: pd.Timestamp, price: float, signal: dict) -> None:
        nonlocal state, next_average_level
        if futures.primary is None or not config.averaging_enabled:
            return
        fast = signal.get("fast")
        slow = signal.get("slow")
        thesis_intact = (
            fast is not None
            and slow is not None
            and (
                (
                    futures.primary.side > 0
                    and fast > slow
                    and signal["close"] > slow
                )
                or (
                    futures.primary.side < 0
                    and fast < slow
                    and signal["close"] < slow
                )
            )
        )
        if next_average_level >= len(strategy.averaging_atr_levels) or not thesis_intact:
            return
        atr = signal.get("atr") or 0.0
        if atr <= 0:
            return
        adverse = (
            futures.primary.average_entry - signal["close"]
            if futures.primary.side > 0
            else signal["close"] - futures.primary.average_entry
        )
        level = strategy.averaging_atr_levels[next_average_level]
        if adverse < level * atr:
            return
        capacity_notional = _order_notional_capacity(signal, price, exec_cfg)
        if capacity_notional < exec_cfg.min_order_notional:
            emit(
                time,
                "AVERAGING_SKIPPED",
                level=next_average_level + 1,
                reason="ORDER_NOTIONAL_LIMIT",
                capacity_notional=capacity_notional,
            )
            next_average_level += 1
            return
        requested_desired = futures_budget * exec_cfg.averaging_budget_fractions[next_average_level]
        desired = min(requested_desired, capacity_notional / exec_cfg.leverage)
        desired = min(
            desired,
            _affordable_margin(futures.free_collateral, exec_cfg.leverage, exec_cfg.taker_fee_per_side),
        )
        margin, report = maximum_margin_for_limit(
            futures,
            spot,
            price=price,
            side=futures.primary.side,
            desired_margin=desired,
            execution=exec_cfg,
            risk=config.risk,
        )
        if margin <= 1e-6 or margin * exec_cfg.leverage < exec_cfg.min_order_notional:
            emit(time, "AVERAGING_SKIPPED", level=next_average_level + 1, reason="RISK_OR_MARGIN", risk=report)
            next_average_level += 1
            return
        futures.average_primary(
            time=time,
            price=price,
            margin=margin,
            slippage=exec_cfg.slippage_per_side,
            fee_rate=exec_cfg.taker_fee_per_side,
            leverage=exec_cfg.leverage,
            max_notional=capacity_notional,
            min_notional=exec_cfg.min_order_notional,
        )
        next_average_level += 1
        state = "PRIMARY_AVERAGED"
        emit(
            time,
            "PRIMARY_AVERAGED",
            level=next_average_level,
            margin=margin,
            quantity=futures.primary.quantity,
            average_entry=futures.primary.average_entry,
            requested_margin=requested_desired,
            child_metadata=futures.primary.metadata["children"][-1],
            risk=report,
        )

    previous_date = None
    for index, row in enumerate(frame.itertuples(index=False)):
        time = pd.Timestamp(row.open_time)
        price = float(row.futures_open)
        signal = decision_by_index.get(index)
        if signal is not None and config.spot_mode == "SWING" and signal["direction"] != 0:
            spot_equity = spot.equity(price)
            if signal["direction"] > 0:
                spot.buy_to_target(
                    price,
                    spot_equity,
                    fee_rate=exec_cfg.taker_fee_per_side,
                    slippage=exec_cfg.slippage_per_side,
                )
            else:
                spot.sell_to_target(
                    price,
                    0.0,
                    fee_rate=exec_cfg.taker_fee_per_side,
                    slippage=exec_cfg.slippage_per_side,
                )

        if signal is not None and futures.primary is not None:
            if futures.hedge is not None:
                if signal["direction"] == futures.primary.side:
                    hedge_close_streak += 1
                    if hedge_close_streak >= strategy.hedge_close_confirmations:
                        close_role(time, "HEDGE", price, "REVERSAL_CONFIRMED")
                else:
                    hedge_close_streak = 0
            held_hours = (time - primary_opened_at).total_seconds() / 3600.0 if primary_opened_at else 0.0
            open_hedge(time, price, signal)
            if (
                futures.hedge is None
                and signal["direction"] == -futures.primary.side
                and held_hours >= strategy.min_hold_hours
            ):
                finish_cycle(time, price, reason="TREND_REVERSAL")
            elif futures.primary is not None:
                average_primary(time, price, signal)

        if signal is not None and futures.primary is None and futures.free_collateral > 0 and signal["direction"] != 0:
            open_primary(time, price, signal["direction"], signal)

        funding_rate = funding_by_minute.get(time.floor("min"))
        if funding_rate is not None and (futures.primary is not None or futures.hedge is not None):
            cost = futures.apply_funding(price, funding_rate)
            emit(time, "FUNDING_APPLIED", rate=funding_rate, cost=cost)

        mark_high = float(row.mark_high)
        mark_low = float(row.mark_low)
        mark_close = float(row.mark_close)
        if futures.primary is not None or futures.hedge is not None:
            risk_time_equity = _equity(futures, spot, mark_close)
            risk_time_futures_equity = futures.equity(mark_close)
            continuous_risk = risk_report(
                futures,
                spot,
                price=mark_close,
                execution=exec_cfg,
                risk=config.risk,
            )
            cycle_loss_futures = max(0.0, cycle_peak_futures_equity - risk_time_futures_equity)
            cycle_loss_total = max(0.0, cycle_peak_equity - risk_time_equity)
            projected_thesis_loss = cycle_loss_futures + continuous_risk["worst_loss_usdt"]
            projected_total_loss = (
                cycle_loss_total + continuous_risk["worst_total_portfolio_loss_usdt"]
            )
            risk_base = risk_time_equity if risk_time_equity > 0 else float("inf")
            actual_thesis_loss_fraction = cycle_loss_futures / risk_base
            actual_total_loss_fraction = cycle_loss_total / risk_base
            continuous_risk.update(
                {
                    "cycle_loss_futures": cycle_loss_futures,
                    "cycle_loss_total_portfolio": cycle_loss_total,
                    "projected_thesis_loss_usdt": projected_thesis_loss,
                    "projected_thesis_loss_fraction": projected_thesis_loss / risk_base,
                    "projected_total_portfolio_loss_usdt": projected_total_loss,
                    "projected_total_portfolio_loss_fraction": projected_total_loss / risk_base,
                    "actual_thesis_loss_fraction": actual_thesis_loss_fraction,
                    "actual_total_portfolio_loss_fraction": actual_total_loss_fraction,
                    "continuous_thesis_passes": (
                        actual_thesis_loss_fraction
                        <= config.risk.max_loss_fraction_total_equity + 1e-12
                    ),
                }
            )
            if not continuous_risk["continuous_thesis_passes"]:
                risk_exits += 1
                emit(
                    time,
                    "CONTINUOUS_RISK_LIMIT_BREACH",
                    risk=continuous_risk,
                )
                finish_cycle(time, mark_close, reason="RISK_LIMIT_CONTINUOUS")
            else:
                cycle_peak_equity = max(cycle_peak_equity, risk_time_equity)
                cycle_peak_futures_equity = max(
                    cycle_peak_futures_equity, risk_time_futures_equity
                )
        liquidation_roles: list[str] = []
        for role in ("PRIMARY", "HEDGE"):
            position = role_position(role)
            if position is None:
                continue
            liq = position.liquidation_price(
                exec_cfg.maintenance_margin_rate,
                exec_cfg.taker_fee_per_side,
            )
            if (position.side > 0 and mark_low <= liq) or (position.side < 0 and mark_high >= liq):
                liquidation_roles.append(role)
        if liquidation_roles:
            liquidated += len(liquidation_roles)
            for role in liquidation_roles:
                position = role_position(role)
                if position is None:
                    continue
                liq = position.liquidation_price(
                    exec_cfg.maintenance_margin_rate,
                    exec_cfg.taker_fee_per_side,
                )
                trade = futures.liquidate(
                    role,
                    time=time,
                    liquidation_price=liq,
                    liquidation_fee_rate=exec_cfg.liquidation_fee_rate,
                )
                trades.append(trade)
                emit(time, f"{role}_LIQUIDATED", **trade)
            if futures.hedge is not None:
                emergency_closes += 1
                close_role(time, "HEDGE", mark_close, "PRIMARY_LIQUIDATION_EXIT")
            if futures.primary is not None:
                emergency_closes += 1
                close_role(time, "PRIMARY", mark_close, "HEDGE_LIQUIDATION_EXIT")
            state = "LIQUIDATED"
            thesis_direction = 0
            primary_opened_at = None
            hedge_cycles = 0
            next_average_level = 0
            cycle_peak_equity = _equity(futures, spot, mark_close)
            cycle_peak_futures_equity = futures.equity(mark_close)
            rebalance(time, mark_close)
            emit(time, "CYCLE_FINISHED", reason="LIQUIDATED")

        current_equity = _equity(futures, spot, mark_close)
        if current_equity <= 0:
            emergency_closes += 1
            emit(time, "ACCOUNT_RUINED", equity=current_equity)
            equity_rows.append(account_snapshot(time, mark_close))
            break
        if time.date() != previous_date:
            equity_rows.append(account_snapshot(time, mark_close))
            previous_date = time.date()

    last = frame.iloc[-1]
    final_time = pd.Timestamp(last["open_time"])
    final_mark = float(last["mark_close"])
    if futures.primary is not None or futures.hedge is not None:
        finish_cycle(final_time, final_mark, reason="RUN_END")
    final_equity = _equity(futures, spot, final_mark)
    equity_rows.append(account_snapshot(final_time, final_mark))

    equity_frame = pd.DataFrame(equity_rows).drop_duplicates("time").sort_values("time")
    trades_frame = pd.DataFrame(trades)
    events_frame = pd.DataFrame(events)
    equity_values = equity_frame["equity"].astype(float).tolist()
    close_pnls = trades_frame["net_pnl"].astype(float) if not trades_frame.empty else pd.Series(dtype=float)
    gains = float(close_pnls[close_pnls > 0].sum())
    losses = float(-close_pnls[close_pnls < 0].sum())
    profit_factor = gains / losses if losses > 0 else (float("inf") if gains > 0 else float("nan"))
    primary_trades = trades_frame[trades_frame["role"] == "PRIMARY"] if not trades_frame.empty else trades_frame
    hedge_trades = trades_frame[trades_frame["role"] == "HEDGE"] if not trades_frame.empty else trades_frame
    buy_hold = float(last["close"]) / float(frame.iloc[0]["close"]) - 1.0
    metrics = {
        "portfolio": config.name,
        "start": pd.Timestamp(frame.iloc[0]["open_time"]).isoformat(),
        "end": final_time.isoformat(),
        "initial_capital": config.initial_capital,
        "spot_fraction": config.spot_fraction,
        "spot_mode": config.spot_mode,
        "hedge_enabled": config.hedge_enabled,
        "averaging_enabled": config.averaging_enabled,
        "final_equity": final_equity,
        "return_percent": (final_equity / config.initial_capital - 1.0) * 100.0,
        "spot_cash": spot.cash,
        "spot_eth": spot.eth,
        "spot_eth_value": spot.eth * final_mark,
        "spot_equity": spot.equity(final_mark),
        "futures_free_collateral": futures.free_collateral,
        "futures_used_margin": futures.margin_used(),
        "futures_equity": futures.equity(final_mark),
        "transfers_spot_to_futures": transfers.spot_to_futures,
        "transfers_futures_to_spot": transfers.futures_to_spot,
        "transfer_count": len(transfers.records),
        "transfer_records": [asdict(record) for record in transfers.records],
        "realized_primary": futures.realized_primary,
        "realized_hedge": futures.realized_hedge,
        "fees": futures.entry_fees + futures.exit_fees,
        "funding_costs": futures.funding_costs,
        "slippage_costs": futures.slippage_costs,
        "liquidation_fees": futures.liquidation_fees,
        "trade_count": int(len(trades_frame)),
        "primary_trade_count": int(len(primary_trades)),
        "hedge_trade_count": int(len(hedge_trades)),
        "averaging_count": int((events_frame["event"] == "PRIMARY_AVERAGED").sum()) if not events_frame.empty else 0,
        "liquidation_count": liquidated,
        "risk_exit_count": risk_exits,
        "emergency_close_count": emergency_closes,
        "isolated_deficit": float(
            trades_frame["isolated_deficit"].fillna(0.0).sum()
        )
        if not trades_frame.empty and "isolated_deficit" in trades_frame
        else 0.0,
        "profit_factor": profit_factor,
        "max_drawdown": _max_drawdown(equity_values),
        "max_equity": max(equity_values),
        "buy_hold_return": buy_hold,
        "thresholds_reached": [
            level for level in (200.0, 500.0, 1000.0, 10000.0) if max(equity_values) >= level
        ],
        "mean_holding_hours": float(trades_frame["holding_hours"].mean()) if not trades_frame.empty and "holding_hours" in trades_frame else None,
        "max_holding_hours": float(trades_frame["holding_hours"].max()) if not trades_frame.empty and "holding_hours" in trades_frame else None,
        "state": state,
    }
    if not trades_frame.empty:
        entry = pd.to_datetime(trades_frame["entry_time"], utc=True)
        exit_ = pd.to_datetime(trades_frame["exit_time"], utc=True)
        trades_frame["holding_hours"] = (exit_ - entry).dt.total_seconds() / 3600.0
        metrics["mean_holding_hours"] = float(trades_frame["holding_hours"].mean())
        metrics["max_holding_hours"] = float(trades_frame["holding_hours"].max())
        recovery_primary = trades_frame[
            (trades_frame["role"] == "PRIMARY")
            & trades_frame["recovery_p50_hours"].notna()
            & trades_frame["holding_hours"].notna()
        ]
        if not recovery_primary.empty:
            errors = (
                recovery_primary["holding_hours"] - recovery_primary["recovery_p50_hours"]
            ).abs()
            metrics["recovery_p50_mae_hours"] = float(errors.mean())
            metrics["recovery_p50_accuracy_within_50pct"] = float(
                (
                    errors
                    <= recovery_primary["recovery_p50_hours"].abs() * 0.5
                ).mean()
            )
            metrics["recovery_unresolved_rate_mean"] = float(
                recovery_primary["recovery_unresolved_rate"].mean()
            )
        else:
            metrics["recovery_p50_mae_hours"] = None
            metrics["recovery_p50_accuracy_within_50pct"] = None
            metrics["recovery_unresolved_rate_mean"] = None
    return SimulationResult(
        portfolio=config.name,
        trades=trades_frame,
        events=events_frame,
        equity=equity_frame,
        metrics=metrics,
        config=asdict(config),
    )
