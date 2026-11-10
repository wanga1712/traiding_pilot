"""Historical capital-growth simulation with isolated primary and hedge positions."""

from .config import ExecutionConfig, PortfolioConfig, RiskConfig, StrategyConfig
from .simulator import SimulationResult, simulate_portfolio

__all__ = [
    "ExecutionConfig",
    "PortfolioConfig",
    "RiskConfig",
    "StrategyConfig",
    "SimulationResult",
    "simulate_portfolio",
]
