from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, CatBoostRegressor

from crypto_trading_bot.research_v2.capital_growth.accounting import FuturesAccount, SpotAccount
from crypto_trading_bot.research_v2.capital_growth.config import (
    ExecutionConfig as RiskExecutionConfig,
    RiskConfig as PolicyRiskConfig,
)
from crypto_trading_bot.research_v2.capital_growth.risk import (
    maximum_margin_for_limit,
    risk_report,
)

from .config import (
    AI_VARIANTS,
    INITIAL_CAPITAL,
    LEVERAGE,
    LIQUIDATION_FEE_RATE,
    MAINTENANCE_MARGIN_RATE,
    MAX_THESIS_LOSS_FRACTION,
    RUN1_END,
    RUN1_START,
    RUN2_END,
    RUN2_START,
    SLIPPAGE_PER_SIDE,
    SPOT_FRACTIONS,
    SPOT_MODES,
    TAKER_FEE_PER_SIDE,
)
from .event_monitor import EventMonitor, MarketEvent
from .qwen_adapter import QwenConfig, QwenPolicyAdapter
from .train import ACTION_NAMES, DatasetBundle, build_matrix, load_bundle


@dataclass
class PolicyResult:
    name: str
    split_name: str
    spot_fraction: float
    spot_mode: str
    equity: pd.DataFrame
    trades: pd.DataFrame
    decisions: pd.DataFrame
    metrics: dict[str, Any]
    qwen_events: pd.DataFrame = field(default_factory=pd.DataFrame)
    market_events: pd.DataFrame = field(default_factory=pd.DataFrame)
    order_trace: pd.DataFrame = field(default_factory=pd.DataFrame)
    action_trace: pd.DataFrame = field(default_factory=pd.DataFrame)
    lifecycle_events: pd.DataFrame = field(default_factory=pd.DataFrame)


@dataclass
class PolicyAccount:
    spot_fraction: float
    spot_mode: str
    spot: SpotAccount = field(init=False)
    futures: FuturesAccount = field(init=False)
    peak_futures_equity: float = field(init=False)
    liquidation_count: int = 0
    averaging_count: int = 0
    hedge_count: int = 0
    hedge_signal_count: int = 0
    hedge_proposed_count: int = 0
    hedge_approved_count: int = 0
    hedge_rejected_count: int = 0
    hedge_filled_count: int = 0
    hedge_closed_count: int = 0
    primary_cycle_count: int = 0
    executed_order_count: int = 0
    total_notional_turnover: float = 0.0
    order_rejections: list[dict[str, Any]] = field(default_factory=list)
    order_trace: list[dict[str, Any]] = field(default_factory=list)
    lifecycle_events: list[dict[str, Any]] = field(default_factory=list)
    spot_slippage: float = 0.0
    spot_trade_count: int = 0
    trades: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    equity_rows: list[dict[str, Any]] = field(default_factory=list)
    qwen_events: list[dict[str, Any]] = field(default_factory=list)
    market_events: list[dict[str, Any]] = field(default_factory=list)
    action_trace: list[dict[str, Any]] = field(default_factory=list)
    lifecycle_state: str = "FLAT"
    cycle_id: int = 0
    risk_cycle_id: int | None = None
    risk_baseline_equity: float | None = None
    risk_peak_futures_equity: float | None = None
    risk_cycle_started_at: pd.Timestamp | None = None

    def __post_init__(self) -> None:
        self.spot = SpotAccount(cash=INITIAL_CAPITAL * self.spot_fraction)
        self.futures = FuturesAccount(
            free_collateral=INITIAL_CAPITAL * (1.0 - self.spot_fraction)
        )
        self.peak_futures_equity = self.futures.free_collateral

    def equity(self, mark: float, spot_mark: float | None = None) -> float:
        spot_price = float(mark if spot_mark is None else spot_mark)
        return float(self.spot.equity(spot_price) + self.futures.equity(mark))

    def position_state(self) -> str:
        if self.futures.primary is None:
            if self.futures.hedge is not None:
                return "HEDGE_ONLY"
            return "FLAT"
        if self.futures.hedge is not None:
            return "HEDGED"
        return "PRIMARY_OPEN"

    def _transition(
        self,
        time: pd.Timestamp,
        state: str,
        reason: str,
    ) -> None:
        self.lifecycle_state = state
        self.lifecycle_events.append(
            {
                "time": pd.Timestamp(time),
                "cycle_id": self.cycle_id,
                "state": state,
                "reason": reason,
                "position_state": self.position_state(),
            }
        )

    def begin_risk_cycle(
        self,
        time: pd.Timestamp,
        mark: float,
        spot_mark: float | None = None,
    ) -> None:
        spot_price = float(mark if spot_mark is None else spot_mark)
        self.cycle_id += 1
        self.risk_cycle_id = self.cycle_id
        self.risk_baseline_equity = self.equity(mark, spot_price)
        self.risk_peak_futures_equity = self.futures.equity(mark)
        self.risk_cycle_started_at = pd.Timestamp(time)
        self._transition(time, "PRIMARY_OPEN", "PRIMARY_OPENED")

    def clear_risk_cycle(
        self,
        time: pd.Timestamp,
        state: str,
        reason: str,
    ) -> None:
        self._transition(time, state, reason)
        if self.risk_cycle_id is not None:
            self.lifecycle_events.append(
                {
                    "time": pd.Timestamp(time),
                    "cycle_id": self.cycle_id,
                    "state": "FLAT",
                    "reason": reason,
                    "position_state": self.position_state(),
                }
            )
        self.risk_cycle_id = None
        self.risk_baseline_equity = None
        self.risk_peak_futures_equity = None
        self.risk_cycle_started_at = None

    def risk_metrics(
        self,
        mark: float,
        spot_mark: float | None = None,
    ) -> dict[str, float]:
        spot_price = float(mark if spot_mark is None else spot_mark)
        current_futures = self.futures.equity(mark)
        if (
            self.futures.primary is None
            or self.risk_cycle_id is None
            or self.risk_baseline_equity is None
            or self.risk_peak_futures_equity is None
        ):
            return {
                "futures_drawdown_fraction": 0.0,
                "remaining_thesis_risk_fraction": MAX_THESIS_LOSS_FRACTION,
                "risk_baseline_equity": float("nan"),
                "risk_peak_futures_equity": float("nan"),
            }
        self.risk_peak_futures_equity = max(
            self.risk_peak_futures_equity,
            current_futures,
        )
        drawdown = max(
            0.0,
            self.risk_peak_futures_equity - current_futures,
        ) / max(self.risk_baseline_equity, 1e-9)
        return {
            "futures_drawdown_fraction": drawdown,
            "remaining_thesis_risk_fraction": max(
                0.0,
                MAX_THESIS_LOSS_FRACTION - drawdown,
            ),
            "risk_baseline_equity": self.risk_baseline_equity,
            "risk_peak_futures_equity": self.risk_peak_futures_equity,
        }

    def state_snapshot(
        self,
        mark: float,
        time: pd.Timestamp,
        spot_mark: float | None = None,
    ) -> dict[str, Any]:
        primary = self.futures.primary
        hedge = self.futures.hedge
        spot_price = float(mark if spot_mark is None else spot_mark)

        def position_payload(position: Any) -> dict[str, Any] | None:
            if position is None:
                return None
            liquidation_price = position.liquidation_price(
                MAINTENANCE_MARGIN_RATE,
                TAKER_FEE_PER_SIDE,
            )
            return {
                "side": int(position.side),
                "quantity": float(position.quantity),
                "margin": float(position.margin),
                "average_entry": float(position.average_entry),
                "unrealized_pnl": float(position.unrealized(mark)),
                "notional": float(position.notional(mark)),
                "liquidation_price": float(liquidation_price),
                "liquidation_distance_pct": float(
                    abs(mark - liquidation_price) / max(mark, 1e-9)
                ),
                "additions": int(position.additions),
                "holding_hours": float(
                    (time - position.entry_time).total_seconds() / 3600.0
                ),
            }

        return {
            "state": self.position_state(),
            "lifecycle_state": self.lifecycle_state,
            "cycle_id": self.cycle_id,
            "risk_cycle_id": self.risk_cycle_id,
            "risk_baseline_equity": self.risk_baseline_equity,
            "risk_peak_futures_equity": self.risk_peak_futures_equity,
            "mark": float(mark),
            "equity": self.equity(mark, spot_price),
            "spot_exposure": float(self.spot.eth * spot_price),
            "free_collateral": float(self.futures.free_collateral),
            "used_margin": float(self.futures.margin_used()),
            "gross_notional": float(self.futures.gross_notional(mark)),
            "net_notional": float(self.futures.net_notional(mark)),
            "primary": position_payload(primary),
            "hedge": position_payload(hedge),
        }

    def state_features(
        self,
        mark: float,
        time: pd.Timestamp,
        spot_mark: float | None = None,
    ) -> dict[str, float]:
        primary = self.futures.primary
        hedge = self.futures.hedge
        spot_price = float(mark if spot_mark is None else spot_mark)
        equity = self.equity(mark, spot_price)
        gross = self.futures.gross_notional(mark)
        net = self.futures.net_notional(mark)
        liquidation_distance = 0.0
        if primary is not None:
            liquidation_distance = abs(
                mark
                - primary.liquidation_price(
                    MAINTENANCE_MARGIN_RATE,
                    TAKER_FEE_PER_SIDE,
                )
            ) / mark
        risk_state = self.risk_metrics(mark, spot_price)
        remaining = risk_state["remaining_thesis_risk_fraction"]
        return {
            "spot_fraction": self.spot_fraction,
            "spot_mode_code": 1.0 if self.spot_mode == "HOLD" else 0.0,
            "spot_exposure_fraction": self.spot.eth * spot_price / max(equity, 1e-9),
            "primary_side": float(primary.side) if primary is not None else 0.0,
            "primary_margin_fraction": primary.margin / max(equity, 1e-9) if primary else 0.0,
            "primary_quantity_fraction": primary.quantity * mark / max(equity, 1e-9) if primary else 0.0,
            "primary_unrealized_fraction": primary.unrealized(mark) / max(equity, 1e-9) if primary else 0.0,
            "hedge_side": float(hedge.side) if hedge is not None else 0.0,
            "hedge_margin_fraction": hedge.margin / max(equity, 1e-9) if hedge else 0.0,
            "hedge_quantity_fraction": hedge.quantity * mark / max(equity, 1e-9) if hedge else 0.0,
            "hedge_unrealized_fraction": hedge.unrealized(mark) / max(equity, 1e-9) if hedge else 0.0,
            "gross_exposure_fraction": gross / max(equity, 1e-9),
            "net_exposure_fraction": net / max(equity, 1e-9),
            "free_margin_fraction": self.futures.free_collateral / max(equity, 1e-9),
            "liquidation_distance_pct": liquidation_distance,
            "averaging_count": float(primary.additions) if primary else 0.0,
            "holding_hours": (
                (time - primary.entry_time).total_seconds() / 3600.0
                if primary is not None
                else 0.0
            ),
            "fees_cumulative": self.futures.entry_fees + self.futures.exit_fees,
            "funding_cumulative": self.futures.funding_costs,
            "remaining_thesis_risk_fraction": remaining,
            "risk_cycle_id": float(self.risk_cycle_id or 0),
            "risk_baseline_equity": risk_state["risk_baseline_equity"],
            "risk_peak_futures_equity": risk_state["risk_peak_futures_equity"],
        }

    @staticmethod
    def _risk_execution_config() -> RiskExecutionConfig:
        return RiskExecutionConfig(
            leverage=LEVERAGE,
            taker_fee_per_side=TAKER_FEE_PER_SIDE,
            slippage_per_side=SLIPPAGE_PER_SIDE,
            maintenance_margin_rate=MAINTENANCE_MARGIN_RATE,
            liquidation_fee_rate=LIQUIDATION_FEE_RATE,
        )

    @staticmethod
    def _risk_config() -> PolicyRiskConfig:
        return PolicyRiskConfig(
            max_loss_fraction_total_equity=MAX_THESIS_LOSS_FRACTION
        )

    def _risk_sized_margin(
        self,
        side: int,
        desired_margin: float,
        mark: float,
    ) -> tuple[float, dict[str, Any]]:
        return maximum_margin_for_limit(
            self.futures,
            self.spot,
            price=mark,
            side=side,
            desired_margin=desired_margin,
            execution=self._risk_execution_config(),
            risk=self._risk_config(),
        )

    def current_risk(self, mark: float) -> dict[str, Any]:
        return risk_report(
            self.futures,
            self.spot,
            price=mark,
            execution=self._risk_execution_config(),
            risk=self._risk_config(),
        )

    def _record_order(
        self,
        *,
        time: pd.Timestamp,
        role: str,
        action: str,
        executed: bool,
        reason: str,
        margin: float = 0.0,
        quantity: float = 0.0,
        notional: float = 0.0,
        fee: float = 0.0,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = {
            "time": pd.Timestamp(time).isoformat(),
            "role": role,
            "action": action,
            "executed": int(executed),
            "reason": reason,
            "margin": margin,
            "quantity": quantity,
            "notional": notional,
            "fee": fee,
            "state_after": self.position_state(),
            "cycle_id": self.cycle_id,
            **(context or {}),
        }
        self.order_trace.append(row)
        if executed:
            self.executed_order_count += 1
            self.total_notional_turnover += float(notional)
        else:
            self.order_rejections.append(row)
        return row

    def _spot_swing(
        self,
        time: pd.Timestamp,
        futures_mark: float,
        spot_mark: float,
        direction: int,
    ) -> None:
        if self.spot_mode != "SWING":
            return
        target = (
            self.equity(futures_mark, spot_mark) * self.spot_fraction
            if direction > 0
            else 0.0
        )
        if target > self.spot.equity(spot_mark):
            fees_before = self.spot.fees_paid
            eth_before = self.spot.eth
            spent = self.spot.buy_to_target(
                spot_mark,
                target,
                fee_rate=TAKER_FEE_PER_SIDE,
                slippage=SLIPPAGE_PER_SIDE,
            )
            self.spot_slippage += spent * SLIPPAGE_PER_SIDE
            self.spot_trade_count += int(spent > 0)
            if spent > 0:
                self._record_order(
                    time=time,
                    role="SPOT",
                    action="SPOT_BUY",
                    executed=True,
                    reason="TARGET_REBALANCE",
                    quantity=self.spot.eth - eth_before,
                    notional=spent,
                    fee=self.spot.fees_paid - fees_before,
                )
        elif target < self.spot.equity(spot_mark):
            fees_before = self.spot.fees_paid
            eth_before = self.spot.eth
            proceeds = self.spot.sell_to_target(
                spot_mark,
                target,
                fee_rate=TAKER_FEE_PER_SIDE,
                slippage=SLIPPAGE_PER_SIDE,
            )
            self.spot_slippage += proceeds * SLIPPAGE_PER_SIDE
            self.spot_trade_count += int(proceeds > 0)
            if proceeds > 0:
                self._record_order(
                    time=time,
                    role="SPOT",
                    action="SPOT_SELL",
                    executed=True,
                    reason="TARGET_REBALANCE",
                    quantity=eth_before - self.spot.eth,
                    notional=proceeds,
                    fee=self.spot.fees_paid - fees_before,
                )

    def _open(
        self,
        side: int,
        time: pd.Timestamp,
        mark: float,
        volume: float,
        spot_mark: float | None = None,
    ) -> list[dict[str, Any]]:
        spot_price = float(mark if spot_mark is None else spot_mark)
        if self.futures.primary is not None:
            return [
                self._record_order(
                    time=time,
                    role="PRIMARY",
                    action="OPEN",
                    executed=False,
                    reason="PRIMARY_ALREADY_OPEN",
                )
            ]
        total = self.equity(mark)
        budget = INITIAL_CAPITAL * (1.0 - self.spot_fraction) * 0.40
        affordable = self.futures.free_collateral / (
            1.0 + LEVERAGE * TAKER_FEE_PER_SIDE
        )
        desired = min(
            budget,
            affordable,
        )
        sized, report = self._risk_sized_margin(side, desired, mark)
        capacity = min(1_000.0, max(0.0, volume) * mark * 0.001)
        margin = min(sized, max(0.0, capacity) / LEVERAGE)
        context = {
            "risk_approved": bool(report.get("passes")),
            "risk": report,
            "desired_margin": desired,
            "risk_sized_margin": sized,
            "capacity_notional": capacity,
            "total_equity_before": total,
        }
        if desired <= 1e-12:
            return [
                self._record_order(
                    time=time,
                    role="PRIMARY",
                    action="OPEN",
                    executed=False,
                    reason="FREE_MARGIN",
                    context=context,
                )
            ]
        if sized <= 1e-12 or not report.get("passes", False):
            return [
                self._record_order(
                    time=time,
                    role="PRIMARY",
                    action="OPEN",
                    executed=False,
                    reason="RISK_LIMIT",
                    context=context,
                )
            ]
        if capacity < 5.0:
            return [
                self._record_order(
                    time=time,
                    role="PRIMARY",
                    action="OPEN",
                    executed=False,
                    reason="LIQUIDITY_CAPACITY",
                    context=context,
                )
            ]
        if margin * LEVERAGE < 5.0:
            return [
                self._record_order(
                    time=time,
                    role="PRIMARY",
                    action="OPEN",
                    executed=False,
                    reason="MIN_NOTIONAL",
                    context=context,
                )
            ]
        try:
            position = self.futures.open_position(
                "PRIMARY",
                side=side,
                time=time,
                price=mark,
                margin=margin,
                slippage=SLIPPAGE_PER_SIDE,
                fee_rate=TAKER_FEE_PER_SIDE,
                leverage=LEVERAGE,
                max_notional=capacity,
                min_notional=5.0,
            )
        except ValueError as exc:
            return [
                self._record_order(
                    time=time,
                    role="PRIMARY",
                    action="OPEN",
                    executed=False,
                    reason=f"ORDER_REJECTED:{exc}",
                    margin=margin,
                    context=context,
                )
            ]
        self.begin_risk_cycle(time, mark, spot_price)
        self._spot_swing(time, mark, spot_price, side)
        self.risk_baseline_equity = self.equity(mark, spot_price)
        self.risk_peak_futures_equity = self.futures.equity(mark)
        order = self._record_order(
            time=time,
            role="PRIMARY",
            action="OPEN",
            executed=True,
            reason="FILLED",
            margin=position.margin,
            quantity=position.quantity,
            notional=position.metadata["filled_notional"],
            fee=position.entry_fees,
            context=context,
        )
        return [order]

    def _close(
        self,
        role: str,
        time: pd.Timestamp,
        mark: float,
        reason: str,
        spot_mark: float | None = None,
    ) -> dict[str, Any] | None:
        spot_price = float(mark if spot_mark is None else spot_mark)
        if (role == "PRIMARY" and self.futures.primary is None) or (
            role == "HEDGE" and self.futures.hedge is None
        ):
            return None
        trade = self.futures.close_position(
            role,
            time=time,
            price=mark,
            slippage=SLIPPAGE_PER_SIDE,
            fee_rate=TAKER_FEE_PER_SIDE,
            reason=reason,
        )
        trade["cycle_id"] = self.cycle_id
        self.trades.append(trade)
        self._record_order(
            time=time,
            role=role,
            action="EXIT",
            executed=True,
            reason=reason,
            margin=float(trade["margin"]),
            quantity=float(trade["quantity"]),
            notional=float(trade["quantity"]) * float(trade["exit_fill"]),
            fee=float(trade["exit_fee"]),
        )
        if role == "HEDGE":
            self.hedge_closed_count += 1
            self._transition(time, "HEDGE_CLOSED", reason)
        else:
            self.primary_cycle_count += 1
            self.clear_risk_cycle(time, "EXITED", reason)
        if role == "PRIMARY":
            self._spot_swing(time, mark, spot_price, 0)
        return trade

    def execute(
        self,
        action: str,
        *,
        time: pd.Timestamp,
        mark: float,
        volume: float,
        spot_mark: float | None = None,
        execution_reason: str | None = None,
    ) -> list[dict[str, Any]]:
        spot_price = float(mark if spot_mark is None else spot_mark)
        if action == "OPEN_LONG":
            return self._open(1, time, mark, volume, spot_price)
        elif action == "OPEN_SHORT":
            return self._open(-1, time, mark, volume, spot_price)
        elif action == "OPEN_HEDGE":
            if self.futures.primary is None:
                self.hedge_rejected_count += 1
                return [
                    self._record_order(
                        time=time,
                        role="HEDGE",
                        action="OPEN_HEDGE",
                        executed=False,
                        reason="NO_PRIMARY",
                    )
                ]
            if self.futures.hedge is not None:
                self.hedge_rejected_count += 1
                return [
                    self._record_order(
                        time=time,
                        role="HEDGE",
                        action="OPEN_HEDGE",
                        executed=False,
                        reason="HEDGE_ALREADY_OPEN",
                    )
                ]
            side = -self.futures.primary.side
            affordable = self.futures.free_collateral / (
                1.0 + LEVERAGE * TAKER_FEE_PER_SIDE
            )
            desired = min(
                INITIAL_CAPITAL * (1.0 - self.spot_fraction) * 0.20,
                self.futures.primary.margin,
                affordable,
            )
            sized, report = self._risk_sized_margin(side, desired, mark)
            capacity = min(1_000.0, max(0.0, volume) * mark * 0.001)
            margin = min(sized, max(0.0, capacity) / LEVERAGE)
            context = {
                "risk_approved": bool(report.get("passes")),
                "risk": report,
                "desired_margin": desired,
                "risk_sized_margin": sized,
                "capacity_notional": capacity,
            }
            reason = None
            if desired <= 1e-12:
                reason = "FREE_MARGIN"
            elif sized <= 1e-12 or not report.get("passes", False):
                reason = "RISK_LIMIT"
            elif capacity < 5.0:
                reason = "LIQUIDITY_CAPACITY"
            elif margin * LEVERAGE < 5.0:
                reason = "MIN_NOTIONAL"
            if reason is not None:
                self.hedge_rejected_count += 1
                return [
                    self._record_order(
                        time=time,
                        role="HEDGE",
                        action="OPEN_HEDGE",
                        executed=False,
                        reason=reason,
                        margin=margin,
                        context=context,
                    )
                ]
            self.hedge_approved_count += 1
            try:
                position = self.futures.open_position(
                    "HEDGE",
                    side=side,
                    time=time,
                    price=mark,
                    margin=margin,
                    slippage=SLIPPAGE_PER_SIDE,
                    fee_rate=TAKER_FEE_PER_SIDE,
                    leverage=LEVERAGE,
                    max_notional=capacity,
                    min_notional=5.0,
                )
            except ValueError as exc:
                self.hedge_rejected_count += 1
                return [
                    self._record_order(
                        time=time,
                        role="HEDGE",
                        action="OPEN_HEDGE",
                        executed=False,
                        reason=f"ORDER_REJECTED:{exc}",
                        margin=margin,
                        context=context,
                    )
                ]
            self.hedge_count += 1
            self.hedge_filled_count += 1
            self._transition(time, "HEDGED", "HEDGE_OPENED")
            return [
                self._record_order(
                    time=time,
                    role="HEDGE",
                    action="OPEN_HEDGE",
                    executed=True,
                    reason="FILLED",
                    margin=position.margin,
                    quantity=position.quantity,
                    notional=position.metadata["filled_notional"],
                    fee=position.entry_fees,
                    context=context,
                )
            ]
        elif action == "CLOSE_HEDGE":
            if self.futures.hedge is None:
                return [
                    self._record_order(
                        time=time,
                        role="HEDGE",
                        action="CLOSE_HEDGE",
                        executed=False,
                        reason="NO_HEDGE",
                    )
                ]
            before = len(self.order_trace)
            self._close("HEDGE", time, mark, "AI_CLOSE_HEDGE", spot_price)
            return self.order_trace[before:]
        elif action == "AVERAGE_PRIMARY":
            if self.futures.primary is None:
                return [
                    self._record_order(
                        time=time,
                        role="PRIMARY",
                        action="AVERAGE_PRIMARY",
                        executed=False,
                        reason="NO_PRIMARY",
                    )
                ]
            if self.futures.primary.additions >= 2:
                return [
                    self._record_order(
                        time=time,
                        role="PRIMARY",
                        action="AVERAGE_PRIMARY",
                        executed=False,
                        reason="AVERAGING_LIMIT",
                    )
                ]
            affordable = self.futures.free_collateral / (
                1.0 + LEVERAGE * TAKER_FEE_PER_SIDE
            )
            desired = min(
                INITIAL_CAPITAL * (1.0 - self.spot_fraction) * 0.20,
                affordable,
            )
            sized, report = self._risk_sized_margin(
                self.futures.primary.side,
                desired,
                mark,
            )
            capacity = min(1_000.0, max(0.0, volume) * mark * 0.001)
            margin = min(sized, max(0.0, capacity) / LEVERAGE)
            context = {
                "risk_approved": bool(report.get("passes")),
                "risk": report,
                "desired_margin": desired,
                "risk_sized_margin": sized,
                "capacity_notional": capacity,
            }
            reason = None
            if desired <= 1e-12:
                reason = "FREE_MARGIN"
            elif sized <= 1e-12 or not report.get("passes", False):
                reason = "RISK_LIMIT"
            elif capacity < 5.0:
                reason = "LIQUIDITY_CAPACITY"
            elif margin * LEVERAGE < 5.0:
                reason = "MIN_NOTIONAL"
            if reason is not None:
                return [
                    self._record_order(
                        time=time,
                        role="PRIMARY",
                        action="AVERAGE_PRIMARY",
                        executed=False,
                        reason=reason,
                        margin=margin,
                        context=context,
                    )
                ]
            try:
                self.futures.average_primary(
                    time=time,
                    price=mark,
                    margin=margin,
                    slippage=SLIPPAGE_PER_SIDE,
                    fee_rate=TAKER_FEE_PER_SIDE,
                    leverage=LEVERAGE,
                    max_notional=capacity,
                    min_notional=5.0,
                )
            except ValueError as exc:
                return [
                    self._record_order(
                        time=time,
                        role="PRIMARY",
                        action="AVERAGE_PRIMARY",
                        executed=False,
                        reason=f"ORDER_REJECTED:{exc}",
                        margin=margin,
                        context=context,
                    )
                ]
            self.averaging_count += 1
            self._transition(time, "PRIMARY_AVERAGED", "AVERAGE_FILLED")
            if self.futures.hedge is not None:
                self._transition(time, "HEDGED", "AVERAGE_WITH_HEDGE")
            child = self.futures.primary.metadata["children"][-1]
            return [
                self._record_order(
                    time=time,
                    role="PRIMARY",
                    action="AVERAGE_PRIMARY",
                    executed=True,
                    reason="FILLED",
                    margin=margin,
                    quantity=child["filled_notional"] / mark,
                    notional=child["filled_notional"],
                    fee=child["filled_notional"] * TAKER_FEE_PER_SIDE,
                    context=context,
                )
            ]
        elif action == "REDUCE_POSITION":
            if self.futures.primary is None:
                return [
                    self._record_order(
                        time=time,
                        role="PRIMARY",
                        action="REDUCE_POSITION",
                        executed=False,
                        reason="NO_PRIMARY",
                    )
                ]
            position = self.futures.primary
            remaining_notional = position.quantity * mark * 0.5
            fraction = 1.0 if remaining_notional < 5.0 else 0.5
            trade = self.futures.reduce_position(
                "PRIMARY",
                time=time,
                price=mark,
                fraction=fraction,
                slippage=SLIPPAGE_PER_SIDE,
                fee_rate=TAKER_FEE_PER_SIDE,
                reason="AI_REDUCE",
            )
            self.trades.append(trade)
            if self.futures.primary is None:
                self.primary_cycle_count += 1
                self.clear_risk_cycle(time, "EXITED", "AI_REDUCE")
                self._spot_swing(time, mark, spot_price, 0)
            return [
                self._record_order(
                    time=time,
                    role="PRIMARY",
                    action="REDUCE_POSITION",
                    executed=True,
                    reason="FILLED",
                    margin=float(trade["margin"]),
                    quantity=float(trade["quantity"]),
                    notional=float(trade["quantity"]) * float(trade["exit_fill"]),
                    fee=float(trade["exit_fee"]),
                )
            ]
        elif action == "EXIT":
            before = len(self.order_trace)
            exit_reason = execution_reason or "AI_EXIT"
            if (
                exit_reason.startswith("RISK_")
                and self.lifecycle_state != "RISK_EXIT"
            ):
                self._transition(time, "RISK_EXIT", exit_reason)
            self._close(
                "HEDGE",
                time,
                mark,
                f"{exit_reason}_HEDGE",
                spot_price,
            )
            self._close("PRIMARY", time, mark, exit_reason, spot_price)
            if len(self.order_trace) == before:
                return [
                    self._record_order(
                        time=time,
                        role="ALL",
                        action="EXIT",
                        executed=False,
                        reason="NO_POSITION",
                    )
                ]
            return self.order_trace[before:]
        elif action in {"SKIP", "HOLD"}:
            return []
        return [
            self._record_order(
                time=time,
                role="ALL",
                action=action,
                executed=False,
                reason="UNKNOWN_ACTION",
            )
        ]

    def apply_funding(self, mark: float, rate: float) -> None:
        if self.futures.primary is not None or self.futures.hedge is not None:
            self.futures.apply_funding(mark, rate)

    def enforce_liquidation(
        self,
        time: pd.Timestamp,
        high: float,
        low: float,
        close: float,
    ) -> list[str]:
        roles: list[str] = []
        for role in ("PRIMARY", "HEDGE"):
            position = self.futures.primary if role == "PRIMARY" else self.futures.hedge
            if position is None:
                continue
            liquidation_price = position.liquidation_price(
                MAINTENANCE_MARGIN_RATE,
                TAKER_FEE_PER_SIDE,
            )
            if (position.side > 0 and low <= liquidation_price) or (
                position.side < 0 and high >= liquidation_price
            ):
                roles.append(role)
        for role in roles:
            position = self.futures.primary if role == "PRIMARY" else self.futures.hedge
            if position is None:
                continue
            liquidation_price = position.liquidation_price(
                MAINTENANCE_MARGIN_RATE,
                TAKER_FEE_PER_SIDE,
            )
            trade = self.futures.liquidate(
                role,
                time=time,
                liquidation_price=liquidation_price,
                liquidation_fee_rate=LIQUIDATION_FEE_RATE,
            )
            trade["cycle_id"] = self.cycle_id
            self.trades.append(trade)
            self._record_order(
                time=time,
                role=role,
                action="LIQUIDATE",
                executed=True,
                reason="LIQUIDATED",
                margin=float(trade["margin"]),
                quantity=float(trade["quantity"]),
                notional=float(trade["quantity"]) * float(trade["exit_fill"]),
                fee=float(trade["exit_fee"]),
            )
            if role == "PRIMARY":
                self.primary_cycle_count += 1
                self.clear_risk_cycle(time, "LIQUIDATED", "LIQUIDATED")
            elif self.futures.primary is not None:
                self._transition(time, "PRIMARY_OPEN", "HEDGE_LIQUIDATED")
            self.liquidation_count += 1
        return roles

    def record_equity(
        self,
        time: pd.Timestamp,
        mark: float,
        spot_mark: float | None = None,
    ) -> None:
        spot_price = float(mark if spot_mark is None else spot_mark)
        self.futures_peak = max(
            self.peak_futures_equity,
            self.futures.equity(mark),
        )
        self.peak_futures_equity = self.futures_peak
        self.equity_rows.append(
            {
                "time": time,
                "equity": self.equity(mark, spot_price),
                "spot_equity": self.spot.equity(spot_price),
                "futures_equity": self.futures.equity(mark),
                "free_collateral": self.futures.free_collateral,
                "used_margin": self.futures.margin_used(),
            }
        )


def _indicator_score(row: pd.Series) -> float:
    score = 0.0
    mappings = (
        ("1H.DMA_3X3_V1.DISTANCE_PRICE_DMA_PCT", 1.0),
        ("4H.DMA_3X3_V1.DISTANCE_PRICE_DMA_PCT", 1.5),
        ("1H.MACD_12_26_9_V1.histogram", 2.0),
        ("4H.MACD_12_26_9_V1.histogram", 3.0),
    )
    for column, weight in mappings:
        value = row.get(column)
        if pd.notna(value):
            score += weight * np.tanh(float(value))
    for timeframe, weight in (("1H", 0.1), ("4H", 0.15)):
        k = row.get(f"{timeframe}.STOCH_14_3_3_V1.k")
        d = row.get(f"{timeframe}.STOCH_14_3_3_V1.d")
        if pd.notna(k) and pd.notna(d):
            score += weight * np.tanh(float(k) - float(d))
    adx = row.get("1H.ADX_14_V1.adx")
    if pd.notna(adx) and float(adx) < 18.0:
        score *= 0.25
    return score


def _max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    drawdown = (peak - equity) / peak.replace(0, np.nan)
    return float(drawdown.max()) if drawdown.notna().any() else 0.0


def _allowed_actions(
    account: PolicyAccount,
    *,
    hedge_enabled: bool = True,
) -> list[str]:
    primary = account.futures.primary
    hedge = account.futures.hedge
    if primary is None:
        return ["OPEN_LONG", "OPEN_SHORT", "HOLD", "SKIP"]
    actions = ["HOLD", "REDUCE_POSITION", "EXIT"]
    if hedge_enabled:
        actions.append("OPEN_HEDGE" if hedge is None else "CLOSE_HEDGE")
    if primary.additions < 2:
        actions.append("AVERAGE_PRIMARY")
    return actions


def _compact_market_event(event: MarketEvent) -> dict[str, Any]:
    return {
        "time": event.time,
        "event_type": event.event_type,
        "priority": event.priority,
        "status": event.status,
        "crossed_level": event.crossed_level,
        "position_state": event.position_state,
        "features": event.features,
        "signature": event.signature,
        "requires_qwen": event.requires_qwen,
        "suppression_reason": event.suppression_reason,
    }


def _run_policy(
    *,
    name: str,
    split_name: str,
    frame: pd.DataFrame,
    spot_fraction: float,
    spot_mode: str,
    funding_by_time: dict[pd.Timestamp, float],
    entry_probabilities: np.ndarray | None,
    risk_predictions: np.ndarray | None,
    management_general: np.ndarray | None,
    management_model: CatBoostClassifier | None,
    management_feature_names: list[str] | None,
    management_state_columns: list[str] | None,
    qwen_adapter: Any | None = None,
    qwen_interval_hours: int = 168,
    qwen_max_requests: int = 64,
    qwen_context: dict[str, Any] | None = None,
    event_monitor: EventMonitor | None = None,
    hedge_enabled: bool = True,
) -> PolicyResult:
    account = PolicyAccount(spot_fraction, spot_mode)
    first = frame.iloc[0]
    first_spot_open = (
        float(first["spot_open"])
        if "spot_open" in first and pd.notna(first["spot_open"])
        else float(first["open"])
    )
    if spot_mode == "HOLD":
        fees_before = account.spot.fees_paid
        eth_before = account.spot.eth
        spent = account.spot.buy_to_target(
            first_spot_open,
            account.spot.cash,
            fee_rate=TAKER_FEE_PER_SIDE,
            slippage=SLIPPAGE_PER_SIDE,
        )
        account.spot_slippage += spent * SLIPPAGE_PER_SIDE
        account.spot_trade_count += int(spent > 0)
        if spent > 0:
            account._record_order(
                time=pd.Timestamp(first["open_time"]),
                role="SPOT",
                action="SPOT_BUY",
                executed=True,
                reason="INITIAL_HOLD",
                quantity=account.spot.eth - eth_before,
                notional=spent,
                fee=account.spot.fees_paid - fees_before,
            )
    pending_action = "SKIP"
    pending_action_reason = "AI_EXIT"
    pending_decision_at: pd.Timestamp | None = None
    pending_decision_price: float | None = None
    pending_trace_index: int | None = None
    last_qwen_at: pd.Timestamp | None = None
    qwen_request_count = 0
    qwen_valid_count = 0
    qwen_fallback_count = 0
    qwen_action_changes = 0
    for index, row in frame.reset_index(drop=True).iterrows():
        execution_time = pd.Timestamp(row["open_time"])
        decision_at = pd.Timestamp(row["decision_at"])
        open_price = float(row["open"])
        close_price = float(row["close"])
        spot_open_price = (
            float(row["spot_open"])
            if "spot_open" in row and pd.notna(row["spot_open"])
            else open_price
        )
        spot_close_price = (
            float(row["spot_close"])
            if "spot_close" in row and pd.notna(row["spot_close"])
            else close_price
        )
        if pending_action != "SKIP":
            before_execution = account.state_snapshot(
                open_price,
                execution_time,
                spot_open_price,
            )
            orders = account.execute(
                pending_action,
                time=execution_time,
                mark=open_price,
                volume=float(row["volume"]),
                spot_mark=spot_open_price,
                execution_reason=pending_action_reason,
            )
            after_execution = account.state_snapshot(
                open_price,
                execution_time,
                spot_open_price,
            )
            account.decisions.append(
                {
                    "time": execution_time,
                    "decision_time": pending_decision_at,
                    "execution_time": execution_time,
                    "action": pending_action,
                    "decision_price": pending_decision_price,
                    "execution_price": open_price,
                    "executed": int(any(order["executed"] for order in orders)),
                    "order_reasons": ";".join(
                        str(order["reason"]) for order in orders
                    ),
                    "state_before": before_execution["state"],
                    "state_after": after_execution["state"],
                    "cycle_id": account.cycle_id,
                    "lifecycle_state": account.lifecycle_state,
                    "execution_reason": pending_action_reason,
                    "strategy": name,
                }
            )
            if pending_trace_index is not None:
                account.action_trace[pending_trace_index].update(
                    {
                        "execution_time": execution_time.isoformat(),
                        "execution_price": open_price,
                        "state_before_execution": before_execution,
                        "state_after_execution": after_execution,
                        "cycle_id": account.cycle_id,
                        "lifecycle_state": account.lifecycle_state,
                        "orders": orders,
                        "order_reasons": [
                            str(order["reason"]) for order in orders
                        ],
                    }
                )
            pending_action = "SKIP"
            pending_decision_at = None
            pending_decision_price = None
            pending_trace_index = None
            pending_action_reason = "AI_EXIT"
        funding = funding_by_time.get(execution_time)
        if funding is not None:
            account.apply_funding(open_price, funding)
        liquidated_roles = account.enforce_liquidation(
            decision_at,
            float(row["high"]),
            float(row["low"]),
            close_price,
        )

        state = account.state_features(
            close_price,
            decision_at,
            spot_close_price,
        )
        risk_metrics = account.risk_metrics(close_price, spot_close_price)
        futures_drawdown = risk_metrics["futures_drawdown_fraction"]
        trace_index = len(account.action_trace)
        hard_risk_reason: str | None = (
            "LIQUIDATION_EVENT"
            if liquidated_roles
            and (
                account.futures.primary is not None
                or account.futures.hedge is not None
            )
            else None
        )
        if hard_risk_reason is None and (
            account.futures.primary is not None
            and (
                futures_drawdown > MAX_THESIS_LOSS_FRACTION
                or state["liquidation_distance_pct"] < 0.02
            )
        ):
            hard_risk_reason = (
                "RISK_DRAWDOWN_LIMIT"
                if futures_drawdown > MAX_THESIS_LOSS_FRACTION
                else "LIQUIDATION_BUFFER_LIMIT"
            )
        account.action_trace.append(
            {
                "decision_time": decision_at.isoformat(),
                "strategy": name,
                "state_at_decision": account.state_snapshot(
                    close_price,
                    decision_at,
                    spot_close_price,
                ),
                "futures_drawdown_fraction": futures_drawdown,
                "risk_cycle_id": account.risk_cycle_id,
                "risk_baseline_equity": risk_metrics["risk_baseline_equity"],
                "risk_peak_futures_equity": risk_metrics[
                    "risk_peak_futures_equity"
                ],
                "hard_risk_reason": hard_risk_reason,
                "catboost_action": None,
                "catboost_probabilities": None,
                "qwen_action": None,
                "qwen_valid": None,
                "qwen_confidence": None,
                "qwen_error": None,
                "allowed_actions": None,
                "applied_action": None,
                "selection_source": None,
                "market_event_types": [],
                "execution_time": None,
                "execution_price": None,
                "state_before_execution": None,
                "state_after_execution": None,
                "orders": None,
                "order_reasons": None,
            }
        )

        catboost_payload: dict[str, Any] = {
            "predicted_downside_24h": (
                float(risk_predictions[index, 0])
                if risk_predictions is not None
                else None
            ),
            "predicted_upside_24h": (
                float(risk_predictions[index, 1])
                if risk_predictions is not None
                else None
            ),
        }
        catboost_action = "SKIP"
        catboost_probabilities: dict[str, float] | None = None
        if hard_risk_reason is not None:
            catboost_action = "RISK_EXIT"
        elif name == "SMA_BASELINE":
            direction = 0
            if pd.notna(row.get("sma20")) and pd.notna(row.get("sma50")):
                if close_price > row["sma20"] > row["sma50"]:
                    direction = 1
                elif close_price < row["sma20"] < row["sma50"]:
                    direction = -1
            if account.futures.primary is None and direction:
                pending_action = "OPEN_LONG" if direction > 0 else "OPEN_SHORT"
            elif account.futures.primary is not None and direction == -account.futures.primary.side:
                pending_action = "EXIT"
            else:
                pending_action = "SKIP"
            catboost_action = pending_action
        elif name == "INDICATORS_ONLY":
            score = _indicator_score(row)
            if account.futures.primary is None:
                pending_action = (
                    "OPEN_LONG"
                    if score > 0.35
                    else "OPEN_SHORT"
                    if score < -0.35
                    else "SKIP"
                )
            else:
                pending_action = (
                    "EXIT"
                    if score * account.futures.primary.side < -0.35
                    else "SKIP"
                )
            catboost_action = pending_action
        elif entry_probabilities is not None and account.futures.primary is None:
            long_probability = float(entry_probabilities[index, 1])
            short_probability = float(entry_probabilities[index, 2])
            catboost_payload.update(
                {
                    "long_probability": long_probability,
                    "short_probability": short_probability,
                    "skip_probability": float(entry_probabilities[index, 0]),
                }
            )
            downside, upside = risk_predictions[index]
            if long_probability > 0.55 and downside > -0.08:
                pending_action = "OPEN_LONG"
            elif short_probability > 0.55 and upside < 0.08:
                pending_action = "OPEN_SHORT"
            else:
                pending_action = "SKIP"
            catboost_action = pending_action
        elif management_model is not None and account.futures.primary is not None:
            state_vector = np.array(
                [state[column] for column in management_state_columns],
                dtype=np.float32,
            )
            model_input = np.concatenate(
                [management_general[index], state_vector]
            ).reshape(1, -1)
            probabilities = management_model.predict_proba(model_input)[0]
            probability_by_action = dict(zip(ACTION_NAMES, probabilities))
            catboost_probabilities = {
                key: float(value) for key, value in probability_by_action.items()
            }
            catboost_payload["management_probabilities"] = probability_by_action
            allowed = {"HOLD", "REDUCE_POSITION", "EXIT"}
            if account.futures.primary is not None and account.futures.primary.additions < 2:
                allowed.add("AVERAGE_PRIMARY")
            if hedge_enabled:
                if account.futures.hedge is None:
                    allowed.add("OPEN_HEDGE")
                else:
                    allowed.add("CLOSE_HEDGE")
            if name == "AI_NO_HEDGE":
                allowed -= {"OPEN_HEDGE", "CLOSE_HEDGE", "AVERAGE_PRIMARY"}
            elif name == "AI_HEDGE":
                allowed -= {"AVERAGE_PRIMARY"}
            action = max(allowed, key=lambda item: probability_by_action[item])
            pending_action = {
                "HOLD": "SKIP",
                "OPEN_HEDGE": "OPEN_HEDGE",
                "CLOSE_HEDGE": "CLOSE_HEDGE",
                "AVERAGE_PRIMARY": "AVERAGE_PRIMARY",
                "REDUCE_POSITION": "REDUCE_POSITION",
                "EXIT": "EXIT",
            }[action]
            catboost_action = pending_action
        else:
            pending_action = "SKIP"
            catboost_action = pending_action

        if (
            catboost_action == "OPEN_HEDGE"
            and account.futures.primary is not None
            and account.futures.hedge is None
        ):
            account.hedge_signal_count += 1
        account.action_trace[trace_index]["catboost_action"] = catboost_action
        account.action_trace[trace_index]["catboost_probabilities"] = (
            catboost_probabilities
        )
        catboost_payload["selected_action"] = catboost_action

        qwen_trigger_events: list[MarketEvent] = []
        should_call_qwen = False
        risk_preempted = hard_risk_reason is not None
        if event_monitor is not None:
            position_state = account.position_state()
            observed_events = event_monitor.observe(
                time=decision_at,
                row=row,
                position_state=position_state,
                primary_side=(
                    account.futures.primary.side
                    if account.futures.primary is not None
                    else 0
                ),
                primary_entry=(
                    account.futures.primary.average_entry
                    if account.futures.primary is not None
                    else None
                ),
                primary_unrealized_fraction=state["primary_unrealized_fraction"],
                averaging_count=(
                    account.futures.primary.additions
                    if account.futures.primary is not None
                    else 0
                ),
                hedge_side=(
                    account.futures.hedge.side
                    if account.futures.hedge is not None
                    else 0
                ),
                hedge_unrealized_fraction=state["hedge_unrealized_fraction"],
                pending_action=pending_action,
                catboost=catboost_payload,
                risk={
                    "risk_limit_fraction": MAX_THESIS_LOSS_FRACTION,
                    "liquidation_distance_pct": state["liquidation_distance_pct"],
                    "free_margin_fraction": state["free_margin_fraction"],
                },
                free_margin_fraction=state["free_margin_fraction"],
                liquidation_distance_fraction=state["liquidation_distance_pct"],
                futures_drawdown_fraction=futures_drawdown,
            )
            account.market_events.extend(event.to_dict() for event in observed_events)
            account.action_trace[trace_index]["market_event_types"] = [
                event.event_type
                for event in observed_events
                if event.status == "TRIGGERED"
            ]
            emergency_events = EventMonitor.emergency(observed_events)
            if emergency_events:
                pending_action = "EXIT"
                catboost_action = "RISK_EXIT"
                hard_risk_reason = emergency_events[0].event_type
                risk_preempted = True
                should_call_qwen = False
            elif qwen_adapter is not None:
                qwen_trigger_events = EventMonitor.triggered_for_qwen(observed_events)
                should_call_qwen = bool(qwen_trigger_events)
        elif (
            qwen_adapter is not None
            and qwen_request_count < qwen_max_requests
            and (
                last_qwen_at is None
                or decision_at - last_qwen_at
                >= pd.Timedelta(hours=qwen_interval_hours)
            )
            and (account.futures.primary is not None or pending_action != "SKIP")
        ):
            should_call_qwen = True

        if risk_preempted:
            pending_action = "EXIT"
            pending_action_reason = hard_risk_reason or "RISK_EXIT"
            account._transition(
                decision_at,
                "RISK_EXIT",
                pending_action_reason,
            )
            should_call_qwen = False
            account.action_trace[trace_index].update(
                {
                    "applied_action": "EXIT",
                    "selection_source": "RISK_ENGINE",
                    "allowed_actions": [],
                    "qwen_action": None,
                    "qwen_valid": None,
                    "qwen_confidence": None,
                    "qwen_error": "QWEN_BYPASSED_RISK_ENGINE",
                }
            )
        elif should_call_qwen and qwen_adapter is not None:
            market_features = {
                key: float(row[key])
                for key in (
                    "sma20",
                    "sma50",
                    "1H.DMA_3X3_V1.DISTANCE_PRICE_DMA_PCT",
                    "4H.DMA_3X3_V1.DISTANCE_PRICE_DMA_PCT",
                    "1H.MACD_12_26_9_V1.histogram",
                    "4H.MACD_12_26_9_V1.histogram",
                    "1H.STOCH_14_3_3_V1.k",
                    "1H.STOCH_14_3_3_V1.d",
                    "4H.STOCH_14_3_3_V1.k",
                    "4H.STOCH_14_3_3_V1.d",
                    "1H.ADX_14_V1.adx",
                    "1H.ATR_14_V1.atr",
                    "1H.ATR_14_V1.atr_norm",
                )
                if key in row and pd.notna(row[key])
            }
            current_risk = account.current_risk(close_price)
            positions_payload = account.state_snapshot(
                close_price,
                decision_at,
                spot_close_price,
            )
            portfolio_payload = {
                **(qwen_context or {}),
                "position_state": account.position_state(),
                "hedge_open": account.futures.hedge is not None,
                "current_price": close_price,
                "spot": {
                    "fraction": state["spot_fraction"],
                    "exposure_fraction": state["spot_exposure_fraction"],
                },
                "primary": positions_payload["primary"],
                "hedge": positions_payload["hedge"],
                "gross_exposure_fraction": state["gross_exposure_fraction"],
                "net_exposure_fraction": state["net_exposure_fraction"],
                "free_margin_fraction": state["free_margin_fraction"],
                "used_margin": positions_payload["used_margin"],
                "liquidation_distance_pct": state["liquidation_distance_pct"],
                "averaging_count": state["averaging_count"],
                "holding_hours": state["holding_hours"],
                "fees_cumulative": state["fees_cumulative"],
                "funding_cumulative": state["funding_cumulative"],
                "remaining_thesis_risk_fraction": state[
                    "remaining_thesis_risk_fraction"
                ],
            }
            allowed_actions = _allowed_actions(
                account,
                hedge_enabled=hedge_enabled,
            )
            decision = qwen_adapter.decide(
                decision_at=decision_at.isoformat(),
                market_features=market_features,
                catboost=catboost_payload,
                portfolio_state=portfolio_payload,
                risk={
                    "risk_limit_fraction": MAX_THESIS_LOSS_FRACTION,
                    "futures_drawdown_fraction": futures_drawdown,
                    "liquidation_distance_pct": state["liquidation_distance_pct"],
                    "free_margin_fraction": state["free_margin_fraction"],
                    "remaining_thesis_risk_fraction": state[
                        "remaining_thesis_risk_fraction"
                    ],
                    "current_worst_loss_fraction": current_risk[
                        "worst_loss_fraction"
                    ],
                    "current_total_portfolio_loss_fraction": current_risk[
                        "worst_total_portfolio_loss_fraction"
                    ],
                    "current_total_portfolio_passes": current_risk[
                        "total_portfolio_passes"
                    ],
                },
                fallback_action=pending_action,
                market_events=[
                    _compact_market_event(event)
                    for event in qwen_trigger_events
                ],
                allowed_actions=allowed_actions,
            )
            qwen_request_count += 1
            last_qwen_at = decision_at
            applied_action = pending_action
            reason = None
            if decision.valid and decision.confidence >= 0.55:
                allowed = set(allowed_actions)
                if decision.action in allowed:
                    applied_action = (
                        "SKIP" if decision.action in {"HOLD", "SKIP"} else decision.action
                    )
                    qwen_valid_count += 1
                else:
                    reason = "QWEN_ACTION_INAPPLICABLE_TO_STATE"
                    qwen_fallback_count += 1
            else:
                reason = (
                    decision.validation_error
                    if not decision.valid
                    else "QWEN_CONFIDENCE_BELOW_0.55"
                )
                qwen_fallback_count += 1
            if applied_action != pending_action:
                qwen_action_changes += 1
            pending_action = applied_action
            pending_action_reason = (
                f"QWEN_{decision.action}"
                if applied_action != catboost_action
                else f"CATBOOST_{catboost_action}"
            )
            account.qwen_events.append(
                {
                    "time": decision_at,
                    "decision_time": decision_at,
                    "request_id": decision.request_hash,
                    "qwen_action": decision.action,
                    "qwen_direction": decision.direction,
                    "qwen_confidence": decision.confidence,
                    "qwen_valid": decision.valid,
                    "fallback_used": decision.fallback_used,
                    "validation_error": decision.validation_error,
                    "catboost_action": catboost_action,
                    "allowed_actions": allowed_actions,
                    "applied_action": applied_action,
                    "application_reason": reason,
                    "latency_seconds": decision.latency_seconds,
                }
            )
            account.action_trace[trace_index].update(
                {
                    "qwen_action": decision.action,
                    "qwen_valid": decision.valid,
                    "qwen_confidence": decision.confidence,
                    "qwen_error": decision.validation_error,
                    "allowed_actions": allowed_actions,
                    "applied_action": applied_action,
                    "selection_source": (
                        "QWEN"
                        if applied_action != catboost_action
                        else "CATBOOST"
                    ),
                }
            )
        elif not risk_preempted:
            pending_action_reason = f"CATBOOST_{catboost_action}"
            account.action_trace[trace_index].update(
                {
                    "applied_action": pending_action,
                    "selection_source": "POLICY",
                    "allowed_actions": _allowed_actions(
                        account,
                        hedge_enabled=hedge_enabled,
                    ),
                }
            )
        if pending_action != "SKIP":
            pending_decision_at = decision_at
            pending_decision_price = close_price
            pending_trace_index = trace_index
            account.action_trace[trace_index]["selected_execution_time"] = (
                pd.Timestamp(frame.iloc[index + 1]["open_time"]).isoformat()
                if index + 1 < len(frame)
                else None
            )
            if pending_action == "OPEN_HEDGE":
                account.hedge_proposed_count += 1
            account.action_trace[trace_index]["execution_reason"] = (
                pending_action_reason
            )
        account.record_equity(
            decision_at,
            close_price,
            spot_close_price,
        )

    last = frame.iloc[-1]
    final_time = pd.Timestamp(last["decision_at"])
    final_mark = float(last["close"])
    final_spot_mark = (
        float(last["spot_close"])
        if "spot_close" in last and pd.notna(last["spot_close"])
        else final_mark
    )
    account._close("HEDGE", final_time, final_mark, "RUN_END", final_spot_mark)
    account._close("PRIMARY", final_time, final_mark, "RUN_END", final_spot_mark)
    if pending_trace_index is not None:
        account.action_trace[pending_trace_index].update(
            {
                "execution_time": None,
                "order_reasons": ["PENDING_AT_RUN_END"],
            }
        )
    account.record_equity(final_time, final_mark, final_spot_mark)
    equity = (
        pd.DataFrame(account.equity_rows)
        .drop_duplicates("time", keep="last")
        .sort_values("time")
    )
    trades = pd.DataFrame(account.trades)
    decisions = pd.DataFrame(account.decisions)
    qwen_events = pd.DataFrame(account.qwen_events)
    market_events = pd.DataFrame(account.market_events)
    order_trace = pd.DataFrame(account.order_trace)
    action_trace = pd.DataFrame(account.action_trace)
    lifecycle_events = pd.DataFrame(account.lifecycle_events)
    final_equity = float(equity.iloc[-1]["equity"])
    executed_orders = (
        order_trace.loc[order_trace["executed"] == 1].copy()
        if not order_trace.empty
        else pd.DataFrame()
    )
    operation_counts = (
        executed_orders.groupby(["role", "action"]).size().to_dict()
        if not executed_orders.empty
        else {}
    )
    operation_counts = {
        f"{role}:{action}": int(count)
        for (role, action), count in operation_counts.items()
    }
    turnover_by_operation = (
        executed_orders.groupby(["role", "action"])["notional"].sum().to_dict()
        if not executed_orders.empty
        else {}
    )
    turnover_by_operation = {
        f"{role}:{action}": float(value)
        for (role, action), value in turnover_by_operation.items()
    }
    fees_by_operation = (
        executed_orders.groupby(["role", "action"])["fee"].sum().to_dict()
        if not executed_orders.empty
        else {}
    )
    fees_by_operation = {
        f"{role}:{action}": float(value)
        for (role, action), value in fees_by_operation.items()
    }
    hedge_rejections = (
        order_trace.loc[
            (order_trace["role"] == "HEDGE")
            & (order_trace["action"] == "OPEN_HEDGE")
            & (order_trace["executed"] == 0),
            "reason",
        ]
        .value_counts()
        .to_dict()
        if not order_trace.empty
        else {}
    )
    hedge_rejection_reasons = {
        str(reason): int(count)
        for reason, count in hedge_rejections.items()
    }
    metrics = {
        "strategy": name,
        "hedge_enabled": hedge_enabled,
        "split": split_name,
        "spot_fraction": spot_fraction,
        "spot_mode": spot_mode,
        "initial_capital": INITIAL_CAPITAL,
        "final_equity": final_equity,
        "return_percent": (final_equity / INITIAL_CAPITAL - 1.0) * 100.0,
        "max_drawdown": _max_drawdown(equity["equity"]),
        "liquidations": account.liquidation_count,
        "risk_exit_count": int(
            (
                (
                    (trades["role"] == "PRIMARY")
                    & trades["reason"]
                    .astype(str)
                    .str.startswith(("RISK_", "LIQUIDATION_BUFFER"))
                )
            ).sum()
        )
        if not trades.empty
        else 0,
        "lifecycle_transition_counts": (
            lifecycle_events["state"].value_counts().to_dict()
            if not lifecycle_events.empty
            else {}
        ),
        "hedges": account.hedge_count,
        "averaging_count": account.averaging_count,
        "trade_count": len(trades) + account.spot_trade_count,
        "primary_executed_orders": int(
            (
                (executed_orders["role"] == "PRIMARY")
                if not executed_orders.empty
                else pd.Series(dtype=bool)
            ).sum()
        ),
        "hedge_executed_orders": int(
            (
                (executed_orders["role"] == "HEDGE")
                if not executed_orders.empty
                else pd.Series(dtype=bool)
            ).sum()
        ),
        "spot_executed_orders": int(
            (
                (executed_orders["role"] == "SPOT")
                if not executed_orders.empty
                else pd.Series(dtype=bool)
            ).sum()
        ),
        "executed_order_count": account.executed_order_count,
        "completed_trade_cycles": account.primary_cycle_count,
        "total_notional_turnover": account.total_notional_turnover,
        "operation_counts": operation_counts,
        "turnover_by_operation": turnover_by_operation,
        "fees_by_operation": fees_by_operation,
        "hedge_signal_count": account.hedge_signal_count,
        "hedge_proposed_count": account.hedge_proposed_count,
        "hedge_approved_count": account.hedge_approved_count,
        "hedge_rejected_count": account.hedge_rejected_count,
        "hedge_filled_count": account.hedge_filled_count,
        "hedge_closed_count": account.hedge_closed_count,
        "hedge_rejection_reasons": hedge_rejection_reasons,
        "order_rejection_count": len(account.order_rejections),
        "spot_trade_count": account.spot_trade_count,
        "decision_count": len(decisions),
        "fees": (
            account.futures.entry_fees
            + account.futures.exit_fees
            + account.spot.fees_paid
        ),
        "funding": account.futures.funding_costs,
        "slippage": account.futures.slippage_costs + account.spot_slippage,
        "realized_primary": account.futures.realized_primary,
        "realized_hedge": account.futures.realized_hedge,
        "qwen_requests": qwen_request_count,
        "qwen_valid": qwen_valid_count,
        "qwen_fallbacks": qwen_fallback_count,
        "qwen_action_changes": qwen_action_changes,
        "market_events_detected": int(
            (market_events["status"] == "TRIGGERED").sum()
        )
        if not market_events.empty
        else 0,
        "market_events_suppressed": int(
            (market_events["status"] == "SUPPRESSED").sum()
        )
        if not market_events.empty
        else 0,
        "risk_events": int(
            market_events["event_type"]
            .str.startswith(("RISK_", "LIQUIDATION_"))
            .sum()
        )
        if not market_events.empty
        else 0,
        "hedge_open_events": account.hedge_signal_count,
        "hedge_close_events": int(
            (market_events["event_type"] == "HEDGE_CLOSE_FAVORABLE").sum()
        )
        if not market_events.empty
        else 0,
    }
    return PolicyResult(
        name=name,
        split_name=split_name,
        spot_fraction=spot_fraction,
        spot_mode=spot_mode,
        equity=equity,
        trades=trades,
        decisions=decisions,
        metrics=metrics,
        qwen_events=qwen_events,
        market_events=market_events,
        order_trace=order_trace,
        action_trace=action_trace,
        lifecycle_events=lifecycle_events,
    )


def run_backtests(
    dataset_root: Path,
    training_root: Path,
    output_root: Path,
    *,
    enable_qwen: bool = False,
    qwen_interval_hours: int = 168,
    qwen_max_requests: int = 64,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    bundle = load_bundle(dataset_root)
    metrics = json.loads((training_root / "training_metrics_v1.json").read_text())
    policy_descriptor = {
        "entry_model_sha256": metrics["entry"]["model_sha256"],
        "risk_model_sha256": metrics["risk"]["model_sha256"],
        "management_model_sha256": metrics["management"]["model_sha256"],
        "entry_probability_threshold": 0.55,
        "max_thesis_loss_fraction": MAX_THESIS_LOSS_FRACTION,
        "leverage": LEVERAGE,
        "taker_fee_per_side": TAKER_FEE_PER_SIDE,
        "slippage_per_side": SLIPPAGE_PER_SIDE,
        "actions": list(ACTION_NAMES),
    }
    policy_sha = hashlib.sha256(
        json.dumps(policy_descriptor, sort_keys=True).encode("utf-8")
    ).hexdigest()
    policy_descriptor["policy_sha256"] = policy_sha
    (output_root / "policy_manifest_v1.json").write_text(
        json.dumps(policy_descriptor, indent=2),
        encoding="utf-8",
    )
    selection_manifest = json.loads(
        (training_root / "feature_selection_manifest_v1.json").read_text()
    )
    entry_model = CatBoostClassifier()
    entry_model.load_model(training_root / "entry_direction_gpu_v1.cbm")
    risk_model = CatBoostRegressor()
    risk_model.load_model(training_root / "entry_risk_gpu_v1.cbm")
    management_model = CatBoostClassifier()
    management_model.load_model(training_root / "position_management_gpu_v1.cbm")

    all_row_ids = bundle.rows["row_id"].to_numpy()
    entry_matrix, entry_names = build_matrix(
        bundle,
        selection_manifest["entry"],
        row_ids=all_row_ids,
    )
    if entry_names != metrics["features"]:
        # CatBoost validates feature names only when provided; positional order is
        # the frozen manifest order, so keep the matrix untouched.
        pass
    entry_probabilities = entry_model.predict_proba(entry_matrix)
    risk_predictions = risk_model.predict(entry_matrix)
    management_general, management_general_names = build_matrix(
        bundle,
        selection_manifest["management"],
        row_ids=all_row_ids,
    )
    management_features = metrics["management"]["features"]
    management_state_columns = selection_manifest["management_state_features"]

    frame = bundle.features[
        [
            "row_id",
            "decision_at",
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "sma20",
            "sma50",
            "1H.DMA_3X3_V1.DISTANCE_PRICE_DMA_PCT",
            "4H.DMA_3X3_V1.DISTANCE_PRICE_DMA_PCT",
            "1H.MACD_12_26_9_V1.histogram",
            "4H.MACD_12_26_9_V1.histogram",
            "1H.STOCH_14_3_3_V1.k",
            "1H.STOCH_14_3_3_V1.d",
            "4H.STOCH_14_3_3_V1.k",
            "4H.STOCH_14_3_3_V1.d",
            "1H.ADX_14_V1.adx",
        ]
    ].copy()
    funding = pd.read_parquet(
        Path(
            "/var/tmp/traiding_pilot_ui_workspace/"
            "capital_growth_experiment_v1/data/funding_ETHUSDT.parquet"
        )
    )
    funding["funding_time"] = pd.to_datetime(funding["funding_time"], utc=True)
    funding_by_time = {
        pd.Timestamp(row.funding_time): float(row.funding_rate)
        for row in funding.itertuples(index=False)
        if pd.notna(row.funding_rate)
    }
    splits = {
        "RUN1": frame[
            (frame["decision_at"] >= pd.Timestamp(RUN1_START))
            & (frame["decision_at"] < pd.Timestamp(RUN1_END))
        ],
        "RUN2": frame[
            (frame["decision_at"] >= pd.Timestamp(RUN2_START))
            & (frame["decision_at"] < pd.Timestamp(RUN2_END))
        ],
    }
    results: list[PolicyResult] = []
    for split_name, split_frame in splits.items():
        row_ids = split_frame["row_id"].to_numpy()
        split_entry = entry_probabilities[row_ids]
        split_risk = risk_predictions[row_ids]
        split_management = management_general[row_ids]
        for spot_fraction in SPOT_FRACTIONS:
            results.append(
                _run_policy(
                    name="BUY_HOLD",
                    split_name=split_name,
                    frame=split_frame,
                    spot_fraction=spot_fraction,
                    spot_mode="HOLD",
                    funding_by_time=funding_by_time,
                    entry_probabilities=None,
                    risk_predictions=None,
                    management_general=None,
                    management_model=None,
                    management_feature_names=None,
                    management_state_columns=None,
                )
            )
            results.append(
                _run_policy(
                    name="SMA_BASELINE",
                    split_name=split_name,
                    frame=split_frame,
                    spot_fraction=spot_fraction,
                    spot_mode="HOLD",
                    funding_by_time=funding_by_time,
                    entry_probabilities=None,
                    risk_predictions=None,
                    management_general=None,
                    management_model=None,
                    management_feature_names=None,
                    management_state_columns=None,
                )
            )
            results.append(
                _run_policy(
                    name="INDICATORS_ONLY",
                    split_name=split_name,
                    frame=split_frame,
                    spot_fraction=spot_fraction,
                    spot_mode="HOLD",
                    funding_by_time=funding_by_time,
                    entry_probabilities=None,
                    risk_predictions=None,
                    management_general=None,
                    management_model=None,
                    management_feature_names=None,
                    management_state_columns=None,
                )
            )
            for variant in AI_VARIANTS:
                for spot_mode in SPOT_MODES:
                    results.append(
                        _run_policy(
                            name=variant,
                            split_name=split_name,
                            frame=split_frame,
                            spot_fraction=spot_fraction,
                            spot_mode=spot_mode,
                            funding_by_time=funding_by_time,
                            entry_probabilities=split_entry,
                            risk_predictions=split_risk,
                            management_general=split_management,
                            management_model=management_model,
                            management_feature_names=management_features,
                            management_state_columns=management_state_columns,
                        )
                    )
            if enable_qwen:
                qwen_log = (
                    output_root
                    / f"qwen_requests_{split_name}_{int(spot_fraction * 100)}_HOLD.jsonl"
                )
                qwen_adapter = QwenPolicyAdapter(
                    config=QwenConfig(model_id="qwen2.5:7b"),
                    log_path=qwen_log,
                )
                qwen_context = {
                    "run": split_name,
                    "spot_fraction": spot_fraction,
                    "spot_mode": "HOLD",
                }
                common = {
                    "split_name": split_name,
                    "frame": split_frame,
                    "spot_fraction": spot_fraction,
                    "spot_mode": "HOLD",
                    "funding_by_time": funding_by_time,
                    "entry_probabilities": split_entry,
                    "risk_predictions": split_risk,
                    "management_general": split_management,
                    "management_model": management_model,
                    "management_feature_names": management_features,
                    "management_state_columns": management_state_columns,
                }
                results.append(
                    _run_policy(
                        name="CATBOOST_ONLY",
                        qwen_adapter=None,
                        qwen_interval_hours=qwen_interval_hours,
                        qwen_max_requests=qwen_max_requests,
                        qwen_context=qwen_context,
                        **common,
                    )
                )
                results.append(
                    _run_policy(
                        name="CATBOOST_PLUS_QWEN",
                        qwen_adapter=qwen_adapter,
                        qwen_interval_hours=qwen_interval_hours,
                        qwen_max_requests=qwen_max_requests,
                        qwen_context=qwen_context,
                        **common,
                    )
                )
    if enable_qwen:
        identity_adapter = QwenPolicyAdapter(
            config=QwenConfig(model_id="qwen2.5:7b"),
            log_path=output_root / "qwen_identity_probe.jsonl",
        )
        qwen_identity = identity_adapter.runtime_identity()
        (output_root / "qwen_runtime_identity_v1.json").write_text(
            json.dumps(qwen_identity, indent=2),
            encoding="utf-8",
        )
        policy_descriptor.update(
            {
                "qwen_model_id": qwen_identity["model_id"],
                "qwen_model_digest": qwen_identity["digest"],
                "qwen_runtime": qwen_identity["runtime"],
                "qwen_interval_hours": qwen_interval_hours,
                "qwen_max_requests_per_variant": qwen_max_requests,
            }
        )
        policy_sha = hashlib.sha256(
            json.dumps(policy_descriptor, sort_keys=True).encode("utf-8")
        ).hexdigest()
        policy_descriptor["policy_sha256"] = policy_sha
        (output_root / "policy_manifest_v1.json").write_text(
            json.dumps(policy_descriptor, indent=2),
            encoding="utf-8",
        )
    metrics_frame = pd.DataFrame([result.metrics for result in results])
    metrics_frame.to_csv(output_root / "portfolio_metrics_v1.csv", index=False)
    for result in results:
        safe = f"{result.split_name}_{result.name}_{int(result.spot_fraction * 100)}_{result.spot_mode}"
        result.equity.to_parquet(output_root / f"{safe}_equity.parquet", index=False)
        result.trades.to_csv(output_root / f"{safe}_trades.csv", index=False)
        result.decisions.to_csv(output_root / f"{safe}_decisions.csv", index=False)
        result.order_trace.to_csv(
            output_root / f"{safe}_order_trace.csv",
            index=False,
        )
        result.action_trace.to_csv(
            output_root / f"{safe}_action_trace.csv",
            index=False,
        )
        result.lifecycle_events.to_csv(
            output_root / f"{safe}_lifecycle_events.csv",
            index=False,
        )
        if not result.qwen_events.empty:
            result.qwen_events.to_csv(
                output_root / f"{safe}_qwen_events.csv",
                index=False,
            )
        if not result.market_events.empty:
            result.market_events.to_csv(
                output_root / f"{safe}_market_events.csv",
                index=False,
            )
    summary = {
        "status": "PASS",
        "policy_sha256": policy_sha,
        "policy_manifest": str(output_root / "policy_manifest_v1.json"),
        "run1_interval": [str(RUN1_START), str(RUN1_END)],
        "run2_interval": [str(RUN2_START), str(RUN2_END)],
        "results": metrics_frame.to_dict(orient="records"),
        "qwen_models": metrics_frame.loc[
            metrics_frame["strategy"] == "CATBOOST_PLUS_QWEN",
            [
                "split",
                "spot_fraction",
                "final_equity",
                "qwen_requests",
                "qwen_valid",
                "qwen_fallbacks",
                "qwen_action_changes",
            ],
        ].to_dict(orient="records")
        if enable_qwen
        else [],
        "oos_opened": "NO",
        "live_trading": "NO",
    }
    (output_root / "backtest_summary_v1.json").write_text(
        json.dumps(summary, indent=2, default=str),
        encoding="utf-8",
    )
    return summary


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--training-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--enable-qwen", action="store_true")
    parser.add_argument("--qwen-interval-hours", type=int, default=168)
    parser.add_argument("--qwen-max-requests", type=int, default=64)
    args = parser.parse_args()
    print(
        json.dumps(
            run_backtests(
                args.dataset_root,
                args.training_root,
                args.output_root,
                enable_qwen=args.enable_qwen,
                qwen_interval_hours=args.qwen_interval_hours,
                qwen_max_requests=args.qwen_max_requests,
            ),
            indent=2,
        )
    )
