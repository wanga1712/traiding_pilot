"""Parameter grid search for classic ZigZag vs expert gold."""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Any, Callable, Iterable

from crypto_trading_bot.research_v2.zigzag.classic import (
    ZigZagPivot,
    classic_absolute_zigzag,
    classic_atr_zigzag,
    classic_percent_zigzag,
)
from crypto_trading_bot.research_v2.zigzag.match import MatchResult, align_chronological, score_tuple


PERCENT_DEVIATIONS = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0)
DEPTHS = (1, 2, 3, 5, 8, 10, 12, 16, 20, 24, 30, 40)
BACKSTEPS = (0, 1, 2, 3, 5, 8, 10)

# Absolute deviations in USD for ETH 4H (secondary)
ABS_DEVIATIONS = (10, 15, 20, 25, 30, 40, 50, 75, 100, 150, 200, 300)
ATR_MULTS = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0)


@dataclass(frozen=True)
class ZigZagParams:
    kind: str  # percent | absolute | atr
    deviation: float
    depth: int
    backstep: int

    def label(self) -> str:
        return f"{self.kind}:dev={self.deviation}:depth={self.depth}:backstep={self.backstep}"


def run_zigzag(candles: list[dict], params: ZigZagParams) -> list[ZigZagPivot]:
    if params.kind == "percent":
        return classic_percent_zigzag(
            candles,
            deviation_percent=params.deviation,
            depth=params.depth,
            backstep=params.backstep,
        )
    if params.kind == "absolute":
        return classic_absolute_zigzag(
            candles,
            deviation_abs=params.deviation,
            depth=params.depth,
            backstep=params.backstep,
        )
    if params.kind == "atr":
        return classic_atr_zigzag(
            candles,
            atr_mult=params.deviation,
            depth=params.depth,
            backstep=params.backstep,
        )
    raise ValueError(f"unknown zigzag kind: {params.kind}")


def evaluate_params(
    candles: list[dict],
    expert_points: list[dict],
    params: ZigZagParams,
    *,
    max_bar_error: int = 3,
    max_price_error_pct: float = 1.5,
) -> tuple[MatchResult, list[ZigZagPivot]]:
    pivots = run_zigzag(candles, params)
    # Restrict zigzags to expert time window (+ margin) for fair EXTRA count.
    if expert_points:
        lo = min(int(p["bar_index"]) for p in expert_points) - max_bar_error - 2
        hi = max(int(p["bar_index"]) for p in expert_points) + max_bar_error + 2
        pivots = [z for z in pivots if lo <= z.index <= hi]
    matched = align_chronological(
        expert_points,
        pivots,
        max_bar_error=max_bar_error,
        max_price_error_pct=max_price_error_pct,
    )
    return matched, pivots


def iter_percent_grid(
    deviations: Iterable[float] = PERCENT_DEVIATIONS,
    depths: Iterable[int] = DEPTHS,
    backsteps: Iterable[int] = BACKSTEPS,
) -> Iterable[ZigZagParams]:
    for d, depth, back in product(deviations, depths, backsteps):
        if back > depth * 2:
            continue
        yield ZigZagParams("percent", float(d), int(depth), int(back))


def iter_absolute_grid(
    deviations: Iterable[float] = ABS_DEVIATIONS,
    depths: Iterable[int] = (1, 2, 3, 5, 8, 12, 16, 24),
    backsteps: Iterable[int] = (0, 1, 2, 3, 5),
) -> Iterable[ZigZagParams]:
    for d, depth, back in product(deviations, depths, backsteps):
        yield ZigZagParams("absolute", float(d), int(depth), int(back))


def iter_atr_grid(
    mults: Iterable[float] = ATR_MULTS,
    depths: Iterable[int] = (1, 2, 3, 5, 8, 12, 16),
    backsteps: Iterable[int] = (0, 1, 2, 3, 5),
) -> Iterable[ZigZagParams]:
    for d, depth, back in product(mults, depths, backsteps):
        yield ZigZagParams("atr", float(d), int(depth), int(back))


def grid_search(
    candles: list[dict],
    expert_discovery: list[dict],
    param_iter: Iterable[ZigZagParams],
    *,
    max_bar_error: int = 3,
    max_price_error_pct: float = 1.5,
    progress_every: int = 200,
    on_progress: Callable[[int, ZigZagParams, MatchResult], None] | None = None,
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for i, params in enumerate(param_iter, start=1):
        result, pivots = evaluate_params(
            candles,
            expert_discovery,
            params,
            max_bar_error=max_bar_error,
            max_price_error_pct=max_price_error_pct,
        )
        row = {
            "params": params,
            "label": params.label(),
            "zigzag_count": len(pivots),
            "result": result,
            "score": score_tuple(result, len(pivots), len(expert_discovery)),
        }
        ranked.append(row)
        if on_progress and (i % progress_every == 0):
            on_progress(i, params, result)
    ranked.sort(key=lambda r: r["score"])
    return ranked


def neighborhood_params(best: ZigZagParams) -> list[ZigZagParams]:
    """Nearby parameter neighborhood for stability check."""
    out: list[ZigZagParams] = []
    if best.kind == "percent":
        devs = [best.deviation + d for d in (-0.25, -0.125, 0.0, 0.125, 0.25) if best.deviation + d > 0]
        depths = sorted({max(1, best.depth + d) for d in (-2, -1, 0, 1, 2)})
        backs = sorted({max(0, best.backstep + d) for d in (-1, 0, 1)})
    elif best.kind == "absolute":
        step = max(5.0, best.deviation * 0.1)
        devs = [best.deviation + d * step for d in (-2, -1, 0, 1, 2) if best.deviation + d * step > 0]
        depths = sorted({max(1, best.depth + d) for d in (-2, -1, 0, 1, 2)})
        backs = sorted({max(0, best.backstep + d) for d in (-1, 0, 1)})
    else:
        step = 0.25
        devs = [best.deviation + d * step for d in (-2, -1, 0, 1, 2) if best.deviation + d * step > 0]
        depths = sorted({max(1, best.depth + d) for d in (-2, -1, 0, 1, 2)})
        backs = sorted({max(0, best.backstep + d) for d in (-1, 0, 1)})
    for d, depth, back in product(devs, depths, backs):
        out.append(ZigZagParams(best.kind, float(d), int(depth), int(back)))
    # unique
    seen = set()
    uniq = []
    for p in out:
        key = (p.kind, p.deviation, p.depth, p.backstep)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    return uniq


def assess_stability(
    candles: list[dict],
    expert_discovery: list[dict],
    best: ZigZagParams,
    best_f1: float,
    *,
    max_bar_error: int = 3,
    max_price_error_pct: float = 1.5,
    f1_drop_threshold: float = 0.08,
) -> dict[str, Any]:
    rows = []
    for params in neighborhood_params(best):
        result, pivots = evaluate_params(
            candles,
            expert_discovery,
            params,
            max_bar_error=max_bar_error,
            max_price_error_pct=max_price_error_pct,
        )
        rows.append(
            {
                "label": params.label(),
                "f1": result.f1,
                "precision": result.precision,
                "recall": result.recall,
                "median_bar_error": result.median_bar_error,
                "extra": result.extra,
                "zigzag_count": len(pivots),
            }
        )
    f1s = [r["f1"] for r in rows]
    min_f1 = min(f1s) if f1s else 0.0
    stable = (best_f1 - min_f1) <= f1_drop_threshold and min_f1 >= max(0.0, best_f1 - f1_drop_threshold)
    return {
        "status": "STABLE" if stable else "UNSTABLE",
        "best_f1": best_f1,
        "neighborhood_min_f1": min_f1,
        "neighborhood_max_f1": max(f1s) if f1s else 0.0,
        "f1_drop_threshold": f1_drop_threshold,
        "samples": rows,
    }
