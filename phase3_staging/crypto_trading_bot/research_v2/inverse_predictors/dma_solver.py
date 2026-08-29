"""DMA / SMA analytic inverse: X = mean of last (N-1) closes."""
from __future__ import annotations

import numpy as np

from .result_utils import make_result
from .state import CausalState
from .types import PredictorResult


FORMULA_DMA = (
    "For N-SMA, SMA_next=(S+X)/N with S=sum(last N-1 closes). "
    "X=SMA_next iff X=S/(N-1). Display displacement does not change availability."
)


def solve_dma_cross(
    state: CausalState,
    *,
    period: int,
    display_shift: int,
    direction: str,  # UP | DOWN
    predictor_id: str,
    parameter_set_id: str,
    source_timeframe: str,
) -> PredictorResult:
    if len(state.closes) < period:
        return make_result(
            predictor_id=predictor_id,
            parameter_set_id=parameter_set_id,
            source_timeframe=source_timeframe,
            decision_time=state.decision_time,
            calculated_at=state.calculated_at,
            current_price=state.current_price,
            trigger_price=None,
            direction_required=direction,
            trigger_definition=f"price_cross_{direction.lower()}_dma_{period}x{display_shift}",
            solution_status="INSUFFICIENT_HISTORY",
            atr=state.atr14,
            formula_note=FORMULA_DMA,
        )
    # last N-1 closes including current
    window = state.closes[-(period - 1) :]
    if len(window) != period - 1:
        return make_result(
            predictor_id=predictor_id,
            parameter_set_id=parameter_set_id,
            source_timeframe=source_timeframe,
            decision_time=state.decision_time,
            calculated_at=state.calculated_at,
            current_price=state.current_price,
            trigger_price=None,
            direction_required=direction,
            trigger_definition=f"price_cross_{direction.lower()}_dma",
            solution_status="INSUFFICIENT_HISTORY",
            atr=state.atr14,
        )
    threshold = float(np.sum(window) / (period - 1))
    # current SMA for already-triggered check
    sma_now = float(np.mean(state.closes[-period:]))
    price = state.current_price
    if direction == "UP":
        if price > sma_now:
            status = "ALREADY_TRIGGERED"
        else:
            status = "EXACT_ANALYTIC"
        # cross up: need X > threshold (strict); report equality as trigger touch
        trig = threshold
        dir_req = "UP"
    else:
        if price < sma_now:
            status = "ALREADY_TRIGGERED"
        else:
            status = "EXACT_ANALYTIC"
        trig = threshold
        dir_req = "DOWN"
    return make_result(
        predictor_id=predictor_id,
        parameter_set_id=parameter_set_id,
        source_timeframe=source_timeframe,
        decision_time=state.decision_time,
        calculated_at=state.calculated_at,
        current_price=price,
        trigger_price=trig,
        direction_required=dir_req,
        trigger_definition=f"NEXT_CLOSE causes price {'>' if direction=='UP' else '<'} SMA({period}); display_shift={display_shift}",
        solution_status=status,
        atr=state.atr14,
        formula_note=FORMULA_DMA,
        details={"sma_now": sma_now, "threshold_X": threshold, "display_shift": display_shift},
    )
