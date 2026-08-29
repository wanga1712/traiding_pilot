"""Deterministic 1D adjacent-gap clustering of trigger prices."""
from __future__ import annotations

from dataclasses import dataclass

from .types import TriggerPoint


@dataclass
class Cluster:
    members: list[TriggerPoint]

    @property
    def size(self) -> int:
        return len(self.members)

    @property
    def center(self) -> float:
        return sum(m.price for m in self.members) / len(self.members)

    @property
    def width_abs(self) -> float:
        prices = [m.price for m in self.members]
        return max(prices) - min(prices)

    @property
    def families(self) -> set[str]:
        return {m.family for m in self.members}

    @property
    def timeframes(self) -> set[str]:
        return {m.timeframe for m in self.members}


def cluster_triggers(
    triggers: list[TriggerPoint],
    *,
    threshold_pct: float | None = None,
    threshold_atr: float | None = None,
    atr: float | None = None,
    current_price: float,
) -> list[Cluster]:
    """
    Sort by price; adjacent points join if gap <= pct threshold of mid
    OR (if ATR threshold set) gap <= threshold_atr * atr.
    Either criterion may join when both provided (OR).
    """
    if not triggers:
        return []
    ordered = sorted(triggers, key=lambda t: t.price)
    clusters: list[Cluster] = [Cluster([ordered[0]])]
    for t in ordered[1:]:
        prev = clusters[-1].members[-1]
        gap = abs(t.price - prev.price)
        mid = (t.price + prev.price) / 2.0
        join = False
        if threshold_pct is not None and mid > 0:
            join = join or (gap / mid * 100.0 <= threshold_pct)
        if threshold_atr is not None and atr and atr > 0:
            join = join or (gap / atr <= threshold_atr)
        if join:
            clusters[-1].members.append(t)
        else:
            clusters.append(Cluster([t]))
    return clusters


def nearest_cluster(clusters: list[Cluster], current_price: float) -> Cluster | None:
    if not clusters:
        return None
    return min(clusters, key=lambda c: abs(c.center - current_price))


def densest_cluster(clusters: list[Cluster]) -> Cluster | None:
    if not clusters:
        return None
    # prefer larger size; tie-break narrower width
    return max(clusters, key=lambda c: (c.size, -c.width_abs))
