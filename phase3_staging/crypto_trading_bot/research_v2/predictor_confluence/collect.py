"""Collect predictor snapshot without modifying inverse mathematics."""
from __future__ import annotations

from typing import Any, Sequence

from crypto_trading_bot.research_v2.inverse_predictors.engine import predict
from crypto_trading_bot.research_v2.inverse_predictors.registry import PARAMETER_REGISTRY as PRED_PARAMS
from crypto_trading_bot.research_v2.inverse_predictors.state import assert_no_forbidden, build_state
from crypto_trading_bot.research_v2.inverse_predictors.types import PredictorResult
from crypto_trading_bot.research_v2.inverse_predictors.version import PREDICTOR_ENGINE_VERSION

from .types import TriggerPoint
from .version import FAMILY_BY_PREDICTOR_PREFIX, FORBIDDEN_INPUT_KEYS, VALID_SOLUTION_STATUSES


def family_of(predictor_id: str) -> str:
    for prefix, fam in FAMILY_BY_PREDICTOR_PREFIX.items():
        if predictor_id.startswith(prefix):
            return fam
    return "OTHER"


def assert_no_forbidden_bars(bars: Sequence[dict[str, Any]]) -> None:
    keys = set()
    for b in list(bars)[:80]:
        keys.update(b.keys())
    bad = keys & FORBIDDEN_INPUT_KEYS
    if bad:
        raise ValueError(f"forbidden fields in confluence inputs: {sorted(bad)}")
    assert_no_forbidden(bars)


def _flatten_results(res: PredictorResult | list[PredictorResult]) -> list[PredictorResult]:
    if isinstance(res, list):
        return res
    return [res]


# Baseline predictor sets used for confluence (skip unsupported bollinger).
DEFAULT_PREDICTOR_SETS = [
    ps
    for ps, meta in PRED_PARAMS.items()
    if meta.get("status") != "UNSUPPORTED_V1" and meta.get("predictor_id") != "BOLLINGER_BAND_INVERSE"
]


def collect_predictor_results(
    bars: Sequence[dict[str, Any]],
    *,
    timeframe: str,
    decision_time: Any,
    parameter_set_ids: Sequence[str] | None = None,
) -> tuple[list[PredictorResult], dict[str, int], float, float | None]:
    """Return all results + status counts + current_price + atr."""
    assert_no_forbidden_bars(bars)
    ids = list(parameter_set_ids or DEFAULT_PREDICTOR_SETS)
    results: list[PredictorResult] = []
    for ps in ids:
        try:
            results.extend(_flatten_results(predict(bars, parameter_set_id=ps, source_timeframe=timeframe, decision_time=decision_time)))
        except Exception:  # noqa: BLE001 — treat engine errors as insufficient
            continue
    counts = {
        "TOTAL_PREDICTORS": len(results),
        "VALID_TRIGGER_COUNT": 0,
        "INVALID_TRIGGER_COUNT": 0,
        "ALREADY_TRIGGERED_COUNT": 0,
        "AMBIGUOUS_COUNT": 0,
        "UNSUPPORTED_COUNT": 0,
        "REQUIRES_INTRABAR_COUNT": 0,
        "INSUFFICIENT_HISTORY_COUNT": 0,
        "NO_FINITE_SOLUTION_COUNT": 0,
    }
    for r in results:
        st = r.solution_status
        if st in VALID_SOLUTION_STATUSES and r.predicted_trigger_price is not None:
            counts["VALID_TRIGGER_COUNT"] += 1
        else:
            counts["INVALID_TRIGGER_COUNT"] += 1
        if st == "ALREADY_TRIGGERED":
            counts["ALREADY_TRIGGERED_COUNT"] += 1
        elif st == "AMBIGUOUS":
            counts["AMBIGUOUS_COUNT"] += 1
        elif st == "UNSUPPORTED_V1":
            counts["UNSUPPORTED_COUNT"] += 1
        elif st == "REQUIRES_INTRABAR_ASSUMPTION":
            counts["REQUIRES_INTRABAR_COUNT"] += 1
        elif st == "INSUFFICIENT_HISTORY":
            counts["INSUFFICIENT_HISTORY_COUNT"] += 1
        elif st == "NO_FINITE_SOLUTION":
            counts["NO_FINITE_SOLUTION_COUNT"] += 1
    state = build_state(bars, decision_time=decision_time, timeframe=timeframe)
    price = state.current_price if state else (float(results[0].current_price) if results else float("nan"))
    atr = state.atr14 if state else None
    return results, counts, price, atr


def to_trigger_points(
    results: list[PredictorResult],
    *,
    current_price: float,
    atr: float | None,
) -> list[TriggerPoint]:
    out: list[TriggerPoint] = []
    for r in results:
        if r.solution_status not in VALID_SOLUTION_STATUSES or r.predicted_trigger_price is None:
            continue
        p = float(r.predicted_trigger_price)
        signed_abs = p - current_price
        signed_pct = (signed_abs / current_price * 100.0) if current_price else 0.0
        signed_atr = (signed_abs / atr) if atr else None
        out.append(
            TriggerPoint(
                predictor_id=r.predictor_id,
                parameter_set_id=r.parameter_set_id,
                family=family_of(r.predictor_id),
                timeframe=r.source_timeframe,
                price=p,
                signed_distance_abs=signed_abs,
                signed_distance_pct=signed_pct,
                signed_distance_atr=signed_atr,
                direction_required=r.direction_required,
                solution_status=r.solution_status,
            )
        )
    return out


def family_normalize_nearest(triggers: list[TriggerPoint]) -> list[TriggerPoint]:
    """One vote per family: keep trigger nearest to market (|signed_distance_pct|)."""
    best: dict[str, TriggerPoint] = {}
    for t in triggers:
        key = t.family
        if key not in best or abs(t.signed_distance_pct) < abs(best[key].signed_distance_pct):
            best[key] = t
    return list(best.values())
