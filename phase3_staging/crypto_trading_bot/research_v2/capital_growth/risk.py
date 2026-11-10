from __future__ import annotations

from typing import Any

from .accounting import FuturesAccount, SpotAccount
from .config import ExecutionConfig, RiskConfig


def _proposed_position_value(side: int, margin: float, fill: float, price: float, leverage: float) -> float:
    quantity = margin * leverage / fill
    return margin + side * quantity * (price - fill)


def scenario_equity(
    futures: FuturesAccount,
    spot: SpotAccount,
    *,
    price: float,
    move: float,
    proposed_side: int | None = None,
    proposed_margin: float = 0.0,
    execution: ExecutionConfig = ExecutionConfig(),
) -> float:
    moved_price = float(price) * (1.0 + float(move))
    equity = spot.cash + spot.eth * moved_price + futures.free_collateral
    for position in (futures.primary, futures.hedge):
        if position is not None:
            equity += position.margin + position.side * position.quantity * (moved_price - position.average_entry)
    if proposed_side is not None and proposed_margin > 0:
        fill = float(price) * (1.0 + proposed_side * execution.slippage_per_side)
        fee = proposed_margin * execution.leverage * execution.taker_fee_per_side
        equity -= proposed_margin + fee
        equity += _proposed_position_value(
            proposed_side,
            proposed_margin,
            fill,
            moved_price,
            execution.leverage,
        )
    return float(equity)


def risk_report(
    futures: FuturesAccount,
    spot: SpotAccount,
    *,
    price: float,
    proposed_side: int | None = None,
    proposed_margin: float = 0.0,
    execution: ExecutionConfig = ExecutionConfig(),
    risk: RiskConfig = RiskConfig(),
) -> dict[str, Any]:
    current = scenario_equity(
        futures,
        spot,
        price=price,
        move=0.0,
        execution=execution,
    )
    scenarios = {}
    worst_loss = 0.0
    for move in risk.scenario_moves:
        value = scenario_equity(
            futures,
            spot,
            price=price,
            move=move,
            proposed_side=proposed_side,
            proposed_margin=proposed_margin,
            execution=execution,
        )
        loss = current - value
        scenarios[f"{move:+.0%}"] = loss
        worst_loss = max(worst_loss, loss)
    loss_fraction = worst_loss / current if current > 0 else float("inf")
    return {
        "current_equity": current,
        "scenario_loss_usdt": scenarios,
        "worst_loss_usdt": worst_loss,
        "worst_loss_fraction": loss_fraction,
        "risk_limit_fraction": risk.max_loss_fraction_total_equity,
        "passes": loss_fraction <= risk.max_loss_fraction_total_equity + 1e-12,
    }


def maximum_margin_for_limit(
    futures: FuturesAccount,
    spot: SpotAccount,
    *,
    price: float,
    side: int,
    desired_margin: float,
    execution: ExecutionConfig = ExecutionConfig(),
    risk: RiskConfig = RiskConfig(),
) -> tuple[float, dict[str, Any]]:
    desired = max(0.0, float(desired_margin))
    report = risk_report(
        futures,
        spot,
        price=price,
        proposed_side=side,
        proposed_margin=desired,
        execution=execution,
        risk=risk,
    )
    if report["passes"]:
        return desired, report
    low, high = 0.0, desired
    best = 0.0
    best_report = report
    for _ in range(60):
        mid = (low + high) / 2.0
        candidate = risk_report(
            futures,
            spot,
            price=price,
            proposed_side=side,
            proposed_margin=mid,
            execution=execution,
            risk=risk,
        )
        if candidate["passes"]:
            best = mid
            best_report = candidate
            low = mid
        else:
            high = mid
    return best, best_report
