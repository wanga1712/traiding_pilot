from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import (
    INITIAL_CAPITAL,
    LEVERAGE,
    LIQUIDATION_FEE_RATE,
    MAINTENANCE_MARGIN_RATE,
    MAX_THESIS_LOSS_FRACTION,
    SLIPPAGE_PER_SIDE,
    TAKER_FEE_PER_SIDE,
)


@dataclass
class _Position:
    side: int
    quantity: float
    entry: float
    margin: float
    opened_at: pd.Timestamp
    additions: int = 0
    fees: float = 0.0
    funding: float = 0.0

    def unrealized(self, mark: float) -> float:
        return self.side * self.quantity * (mark - self.entry)

    def liquidation_price(self) -> float:
        risk_rate = MAINTENANCE_MARGIN_RATE + TAKER_FEE_PER_SIDE
        if self.side > 0:
            return max(
                0.0,
                (self.entry * self.quantity - self.margin)
                / (self.quantity * (1.0 + risk_rate)),
            )
        return (self.entry * self.quantity + self.margin) / (
            self.quantity * (1.0 - risk_rate)
        )


@dataclass
class CanonicalPortfolioState:
    spot_fraction: float
    spot_mode: str
    spot_cash: float
    spot_eth: float = 0.0
    futures_cash: float = 0.0
    primary: _Position | None = None
    hedge: _Position | None = None
    realized_primary: float = 0.0
    realized_hedge: float = 0.0
    fees: float = 0.0
    funding: float = 0.0
    cycle_peak_equity: float = INITIAL_CAPITAL
    pending_direction: int = 0

    def __post_init__(self) -> None:
        self.futures_cash = INITIAL_CAPITAL * (1.0 - self.spot_fraction)

    def equity(self, mark: float) -> float:
        value = self.spot_cash + self.spot_eth * mark + self.futures_cash
        for position in (self.primary, self.hedge):
            if position is not None:
                value += position.margin + position.unrealized(mark)
        return float(value)

    def margin_used(self) -> float:
        return sum(
            position.margin
            for position in (self.primary, self.hedge)
            if position is not None
        )

    def _buy_spot(self, mark: float, target_value: float) -> None:
        spend = min(self.spot_cash, max(0.0, target_value - self.spot_eth * mark))
        if spend <= 0:
            return
        fill = mark * (1.0 + SLIPPAGE_PER_SIDE)
        fee = spend * TAKER_FEE_PER_SIDE
        self.spot_cash -= spend
        self.spot_eth += max(0.0, spend - fee) / fill
        self.fees += fee

    def _sell_spot(self, mark: float, target_value: float) -> None:
        current = self.spot_eth * mark
        if current <= target_value or self.spot_eth <= 0:
            return
        quantity = min(self.spot_eth, (current - target_value) / mark)
        proceeds = quantity * mark * (1.0 - SLIPPAGE_PER_SIDE)
        fee = proceeds * TAKER_FEE_PER_SIDE
        self.spot_eth -= quantity
        self.spot_cash += proceeds - fee
        self.fees += fee

    def _risk_margin(self, mark: float) -> float:
        risk_budget = self.equity(mark) * MAX_THESIS_LOSS_FRACTION
        risk_cap_margin = risk_budget / (0.15 * LEVERAGE)
        budget_margin = INITIAL_CAPITAL * (1.0 - self.spot_fraction) * 0.40
        affordable = self.futures_cash / (1.0 + LEVERAGE * TAKER_FEE_PER_SIDE)
        return max(0.0, min(risk_cap_margin, budget_margin, affordable))

    def _open(self, role: str, side: int, mark: float, time: pd.Timestamp, margin: float) -> None:
        if margin <= 0:
            return
        fill = mark * (1.0 + side * SLIPPAGE_PER_SIDE)
        notional = margin * LEVERAGE
        quantity = notional / fill
        fee = notional * TAKER_FEE_PER_SIDE
        if fee > self.futures_cash - margin:
            return
        self.futures_cash -= margin + fee
        self.fees += fee
        position = _Position(side, quantity, fill, margin, time, fees=fee)
        if role == "PRIMARY":
            self.primary = position
        else:
            self.hedge = position

    def _average(self, mark: float, time: pd.Timestamp, margin: float) -> None:
        if self.primary is None or margin <= 0:
            return
        fill = mark * (1.0 + self.primary.side * SLIPPAGE_PER_SIDE)
        notional = margin * LEVERAGE
        quantity = notional / fill
        fee = notional * TAKER_FEE_PER_SIDE
        if fee > self.futures_cash - margin:
            return
        total = self.primary.quantity + quantity
        self.primary.entry = (
            self.primary.entry * self.primary.quantity + fill * quantity
        ) / total
        self.primary.quantity = total
        self.primary.margin += margin
        self.primary.additions += 1
        self.primary.fees += fee
        self.futures_cash -= margin + fee
        self.fees += fee

    def _close(self, role: str, mark: float) -> None:
        position = self.primary if role == "PRIMARY" else self.hedge
        if position is None:
            return
        fill = mark * (1.0 - position.side * SLIPPAGE_PER_SIDE)
        gross = position.side * position.quantity * (fill - position.entry)
        fee = position.quantity * fill * TAKER_FEE_PER_SIDE
        released = max(0.0, position.margin + gross - fee)
        self.futures_cash += released
        self.fees += fee
        net = gross - position.fees - position.funding - fee
        if role == "PRIMARY":
            self.realized_primary += net
            self.primary = None
        else:
            self.realized_hedge += net
            self.hedge = None

    def apply_funding(self, mark: float, rate: float) -> None:
        for position in (self.primary, self.hedge):
            if position is None:
                continue
            cost = position.side * rate * position.quantity * mark
            position.funding += cost
            self.futures_cash -= cost
            self.funding += cost

    def act_at_open(
        self,
        *,
        time: pd.Timestamp,
        mark: float,
        fast: float | None,
        slow: float | None,
        atr: float | None,
    ) -> None:
        direction = self.pending_direction
        if self.spot_mode == "SWING":
            target = self.equity(mark) * self.spot_fraction if direction > 0 else 0.0
            if direction > 0:
                self._buy_spot(mark, target)
            elif direction < 0:
                self._sell_spot(mark, 0.0)

        if self.primary is None:
            if direction != 0:
                margin = self._risk_margin(mark)
                self._open("PRIMARY", direction, mark, time, margin)
            return

        held_hours = (time - self.primary.opened_at).total_seconds() / 3600.0
        adverse = (
            self.primary.entry - mark
            if self.primary.side > 0
            else mark - self.primary.entry
        )
        atr_value = atr if atr is not None and np.isfinite(atr) and atr > 0 else None

        if self.hedge is not None and direction == self.primary.side:
            self._close("HEDGE", mark)
        if (
            self.hedge is None
            and direction == -self.primary.side
            and atr_value is not None
            and adverse >= 2.0 * atr_value
        ):
            hedge_margin = min(
                INITIAL_CAPITAL * (1.0 - self.spot_fraction) * 0.20,
                self.primary.margin,
                self.futures_cash / (1.0 + LEVERAGE * TAKER_FEE_PER_SIDE),
            )
            self._open("HEDGE", direction, mark, time, hedge_margin)

        if (
            self.primary.additions < 2
            and direction == self.primary.side
            and atr_value is not None
            and adverse >= (2.0 if self.primary.additions == 0 else 4.0) * atr_value
            and fast is not None
            and slow is not None
        ):
            reserve = INITIAL_CAPITAL * (1.0 - self.spot_fraction) * 0.20
            self._average(mark, time, min(reserve, self.futures_cash))

        if (
            self.hedge is None
            and direction == -self.primary.side
            and held_hours >= 72.0
        ):
            self._close("PRIMARY", mark)

    def state_features(self, *, mark: float, time: pd.Timestamp) -> dict[str, float]:
        primary = self.primary
        hedge = self.hedge
        equity = self.equity(mark)
        gross = sum(
            position.quantity * mark
            for position in (primary, hedge)
            if position is not None
        )
        net = sum(
            position.side * position.quantity * mark
            for position in (primary, hedge)
            if position is not None
        )
        liquidation_distance = 0.0
        if primary is not None:
            liquidation_distance = abs(mark - primary.liquidation_price()) / mark
        cycle_loss = max(0.0, self.cycle_peak_equity - equity)
        remaining_risk = max(0.0, MAX_THESIS_LOSS_FRACTION - cycle_loss / max(equity, 1e-9))
        return {
            "spot_fraction": self.spot_fraction,
            "spot_mode_code": 1.0 if self.spot_mode == "HOLD" else 0.0,
            "spot_exposure_fraction": self.spot_eth * mark / max(equity, 1e-9),
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
            "free_margin_fraction": self.futures_cash / max(equity, 1e-9),
            "liquidation_distance_pct": liquidation_distance,
            "averaging_count": float(primary.additions) if primary else 0.0,
            "holding_hours": (
                (time - primary.opened_at).total_seconds() / 3600.0
                if primary is not None
                else 0.0
            ),
            "fees_cumulative": self.fees,
            "funding_cumulative": self.funding,
            "remaining_thesis_risk_fraction": remaining_risk,
        }


def build_canonical_state_features(
    *,
    decisions: pd.DataFrame,
    output_root: Path,
    funding: pd.DataFrame,
) -> dict[str, Any]:
    funding_map = {
        pd.Timestamp(row.funding_time): float(row.funding_rate)
        for row in funding.itertuples(index=False)
        if pd.notna(row.funding_rate)
    }
    trackers = {
        f"A_HOLD": CanonicalPortfolioState(0.60, "HOLD", INITIAL_CAPITAL * 0.60),
        f"A_SWING": CanonicalPortfolioState(0.60, "SWING", INITIAL_CAPITAL * 0.60),
        f"B_HOLD": CanonicalPortfolioState(0.40, "HOLD", INITIAL_CAPITAL * 0.40),
        f"B_SWING": CanonicalPortfolioState(0.40, "SWING", INITIAL_CAPITAL * 0.40),
    }
    rows: list[dict[str, Any]] = []
    management_rows: list[dict[str, Any]] = []
    for row in decisions.itertuples(index=False):
        open_time = pd.Timestamp(row.open_time)
        close_time = pd.Timestamp(row.decision_at)
        fast = float(row.sma20) if np.isfinite(row.sma20) else None
        slow = float(row.sma50) if np.isfinite(row.sma50) else None
        atr = float(row.atr14) if np.isfinite(row.atr14) else None
        direction = 0
        if fast is not None and slow is not None:
            if row.close > fast > slow:
                direction = 1
            elif row.close < fast < slow:
                direction = -1
        state_row: dict[str, Any] = {"row_id": int(row.row_id), "decision_at": close_time}
        for name, tracker in trackers.items():
            if open_time in funding_map and (tracker.primary is not None or tracker.hedge is not None):
                tracker.apply_funding(float(row.open), funding_map[open_time])
            tracker.act_at_open(
                time=open_time,
                mark=float(row.open),
                fast=fast,
                slow=slow,
                atr=atr,
            )
            mark = float(row.close)
            tracker.cycle_peak_equity = max(tracker.cycle_peak_equity, tracker.equity(mark))
            snapshot = tracker.state_features(mark=mark, time=close_time)
            state_row.update({f"state_{name}_{key}": value for key, value in snapshot.items()})
            if tracker.primary is not None or tracker.hedge is not None:
                management = {
                    "row_id": int(row.row_id),
                    "decision_at": close_time,
                    "portfolio_variant": name,
                    **snapshot,
                }
                if "fwd_return_24h" in decisions.columns and pd.notna(row.fwd_return_24h):
                    primary = tracker.primary
                    hedge = tracker.hedge
                    fwd = float(row.fwd_return_24h)
                    primary_future = (
                        primary.side * primary.quantity * mark * fwd
                        if primary is not None
                        else 0.0
                    )
                    hedge_future = (
                        hedge.side * hedge.quantity * mark * fwd
                        if hedge is not None
                        else 0.0
                    )
                    hold_utility = primary_future + hedge_future
                    close_cost = (
                        primary.quantity * mark * (TAKER_FEE_PER_SIDE + SLIPPAGE_PER_SIDE)
                        if primary is not None
                        else 0.0
                    ) + (
                        hedge.quantity * mark * (TAKER_FEE_PER_SIDE + SLIPPAGE_PER_SIDE)
                        if hedge is not None
                        else 0.0
                    )
                    primary_risk = float(row.long_risk_limit_hit_24h) if primary is not None and primary.side > 0 else (
                        float(row.short_risk_limit_hit_24h) if primary is not None else 0.0
                    )
                    future_margin = max(0.0, tracker.futures_cash)
                    hedge_margin = min(
                        future_margin,
                        primary.margin if primary is not None else 0.0,
                        INITIAL_CAPITAL * (1.0 - tracker.spot_fraction) * 0.20,
                    )
                    hedge_quantity = hedge_margin * LEVERAGE / mark
                    hedge_side = -primary.side if primary is not None else 0
                    hedge_cost = hedge_quantity * mark * (
                        TAKER_FEE_PER_SIDE + SLIPPAGE_PER_SIDE
                    )
                    average_margin = min(
                        future_margin,
                        INITIAL_CAPITAL * (1.0 - tracker.spot_fraction) * 0.20,
                    )
                    average_quantity = average_margin * LEVERAGE / mark
                    average_cost = average_quantity * mark * (
                        TAKER_FEE_PER_SIDE + SLIPPAGE_PER_SIDE
                    )
                    utilities = {
                        "HOLD": hold_utility - (5.0 * primary_risk),
                        "OPEN_HEDGE": hold_utility
                        + hedge_side * hedge_quantity * mark * fwd
                        - hedge_cost
                        - (5.0 * primary_risk),
                        "AVERAGE_PRIMARY": hold_utility
                        + (primary.side * average_quantity * mark * fwd if primary is not None else 0.0)
                        - average_cost
                        - (5.0 * primary_risk),
                        "REDUCE_POSITION": 0.5 * primary_future
                        - 0.5 * close_cost
                        - (2.5 * primary_risk),
                        "EXIT": -close_cost,
                    }
                    if hedge is not None:
                        utilities["CLOSE_HEDGE"] = -(
                            hedge.quantity
                            * mark
                            * (TAKER_FEE_PER_SIDE + SLIPPAGE_PER_SIDE)
                        )
                    allowed = ["HOLD", "REDUCE_POSITION", "EXIT"]
                    if hedge is None:
                        allowed.append("OPEN_HEDGE")
                    if primary is not None and primary.additions < 2:
                        allowed.append("AVERAGE_PRIMARY")
                    if hedge is not None:
                        allowed.append("CLOSE_HEDGE")
                    for action in (
                        "HOLD",
                        "OPEN_HEDGE",
                        "CLOSE_HEDGE",
                        "AVERAGE_PRIMARY",
                        "REDUCE_POSITION",
                        "EXIT",
                    ):
                        management[f"utility_{action}"] = utilities.get(action, np.nan)
                        management[f"allowed_{action}"] = int(action in allowed)
                    management["best_action"] = max(
                        allowed,
                        key=lambda action: utilities[action],
                    )
                management_rows.append(management)
            tracker.pending_direction = direction
        rows.append(state_row)

    state_frame = pd.DataFrame(rows)
    management = pd.DataFrame(management_rows)
    state_frame.to_parquet(output_root / "portfolio_state_features_v1.parquet", index=False)
    management.to_parquet(output_root / "management_state_samples_v1.parquet", index=False)
    return {
        "rows": len(state_frame),
        "management_state_rows": len(management),
        "variants": list(trackers),
    }
