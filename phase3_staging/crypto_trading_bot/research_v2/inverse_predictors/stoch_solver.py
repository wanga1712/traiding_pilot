"""Stochastic inverse — close-only with explicit point-bar assumption, else REQUIRES_INTRABAR_ASSUMPTION."""
from __future__ import annotations

import numpy as np

from .result_utils import make_result
from .state import CausalState
from .types import PredictorResult

STOCH_NOTE = (
    "Stochastic depends on next high/low. V1 close-only exact solve uses POINT_BAR assumption "
    "(next H=L=X). K/D smoothed cross without H/L is REQUIRES_INTRABAR_ASSUMPTION."
)


def solve_stoch_k_level_point_bar(
    state: CausalState,
    *,
    k_period: int,
    level: float,
    predictor_id: str,
    parameter_set_id: str,
    source_timeframe: str,
) -> PredictorResult:
    """Solve raw %K = level under next bar H=L=X (point candle)."""
    if len(state.closes) < k_period:
        return make_result(
            predictor_id=predictor_id,
            parameter_set_id=parameter_set_id,
            source_timeframe=source_timeframe,
            decision_time=state.decision_time,
            calculated_at=state.calculated_at,
            current_price=state.current_price,
            trigger_price=None,
            direction_required="EITHER",
            trigger_definition=f"raw_%K={level} POINT_BAR",
            solution_status="INSUFFICIENT_HISTORY",
            atr=state.atr14,
            formula_note=STOCH_NOTE,
        )
    # Prior window bars excluding oldest that drops out: use last k_period-1 bars' H/L
    prev_h = state.highs[-(k_period - 1) :]
    prev_l = state.lows[-(k_period - 1) :]
    hh0 = float(np.max(prev_h))
    ll0 = float(np.min(prev_l))
    # Under point bar, hh=max(hh0,X), ll=min(ll0,X).
    # If X in [ll0, hh0], range unchanged: %K=(X-ll0)/(hh0-ll0)*100 → X = ll0 + level/100*(hh0-ll0)
    if hh0 == ll0:
        return make_result(
            predictor_id=predictor_id,
            parameter_set_id=parameter_set_id,
            source_timeframe=source_timeframe,
            decision_time=state.decision_time,
            calculated_at=state.calculated_at,
            current_price=state.current_price,
            trigger_price=None,
            direction_required="EITHER",
            trigger_definition=f"raw_%K={level}",
            solution_status="NO_FINITE_SOLUTION",
            atr=state.atr14,
            formula_note=STOCH_NOTE,
            details={"intrabar_assumption": "POINT_BAR_H_EQ_L_EQ_X"},
        )
    x_interior = ll0 + (level / 100.0) * (hh0 - ll0)
    if ll0 <= x_interior <= hh0:
        return make_result(
            predictor_id=predictor_id,
            parameter_set_id=parameter_set_id,
            source_timeframe=source_timeframe,
            decision_time=state.decision_time,
            calculated_at=state.calculated_at,
            current_price=state.current_price,
            trigger_price=float(x_interior),
            direction_required="UP" if x_interior >= state.current_price else "DOWN",
            trigger_definition=f"raw_%K={level} under POINT_BAR (range unchanged)",
            solution_status="EXACT_ANALYTIC",
            atr=state.atr14,
            formula_note=STOCH_NOTE,
            details={"intrabar_assumption": "POINT_BAR_H_EQ_L_EQ_X", "hh0": hh0, "ll0": ll0},
        )
    # Outside prior range: X changes hh or ll — still solvable for point bar but nonlinear cases;
    # document as REQUIRES_INTRABAR_ASSUMPTION for general OHLC, offer point-bar extended formulas.
    # If X > hh0: hh=X, ll=ll0 → (X-ll0)/(X-ll0)*100=100 → only level=100
    # If X < ll0: hh=hh0, ll=X → (X-X)/(hh0-X)=0 → only level=0
    if level >= 100:
        return make_result(
            predictor_id=predictor_id,
            parameter_set_id=parameter_set_id,
            source_timeframe=source_timeframe,
            decision_time=state.decision_time,
            calculated_at=state.calculated_at,
            current_price=state.current_price,
            trigger_price=hh0,  # any X>=hh0 gives 100 under point extending high
            direction_required="UP",
            trigger_definition="raw_%K=100 boundary",
            solution_status="AMBIGUOUS",
            atr=state.atr14,
            formula_note=STOCH_NOTE,
        )
    if level <= 0:
        return make_result(
            predictor_id=predictor_id,
            parameter_set_id=parameter_set_id,
            source_timeframe=source_timeframe,
            decision_time=state.decision_time,
            calculated_at=state.calculated_at,
            current_price=state.current_price,
            trigger_price=ll0,
            direction_required="DOWN",
            trigger_definition="raw_%K=0 boundary",
            solution_status="AMBIGUOUS",
            atr=state.atr14,
            formula_note=STOCH_NOTE,
        )
    return make_result(
        predictor_id=predictor_id,
        parameter_set_id=parameter_set_id,
        source_timeframe=source_timeframe,
        decision_time=state.decision_time,
        calculated_at=state.calculated_at,
        current_price=state.current_price,
        trigger_price=None,
        direction_required="EITHER",
        trigger_definition=f"smoothed/intrabar %K={level}",
        solution_status="REQUIRES_INTRABAR_ASSUMPTION",
        atr=state.atr14,
        formula_note=STOCH_NOTE,
        details={"reason": "target_outside_prior_range_or_needs_HL"},
    )


def solve_stoch_kd_cross_unsupported(
    state: CausalState,
    *,
    predictor_id: str,
    parameter_set_id: str,
    source_timeframe: str,
    direction: str,
) -> PredictorResult:
    return make_result(
        predictor_id=predictor_id,
        parameter_set_id=parameter_set_id,
        source_timeframe=source_timeframe,
        decision_time=state.decision_time,
        calculated_at=state.calculated_at,
        current_price=state.current_price,
        trigger_price=None,
        direction_required=direction,
        trigger_definition=f"K_cross_{direction}_D",
        solution_status="REQUIRES_INTRABAR_ASSUMPTION",
        atr=state.atr14,
        formula_note=STOCH_NOTE,
        details={"limitation": "K and D smoothing plus unknown next H/L; not unique from NEXT_BAR_CLOSE alone"},
    )
