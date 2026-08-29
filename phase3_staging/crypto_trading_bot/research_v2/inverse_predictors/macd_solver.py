"""MACD analytic inverse using INDICATOR_ENGINE_V1 EMA state."""
from __future__ import annotations

from crypto_trading_bot.research_v2.indicator_engine.bars import bars_to_arrays
from crypto_trading_bot.research_v2.indicator_engine.macd import compute_macd_series
from crypto_trading_bot.research_v2.indicator_engine.math_core import ema

from .result_utils import make_result
from .state import CausalState
from .types import PredictorResult

FORMULA_MACD = (
    "EMA_f'=a_f*X+(1-a_f)*E_f; EMA_s'=a_s*X+(1-a_s)*E_s; MACD'=EMA_f'-EMA_s'. "
    "Signal'=a_g*MACD'+(1-a_g)*Signal. Setting MACD'=Signal' implies MACD'=Signal_prev. "
    "Solve (a_f-a_s)*X + (1-a_f)*E_f - (1-a_s)*E_s = Signal_prev."
)


def solve_macd(
    state: CausalState,
    *,
    fast: int,
    slow: int,
    signal: int,
    mode: str,  # SIGNAL_CROSS_UP | SIGNAL_CROSS_DOWN | HIST_ZERO
    predictor_id: str,
    parameter_set_id: str,
    source_timeframe: str,
) -> PredictorResult:
    arrays = bars_to_arrays(state.bars, timeframe=source_timeframe)
    series = compute_macd_series(arrays, fast=fast, slow=slow, signal=signal, display_shift=0)
    last = series[-1]
    if not last.valid:
        return make_result(
            predictor_id=predictor_id,
            parameter_set_id=parameter_set_id,
            source_timeframe=source_timeframe,
            decision_time=state.decision_time,
            calculated_at=state.calculated_at,
            current_price=state.current_price,
            trigger_price=None,
            direction_required="EITHER",
            trigger_definition=mode,
            solution_status="INSUFFICIENT_HISTORY",
            atr=state.atr14,
            formula_note=FORMULA_MACD,
        )
    ef = ema(state.closes, fast)
    es = ema(state.closes, slow)
    e_f, e_s = float(ef[-1]), float(es[-1])
    sig_prev = float(last.values["signal"])
    macd_now = float(last.values["macd"])
    hist_now = float(last.values["histogram"])

    a_f = 2.0 / (fast + 1.0)
    a_s = 2.0 / (slow + 1.0)
    coef = a_f - a_s
    if abs(coef) < 1e-15:
        return make_result(
            predictor_id=predictor_id,
            parameter_set_id=parameter_set_id,
            source_timeframe=source_timeframe,
            decision_time=state.decision_time,
            calculated_at=state.calculated_at,
            current_price=state.current_price,
            trigger_price=None,
            direction_required="EITHER",
            trigger_definition=mode,
            solution_status="NO_FINITE_SOLUTION",
            atr=state.atr14,
            formula_note=FORMULA_MACD,
        )
    const = (1.0 - a_f) * e_f - (1.0 - a_s) * e_s
    x = (sig_prev - const) / coef

    if mode == "HIST_ZERO":
        status = "ALREADY_TRIGGERED" if abs(hist_now) < 1e-12 else "EXACT_ANALYTIC"
        direction = "UP" if x >= state.current_price else "DOWN"
        trig_def = "NEXT_CLOSE makes MACD histogram = 0 (MACD'=Signal_prev)"
    elif mode == "SIGNAL_CROSS_UP":
        status = "ALREADY_TRIGGERED" if macd_now > sig_prev else "EXACT_ANALYTIC"
        direction = "UP"
        trig_def = "NEXT_CLOSE makes MACD cross above Signal"
    else:
        status = "ALREADY_TRIGGERED" if macd_now < sig_prev else "EXACT_ANALYTIC"
        direction = "DOWN"
        trig_def = "NEXT_CLOSE makes MACD cross below Signal"

    return make_result(
        predictor_id=predictor_id,
        parameter_set_id=parameter_set_id,
        source_timeframe=source_timeframe,
        decision_time=state.decision_time,
        calculated_at=state.calculated_at,
        current_price=state.current_price,
        trigger_price=float(x),
        direction_required=direction,
        trigger_definition=trig_def,
        solution_status=status,
        atr=state.atr14,
        formula_note=FORMULA_MACD,
        details={
            "macd_now": macd_now,
            "signal_now": sig_prev,
            "hist_now": hist_now,
            "ema_fast": e_f,
            "ema_slow": e_s,
        },
    )
