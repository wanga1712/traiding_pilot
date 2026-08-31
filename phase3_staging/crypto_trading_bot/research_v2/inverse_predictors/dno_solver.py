"""DNO OB/OS analytic inverse predictor — integrates with INVERSE_PREDICTOR_ENGINE_V1."""
from __future__ import annotations

from crypto_trading_bot.research_v2.oscillator_predictor.inverse import price_for_next_detrended_value

from .result_utils import make_result
from .state import CausalState
from .types import PredictorResult


def solve_dno_level(
    state: CausalState,
    *,
    period: int,
    target_level: float,
    predictor_id: str,
    parameter_set_id: str,
    source_timeframe: str,
    band: str,
) -> PredictorResult:
    if len(state.closes) < period - 1:
        return make_result(
            predictor_id=predictor_id,
            parameter_set_id=parameter_set_id,
            source_timeframe=source_timeframe,
            decision_time=state.decision_time,
            calculated_at=state.calculated_at,
            current_price=state.current_price,
            trigger_price=None,
            direction_required="EITHER",
            trigger_definition=f"DNO_{band}_next_bar",
            solution_status="INSUFFICIENT_HISTORY",
            atr=state.atr14,
        )
    trigger = price_for_next_detrended_value(state.closes, period=period, target_oscillator_value=target_level)
    return make_result(
        predictor_id=predictor_id,
        parameter_set_id=parameter_set_id,
        source_timeframe=source_timeframe,
        decision_time=state.decision_time,
        calculated_at=state.calculated_at,
        current_price=state.current_price,
        trigger_price=trigger,
        direction_required="EITHER",
        trigger_definition=f"Close[t+1] s.t. DNO[t+1]={target_level}",
        solution_status="EXACT_ANALYTIC",
        atr=state.atr14,
        formula_note="P=(N*D_TARGET+S)/(N-1)",
    )
