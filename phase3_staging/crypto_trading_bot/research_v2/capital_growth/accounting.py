from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class Position:
    role: str
    side: int
    entry_time: pd.Timestamp
    quantity: float
    margin: float
    average_entry: float
    entry_fees: float = 0.0
    funding_costs: float = 0.0
    realized_gross: float = 0.0
    realized_net: float = 0.0
    additions: int = 0
    metadata: dict = field(default_factory=dict)

    def unrealized(self, mark: float) -> float:
        return self.side * self.quantity * (float(mark) - self.average_entry)

    def notional(self, mark: float) -> float:
        return self.quantity * abs(float(mark))

    def liquidation_price(self, maintenance_rate: float, fee_buffer: float) -> float:
        if self.side > 0:
            return self.average_entry * (1.0 - 1.0 / self.metadata["leverage"] + maintenance_rate + fee_buffer)
        return self.average_entry * (1.0 + 1.0 / self.metadata["leverage"] - maintenance_rate - fee_buffer)

    def add(
        self,
        *,
        quantity: float,
        price: float,
        margin: float,
        fee: float,
        time: pd.Timestamp,
    ) -> None:
        total_quantity = self.quantity + quantity
        self.average_entry = (self.average_entry * self.quantity + float(price) * quantity) / total_quantity
        self.quantity = total_quantity
        self.margin += float(margin)
        self.entry_fees += float(fee)
        self.additions += 1
        self.metadata.setdefault("add_times", []).append(str(time))


@dataclass
class SpotAccount:
    cash: float
    eth: float = 0.0
    cost_basis: float = 0.0
    fees_paid: float = 0.0
    realized_net: float = 0.0

    def equity(self, price: float) -> float:
        return self.cash + self.eth * float(price)

    def buy_to_target(self, price: float, target_value: float, *, fee_rate: float, slippage: float) -> float:
        current = self.eth * float(price)
        delta = max(0.0, float(target_value) - current)
        spend = min(delta, self.cash)
        if spend <= 0:
            return 0.0
        fill = float(price) * (1.0 + slippage)
        fee = spend * fee_rate
        qty = max(0.0, spend - fee) / fill
        self.cash -= spend
        self.eth += qty
        self.cost_basis += spend
        self.fees_paid += fee
        return spend

    def sell_to_target(self, price: float, target_value: float, *, fee_rate: float, slippage: float) -> float:
        current = self.eth * float(price)
        delta = max(0.0, current - float(target_value))
        if delta <= 0 or self.eth <= 0:
            return 0.0
        qty = min(self.eth, delta / float(price))
        basis_removed = self.cost_basis * (qty / self.eth) if self.eth > 0 else 0.0
        fill = float(price) * (1.0 - slippage)
        proceeds = qty * fill
        fee = proceeds * fee_rate
        self.eth -= qty
        self.cost_basis = max(0.0, self.cost_basis - basis_removed)
        self.cash += proceeds - fee
        self.fees_paid += fee
        self.realized_net += proceeds - fee - basis_removed
        return proceeds

    def average_cost(self) -> float:
        if self.eth <= 0:
            return 0.0
        return self.cost_basis / self.eth


@dataclass
class FuturesAccount:
    free_collateral: float
    primary: Position | None = None
    hedge: Position | None = None
    realized_primary: float = 0.0
    realized_hedge: float = 0.0
    entry_fees: float = 0.0
    exit_fees: float = 0.0
    funding_costs: float = 0.0
    slippage_costs: float = 0.0
    liquidation_fees: float = 0.0

    def equity(self, mark: float) -> float:
        value = self.free_collateral
        for position in (self.primary, self.hedge):
            if position is not None:
                value += position.margin + position.unrealized(mark)
        return value

    def margin_used(self) -> float:
        return sum(p.margin for p in (self.primary, self.hedge) if p is not None)

    def gross_notional(self, mark: float) -> float:
        return sum(p.notional(mark) for p in (self.primary, self.hedge) if p is not None)

    def net_notional(self, mark: float) -> float:
        return sum(p.side * p.notional(mark) for p in (self.primary, self.hedge) if p is not None)

    def open_position(
        self,
        role: str,
        *,
        side: int,
        time: pd.Timestamp,
        price: float,
        margin: float,
        slippage: float,
        fee_rate: float,
        leverage: float,
    ) -> Position:
        if margin <= 0 or margin > self.free_collateral + 1e-12:
            raise ValueError("insufficient free collateral")
        fill = float(price) * (1.0 + side * slippage)
        notional = float(margin) * float(leverage)
        quantity = notional / fill
        fee = notional * fee_rate
        if fee > self.free_collateral - margin + 1e-12:
            raise ValueError("insufficient collateral for entry fee")
        self.free_collateral -= margin + fee
        self.slippage_costs += notional * slippage
        self.entry_fees += fee
        position = Position(
            role=role,
            side=int(side),
            entry_time=pd.Timestamp(time),
            quantity=quantity,
            margin=float(margin),
            average_entry=fill,
            entry_fees=fee,
            metadata={"leverage": float(leverage)},
        )
        if role == "PRIMARY":
            self.primary = position
        elif role == "HEDGE":
            self.hedge = position
        else:
            raise ValueError(f"unknown role: {role}")
        return position

    def average_primary(
        self,
        *,
        time: pd.Timestamp,
        price: float,
        margin: float,
        slippage: float,
        fee_rate: float,
        leverage: float,
    ) -> None:
        if self.primary is None:
            raise ValueError("no primary position")
        if margin <= 0 or margin > self.free_collateral + 1e-12:
            raise ValueError("insufficient free collateral for averaging")
        fill = float(price) * (1.0 + self.primary.side * slippage)
        notional = float(margin) * float(leverage)
        quantity = notional / fill
        fee = notional * fee_rate
        self.free_collateral -= margin + fee
        self.slippage_costs += notional * slippage
        self.entry_fees += fee
        self.primary.add(quantity=quantity, price=fill, margin=margin, fee=fee, time=time)

    def apply_funding(self, mark: float, rate: float) -> float:
        total_cost = 0.0
        for position in (self.primary, self.hedge):
            if position is None:
                continue
            cost = position.side * float(rate) * position.notional(mark)
            self.free_collateral -= cost
            position.funding_costs += cost
            self.funding_costs += cost
            total_cost += cost
        return total_cost

    def close_position(
        self,
        role: str,
        *,
        time: pd.Timestamp,
        price: float,
        slippage: float,
        fee_rate: float,
        reason: str,
    ) -> dict:
        position = self.primary if role == "PRIMARY" else self.hedge
        if position is None:
            raise ValueError(f"no {role} position")
        fill = float(price) * (1.0 - position.side * slippage)
        gross = position.side * position.quantity * (fill - position.average_entry)
        exit_fee = position.quantity * fill * fee_rate
        self.free_collateral += position.margin + gross - exit_fee
        self.slippage_costs += position.quantity * float(price) * slippage
        self.exit_fees += exit_fee
        net = gross - position.entry_fees - position.funding_costs - exit_fee
        if role == "PRIMARY":
            self.realized_primary += net
            self.primary = None
        else:
            self.realized_hedge += net
            self.hedge = None
        return {
            "role": role,
            "side": "LONG" if position.side > 0 else "SHORT",
            "entry_time": position.entry_time.isoformat(),
            "exit_time": pd.Timestamp(time).isoformat(),
            "average_entry": position.average_entry,
            "exit_fill": fill,
            "quantity": position.quantity,
            "margin": position.margin,
            "gross_pnl": gross,
            "net_pnl": net,
            "entry_fees": position.entry_fees,
            "exit_fee": exit_fee,
            "funding_cost": position.funding_costs,
            "reason": reason,
            "additions": position.additions,
        }

    def liquidate(
        self,
        role: str,
        *,
        time: pd.Timestamp,
        liquidation_price: float,
        liquidation_fee_rate: float,
    ) -> dict:
        position = self.primary if role == "PRIMARY" else self.hedge
        if position is None:
            raise ValueError(f"no {role} position")
        gross = position.side * position.quantity * (float(liquidation_price) - position.average_entry)
        liquidation_fee = position.quantity * float(liquidation_price) * liquidation_fee_rate
        self.free_collateral += max(0.0, position.margin + gross - liquidation_fee)
        self.liquidation_fees += liquidation_fee
        net = gross - position.entry_fees - position.funding_costs - liquidation_fee
        if role == "PRIMARY":
            self.realized_primary += net
            self.primary = None
        else:
            self.realized_hedge += net
            self.hedge = None
        return {
            "role": role,
            "side": "LONG" if position.side > 0 else "SHORT",
            "entry_time": position.entry_time.isoformat(),
            "exit_time": pd.Timestamp(time).isoformat(),
            "average_entry": position.average_entry,
            "exit_fill": float(liquidation_price),
            "quantity": position.quantity,
            "margin": position.margin,
            "gross_pnl": gross,
            "net_pnl": net,
            "entry_fees": position.entry_fees,
            "exit_fee": liquidation_fee,
            "funding_cost": position.funding_costs,
            "reason": "LIQUIDATED",
            "additions": position.additions,
        }
