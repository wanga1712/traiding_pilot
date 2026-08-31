"""DNO OB/OS analytic inverse predictor — segment-safe adapter for INVERSE_PREDICTOR_ENGINE_V1."""
from __future__ import annotations

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.bars import BarArrays
from crypto_trading_bot.research_v2.indicator_engine.volatility import compute_atr_series
from crypto_trading_bot.research_v2.oscillator_predictor.inverse import (
    INSUFFICIENT_CONTIGUOUS_HISTORY,
    price_for_next_detrended_value_segment_safe,
)

from .result_utils import make_result
from .state import CausalState
from .types import PredictorResult


def segment_safe_atr14(state: CausalState) -> float | None:
    """Segment-aware ATR14 at decision bar — does not use cross-gap state.atr14."""
    arrays = BarArrays(
        state.open_times,
        state.close_times,
        state.closes,
        state.highs,
        state.lows,
        state.closes,
        state.volumes,
        state.gap_flags,
    )
    samples = compute_atr_series(arrays, period=14)
    if not samples:
        return None
    last = samples[-1]
    if not last.valid or last.values.get("atr") is None:
        return None
    return float(last.values["atr"])


def solve_dno_level(
    state: CausalState,
    *,
    period: int,
    target_level: float,
    predictor_id: str,
    parameter_set_id: str,
    source_timeframe: str,
    band: str,
    gap_flags: np.ndarray,
) -> PredictorResult:
    idx = len(state.closes) - 1
    atr = segment_safe_atr14(state)
    trigger, status = price_for_next_detrended_value_segment_safe(
        state.closes,
        gap_flags,
        idx,
        period=period,
        target_oscillator_value=target_level,
    )
    if status == INSUFFICIENT_CONTIGUOUS_HISTORY:
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
            solution_status=INSUFFICIENT_CONTIGUOUS_HISTORY,
            atr=atr,
        )
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
        atr=atr,
        formula_note="P=(N*D_TARGET+S)/(N-1) segment-safe adapter",
    )
