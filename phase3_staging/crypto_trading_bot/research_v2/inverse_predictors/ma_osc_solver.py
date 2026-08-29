"""Generic MA cross + project oscillator + Bollinger feasibility."""
from __future__ import annotations

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.math_core import ema, sma, wma

from .dma_solver import FORMULA_DMA, solve_dma_cross
from .result_utils import make_result
from .state import CausalState, ema_last
from .types import PredictorResult


def solve_sma_cross(state: CausalState, period: int, direction: str, predictor_id: str, parameter_set_id: str, tf: str):
    return solve_dma_cross(
        state,
        period=period,
        display_shift=0,
        direction=direction,
        predictor_id=predictor_id,
        parameter_set_id=parameter_set_id,
        source_timeframe=tf,
    )


def solve_ema_cross(
    state: CausalState,
    *,
    period: int,
    direction: str,
    predictor_id: str,
    parameter_set_id: str,
    source_timeframe: str,
) -> PredictorResult:
    """Price vs EMA: EMA'=a*X+(1-a)*E. X=EMA' ⇒ X=E (previous EMA)."""
    e = ema_last(state.closes, period)
    if e is None:
        return make_result(
            predictor_id=predictor_id,
            parameter_set_id=parameter_set_id,
            source_timeframe=source_timeframe,
            decision_time=state.decision_time,
            calculated_at=state.calculated_at,
            current_price=state.current_price,
            trigger_price=None,
            direction_required=direction,
            trigger_definition=f"price_cross_EMA({period})",
            solution_status="INSUFFICIENT_HISTORY",
            atr=state.atr14,
            formula_note="X=EMA_prev for price=EMA_next",
        )
    price = state.current_price
    if direction == "UP" and price > e:
        status = "ALREADY_TRIGGERED"
    elif direction == "DOWN" and price < e:
        status = "ALREADY_TRIGGERED"
    else:
        status = "EXACT_ANALYTIC"
    return make_result(
        predictor_id=predictor_id,
        parameter_set_id=parameter_set_id,
        source_timeframe=source_timeframe,
        decision_time=state.decision_time,
        calculated_at=state.calculated_at,
        current_price=price,
        trigger_price=float(e),
        direction_required=direction,
        trigger_definition=f"NEXT_CLOSE equals EMA({period}) (cross threshold)",
        solution_status=status,
        atr=state.atr14,
        formula_note="EMA'=aX+(1-a)E; X=EMA' ⇒ X=E",
    )


def solve_wma_cross(
    state: CausalState,
    *,
    period: int,
    direction: str,
    predictor_id: str,
    parameter_set_id: str,
    source_timeframe: str,
) -> PredictorResult:
    """WMA next: weights 1..N on (c_{-(N-2)}..c_0, X). Set X=WMA' and solve."""
    if len(state.closes) < period - 1:
        return make_result(
            predictor_id=predictor_id,
            parameter_set_id=parameter_set_id,
            source_timeframe=source_timeframe,
            decision_time=state.decision_time,
            calculated_at=state.calculated_at,
            current_price=state.current_price,
            trigger_price=None,
            direction_required=direction,
            trigger_definition=f"price_cross_WMA({period})",
            solution_status="INSUFFICIENT_HISTORY",
            atr=state.atr14,
        )
    # WMA' = (sum_{i=1}^{N-1} i * close[-(N-1)+i] + N*X) / (N(N+1)/2)
    # X = WMA' ⇒ X * sum_w = sum_i i*c_i + N*X ⇒ X*(sum_w - N) = sum_i i*c_i
    prev = state.closes[-(period - 1) :]
    weighted = sum((i + 1) * float(prev[i]) for i in range(period - 1))
    sum_w = period * (period + 1) / 2.0
    denom = sum_w - period
    if abs(denom) < 1e-15:
        return make_result(
            predictor_id=predictor_id,
            parameter_set_id=parameter_set_id,
            source_timeframe=source_timeframe,
            decision_time=state.decision_time,
            calculated_at=state.calculated_at,
            current_price=state.current_price,
            trigger_price=None,
            direction_required=direction,
            trigger_definition=f"price_cross_WMA({period})",
            solution_status="NO_FINITE_SOLUTION",
            atr=state.atr14,
        )
    x = weighted / denom
    w_now = wma(state.closes, period)
    price = state.current_price
    wcur = float(w_now[-1]) if not np.isnan(w_now[-1]) else None
    if wcur is not None and direction == "UP" and price > wcur:
        status = "ALREADY_TRIGGERED"
    elif wcur is not None and direction == "DOWN" and price < wcur:
        status = "ALREADY_TRIGGERED"
    else:
        status = "EXACT_ANALYTIC"
    return make_result(
        predictor_id=predictor_id,
        parameter_set_id=parameter_set_id,
        source_timeframe=source_timeframe,
        decision_time=state.decision_time,
        calculated_at=state.calculated_at,
        current_price=price,
        trigger_price=float(x),
        direction_required=direction,
        trigger_definition=f"NEXT_CLOSE = WMA({period})",
        solution_status=status,
        atr=state.atr14,
        formula_note="X = sum_{i=1..N-1} i*c_i / (sum_w - N)",
    )


def solve_project_oscillator(
    state: CausalState,
    *,
    ma_period: int,
    lookback: int,
    k_std: float,
    predictor_id: str,
    parameter_set_id: str,
    source_timeframe: str,
) -> list[PredictorResult]:
    """
    DETRENDED_OSC = close - SMA(close,N).
    Thresholds = rolling mean(osc) ± k*std(osc) over lookback (history <= T).
    Solve X - SMA'(X) = threshold.
    SMA'=(S+X)/N ⇒ X - (S+X)/N = thr ⇒ X*(N-1)/N = thr + S/N ⇒ X = (N/(N-1))*(thr + S/N)
    """
    n = ma_period
    if len(state.closes) < max(n, lookback) + 1:
        r = make_result(
            predictor_id=predictor_id,
            parameter_set_id=parameter_set_id,
            source_timeframe=source_timeframe,
            decision_time=state.decision_time,
            calculated_at=state.calculated_at,
            current_price=state.current_price,
            trigger_price=None,
            direction_required="EITHER",
            trigger_definition="PROJECT_OSCILLATOR",
            solution_status="INSUFFICIENT_HISTORY",
            atr=state.atr14,
        )
        return [r, r]
    ma = sma(state.closes, n)
    osc = state.closes - ma
    # valid osc tail
    valid = osc[~np.isnan(osc)]
    if len(valid) < lookback:
        r = make_result(
            predictor_id=predictor_id,
            parameter_set_id=parameter_set_id,
            source_timeframe=source_timeframe,
            decision_time=state.decision_time,
            calculated_at=state.calculated_at,
            current_price=state.current_price,
            trigger_price=None,
            direction_required="EITHER",
            trigger_definition="PROJECT_OSCILLATOR",
            solution_status="INSUFFICIENT_HISTORY",
            atr=state.atr14,
        )
        return [r, r]
    window = valid[-lookback:]
    mu = float(np.mean(window))
    sd = float(np.std(window, ddof=0))
    upper_thr = mu + k_std * sd
    lower_thr = mu - k_std * sd
    s = float(np.sum(state.closes[-(n - 1) :]))
    def x_for(thr: float) -> float:
        return (n / (n - 1.0)) * (thr + s / n)

    xu, xl = x_for(upper_thr), x_for(lower_thr)
    note = "DETRENDED_OSC=close-SMA(N); thr=mean±k*std of osc history; X=(N/(N-1))*(thr+S/N)"
    upper = make_result(
        predictor_id=predictor_id + "_UPPER",
        parameter_set_id=parameter_set_id,
        source_timeframe=source_timeframe,
        decision_time=state.decision_time,
        calculated_at=state.calculated_at,
        current_price=state.current_price,
        trigger_price=float(xu),
        direction_required="UP",
        trigger_definition=f"osc reaches +{k_std}*std band",
        solution_status="EXACT_ANALYTIC",
        atr=state.atr14,
        formula_note=note,
        details={"threshold": upper_thr, "mu": mu, "sd": sd},
    )
    lower = make_result(
        predictor_id=predictor_id + "_LOWER",
        parameter_set_id=parameter_set_id,
        source_timeframe=source_timeframe,
        decision_time=state.decision_time,
        calculated_at=state.calculated_at,
        current_price=state.current_price,
        trigger_price=float(xl),
        direction_required="DOWN",
        trigger_definition=f"osc reaches -{k_std}*std band",
        solution_status="EXACT_ANALYTIC",
        atr=state.atr14,
        formula_note=note,
        details={"threshold": lower_thr, "mu": mu, "sd": sd},
    )
    return [upper, lower]


def bollinger_feasibility() -> PredictorResult:
    """Documented unsupported: X changes mean and std simultaneously → nonlinear/ambiguous."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return make_result(
        predictor_id="BOLLINGER_BAND_INVERSE",
        parameter_set_id="BOLLINGER_20_2_V1",
        source_timeframe="n/a",
        decision_time=now,
        calculated_at=now,
        current_price=0.0,
        trigger_price=None,
        direction_required="EITHER",
        trigger_definition="PRICE_AT_UPPER/LOWER/MID band",
        solution_status="UNSUPPORTED_V1",
        formula_note="Next close changes both SMA and rolling std; quadratic/root may be multiple/unstable. Status=UNSUPPORTED_V1.",
        details={"solution_class": "UNSUPPORTED_V1"},
    )
