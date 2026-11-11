from __future__ import annotations

from typing import Any

from .accounting import FuturesAccount, SpotAccount
from .config import ExecutionConfig, RiskConfig


def _proposed_position_value(side: int, margin: float, fill: float, price: float, leverage: float) -> float:
    quantity = margin * leverage / fill
    return margin + side * quantity * (price - fill)


def _scenario_components(
    futures: FuturesAccount,
    spot: SpotAccount,
    *,
    price: float,
    move: float,
    proposed_side: int | None = None,
    proposed_margin: float = 0.0,
    execution: ExecutionConfig = ExecutionConfig(),
) -> tuple[float, float, float]:
    moved_price = float(price) * (1.0 + float(move))
    spot_equity = spot.cash + spot.eth * moved_price
    futures_equity = futures.free_collateral
    for position in (futures.primary, futures.hedge):
        if position is not None:
            futures_equity += position.margin + position.side * position.quantity * (
                moved_price - position.average_entry
            )
    if proposed_side is not None and proposed_margin > 0:
        fill = float(price) * (1.0 + proposed_side * execution.slippage_per_side)
        fee = proposed_margin * execution.leverage * execution.taker_fee_per_side
        futures_equity -= proposed_margin + fee
        futures_equity += _proposed_position_value(
            proposed_side,
            proposed_margin,
            fill,
            moved_price,
            execution.leverage,
        )
    return float(spot_equity), float(futures_equity), float(spot_equity + futures_equity)


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
    return _scenario_components(
        futures,
        spot,
        price=price,
        move=move,
        proposed_side=proposed_side,
        proposed_margin=proposed_margin,
        execution=execution,
    )[2]


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
    current_spot, current_futures, current = _scenario_components(
        futures,
        spot,
        price=price,
        move=0.0,
        execution=execution,
    )
    total_scenarios: dict[str, float] = {}
    thesis_scenarios: dict[str, float] = {}
    worst_total_loss = 0.0
    worst_thesis_loss = 0.0
    for move in risk.scenario_moves:
        _, scenario_futures, scenario_total = _scenario_components(
            futures,
            spot,
            price=price,
            move=move,
            proposed_side=proposed_side,
            proposed_margin=proposed_margin,
            execution=execution,
        )
        total_loss = max(0.0, current - scenario_total)
        thesis_loss = max(0.0, current_futures - scenario_futures)
        key = f"{move:+.0%}"
        total_scenarios[key] = total_loss
        thesis_scenarios[key] = thesis_loss
        worst_total_loss = max(worst_total_loss, total_loss)
        worst_thesis_loss = max(worst_thesis_loss, thesis_loss)
    loss_fraction = worst_thesis_loss / current if current > 0 else float("inf")
    total_loss_fraction = worst_total_loss / current if current > 0 else float("inf")
    primary_unrealized = (
        futures.primary.unrealized(price) if futures.primary is not None else 0.0
    )
    hedge_unrealized = futures.hedge.unrealized(price) if futures.hedge is not None else 0.0
    return {
        "current_equity": current,
        "current_spot_equity": current_spot,
        "current_futures_equity": current_futures,
        "spot_exposure_usdt": spot.eth * float(price),
        "spot_exposure_fraction": (
            spot.eth * float(price) / current if current > 0 else float("inf")
        ),
        "free_collateral": futures.free_collateral,
        "used_margin": futures.margin_used(),
        "primary_unrealized": primary_unrealized,
        "hedge_unrealized": hedge_unrealized,
        "scenario_loss_usdt": thesis_scenarios,
        "total_portfolio_scenario_loss_usdt": total_scenarios,
        "worst_loss_usdt": worst_thesis_loss,
        "worst_total_portfolio_loss_usdt": worst_total_loss,
        "worst_loss_fraction": loss_fraction,
        "worst_total_portfolio_loss_fraction": total_loss_fraction,
        "risk_limit_fraction": risk.max_loss_fraction_total_equity,
        "passes": loss_fraction <= risk.max_loss_fraction_total_equity + 1e-12,
        "total_portfolio_passes": (
            total_loss_fraction <= risk.max_loss_fraction_total_equity + 1e-12
        ),
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
