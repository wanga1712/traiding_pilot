"""Wilder RSI inverse — same convention as INDICATOR_ENGINE_V1."""
from __future__ import annotations

from .result_utils import make_result
from .state import CausalState, wilder_rsi_state
from .types import PredictorResult

FORMULA_RSI = (
    "Wilder: AG'=(AG*(n-1)+g)/n, AL'=(AL*(n-1)+l)/n. "
    "For RSI=L, RS=L/(100-L). Up branch X=c+(n-1)*(RS*AL-AG); "
    "down branch X=c-(n-1)*(AG/RS-AL). Keep branch consistent with X vs c."
)


def _solve_rsi_level(avg_gain: float, avg_loss: float, close: float, period: int, level: float) -> tuple[float | None, str]:
    if level <= 0 or level >= 100:
        return None, "NO_FINITE_SOLUTION"
    if level == 100:
        return None, "NO_FINITE_SOLUTION"
    rs = level / (100.0 - level)
    n = period
    # up branch: X >= close
    x_up = close + (n - 1) * (rs * avg_loss - avg_gain)
    # down branch: X < close
    if rs == 0:
        x_down = None
    else:
        x_down = close - (n - 1) * (avg_gain / rs - avg_loss)

    candidates = []
    if x_up is not None and x_up >= close - 1e-12:
        candidates.append(x_up)
    if x_down is not None and x_down < close - 1e-12:
        candidates.append(x_down)
    if not candidates:
        return None, "NO_FINITE_SOLUTION"
    if len(candidates) > 1:
        # prefer the branch that actually hits level; if both, ambiguous
        return None, "AMBIGUOUS"
    return float(candidates[0]), "EXACT_ANALYTIC"


def solve_rsi(
    state: CausalState,
    *,
    period: int,
    level: float,
    predictor_id: str,
    parameter_set_id: str,
    source_timeframe: str,
    cross: str | None = None,  # UP | DOWN | None (level only)
) -> PredictorResult:
    st = wilder_rsi_state(state.closes, period)
    if st is None:
        return make_result(
            predictor_id=predictor_id,
            parameter_set_id=parameter_set_id,
            source_timeframe=source_timeframe,
            decision_time=state.decision_time,
            calculated_at=state.calculated_at,
            current_price=state.current_price,
            trigger_price=None,
            direction_required="EITHER",
            trigger_definition=f"RSI({period})={level}",
            solution_status="INSUFFICIENT_HISTORY",
            atr=state.atr14,
            formula_note=FORMULA_RSI,
        )
    ag, al, rsi_now = st
    # already at/beyond for cross semantics
    if cross == "UP" and rsi_now > level:
        status_pre = "ALREADY_TRIGGERED"
    elif cross == "DOWN" and rsi_now < level:
        status_pre = "ALREADY_TRIGGERED"
    else:
        status_pre = None

    x, status = _solve_rsi_level(ag, al, state.current_price, period, level)
    if status_pre:
        status = status_pre
    direction = "UP" if (x is not None and x >= state.current_price) else "DOWN" if x is not None else "EITHER"
    if cross == "UP":
        direction = "UP"
    elif cross == "DOWN":
        direction = "DOWN"
    return make_result(
        predictor_id=predictor_id,
        parameter_set_id=parameter_set_id,
        source_timeframe=source_timeframe,
        decision_time=state.decision_time,
        calculated_at=state.calculated_at,
        current_price=state.current_price,
        trigger_price=x,
        direction_required=direction,
        trigger_definition=f"NEXT_CLOSE yields RSI({period})={level}" + (f" cross_{cross}" if cross else ""),
        solution_status=status,
        atr=state.atr14,
        formula_note=FORMULA_RSI,
        details={"rsi_now": rsi_now, "avg_gain": ag, "avg_loss": al, "level": level},
    )
