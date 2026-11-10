from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


RUN1_START = datetime(2020, 1, 1, tzinfo=timezone.utc)
RUN1_END = datetime(2021, 1, 1, tzinfo=timezone.utc)
RUN2_START = datetime(2021, 1, 1, tzinfo=timezone.utc)
RUN2_END = datetime(2022, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class StrategyConfig:
    fast_period: int = 20
    slow_period: int = 50
    atr_period: int = 14
    hedge_atr_mult: float = 2.0
    hedge_close_confirmations: int = 1
    averaging_atr_levels: tuple[float, ...] = (2.0, 4.0)
    min_hold_hours: int = 72
    max_hedge_cycles: int = 2
    hedge_fractions: tuple[float, ...] = (1.0, 0.75, 0.5, 0.25)
    primary_risk_headroom_fraction: float = 0.40


@dataclass(frozen=True)
class ExecutionConfig:
    leverage: float = 10.0
    taker_fee_per_side: float = 0.0005
    slippage_per_side: float = 0.0002
    maintenance_margin_rate: float = 0.004
    liquidation_fee_rate: float = 0.0005
    primary_budget_fraction: float = 0.40
    hedge_budget_fraction: float = 0.20
    averaging_budget_fractions: tuple[float, float] = (0.20, 0.20)


@dataclass(frozen=True)
class RiskConfig:
    scenario_moves: tuple[float, ...] = (-0.15, -0.10, -0.08, -0.05, -0.03, 0.03, 0.05, 0.08, 0.10, 0.15)
    max_loss_fraction_total_equity: float = 0.05


@dataclass(frozen=True)
class PortfolioConfig:
    name: str
    spot_fraction: float
    spot_mode: str
    hedge_enabled: bool
    averaging_enabled: bool
    initial_capital: float = 100.0
    strategy: StrategyConfig = StrategyConfig()
    execution: ExecutionConfig = ExecutionConfig()
    risk: RiskConfig = RiskConfig()
    rebalance_after_cycle: bool = True


def portfolio_matrix(initial_capital: float = 100.0) -> list[PortfolioConfig]:
    """Return the predeclared A/B × HOLD/SWING × controls matrix."""
    rows: list[PortfolioConfig] = []
    for split_name, spot_fraction in (("A", 0.60), ("B", 0.40)):
        for spot_mode in ("HOLD", "SWING"):
            for hedge_enabled, averaging_enabled, control_name in (
                (True, True, "HEDGED_AVG"),
                (True, False, "HEDGED_NOAVG"),
                (False, True, "UNHEDGED_AVG"),
            ):
                rows.append(
                    PortfolioConfig(
                        name=f"{split_name}_{spot_mode}_{control_name}",
                        spot_fraction=spot_fraction,
                        spot_mode=spot_mode,
                        hedge_enabled=hedge_enabled,
                        averaging_enabled=averaging_enabled,
                        initial_capital=float(initial_capital),
                    )
                )
    return rows
