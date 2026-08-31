"""Public predict API."""
from __future__ import annotations

from typing import Any, Sequence

from .dma_solver import solve_dma_cross
from .dno_solver import solve_dno_level
from .ma_osc_solver import bollinger_feasibility, solve_ema_cross, solve_project_oscillator, solve_sma_cross, solve_wma_cross
from .macd_solver import solve_macd
from .registry import PARAMETER_REGISTRY
from .rsi_solver import solve_rsi
from .state import build_state
from .stoch_solver import solve_stoch_k_level_point_bar, solve_stoch_kd_cross_unsupported
from .types import PredictorResult


def predict(
    bars: Sequence[dict[str, Any]],
    *,
    parameter_set_id: str,
    source_timeframe: str,
    decision_time: Any,
) -> PredictorResult | list[PredictorResult]:
    if parameter_set_id not in PARAMETER_REGISTRY:
        raise KeyError(parameter_set_id)
    params = PARAMETER_REGISTRY[parameter_set_id]
    if params.get("status") == "UNSUPPORTED_V1":
        return bollinger_feasibility()

    state = build_state(bars, decision_time=decision_time, timeframe=source_timeframe)
    if state is None:
        from .result_utils import make_result
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        return make_result(
            predictor_id=params["predictor_id"],
            parameter_set_id=parameter_set_id,
            source_timeframe=source_timeframe,
            decision_time=now,
            calculated_at=now,
            current_price=0.0,
            trigger_price=None,
            direction_required="EITHER",
            trigger_definition="n/a",
            solution_status="INSUFFICIENT_HISTORY",
        )

    pid = params["predictor_id"]
    if pid in ("DMA_CROSS_UP", "DMA_CROSS_DOWN"):
        return solve_dma_cross(
            state,
            period=int(params["period"]),
            display_shift=int(params["display_shift"]),
            direction=params["direction"],
            predictor_id=pid,
            parameter_set_id=parameter_set_id,
            source_timeframe=source_timeframe,
        )
    if pid in ("RSI_LEVEL", "RSI_CROSS_UP", "RSI_CROSS_DOWN"):
        return solve_rsi(
            state,
            period=int(params["period"]),
            level=float(params["level"]),
            predictor_id=pid,
            parameter_set_id=parameter_set_id,
            source_timeframe=source_timeframe,
            cross=params.get("cross"),
        )
    if pid.startswith("MACD_"):
        return solve_macd(
            state,
            fast=int(params["fast"]),
            slow=int(params["slow"]),
            signal=int(params["signal"]),
            mode=params["mode"],
            predictor_id=pid,
            parameter_set_id=parameter_set_id,
            source_timeframe=source_timeframe,
        )
    if pid == "STOCH_K_LEVEL_POINT_BAR":
        return solve_stoch_k_level_point_bar(
            state,
            k_period=int(params["k_period"]),
            level=float(params["level"]),
            predictor_id=pid,
            parameter_set_id=parameter_set_id,
            source_timeframe=source_timeframe,
        )
    if pid == "STOCH_K_CROSS_D":
        return solve_stoch_kd_cross_unsupported(
            state,
            predictor_id=pid,
            parameter_set_id=parameter_set_id,
            source_timeframe=source_timeframe,
            direction=params.get("direction", "UP"),
        )
    if pid == "SMA_CROSS_UP":
        return solve_sma_cross(state, int(params["period"]), "UP", pid, parameter_set_id, source_timeframe)
    if pid == "EMA_CROSS_UP":
        return solve_ema_cross(
            state,
            period=int(params["period"]),
            direction="UP",
            predictor_id=pid,
            parameter_set_id=parameter_set_id,
            source_timeframe=source_timeframe,
        )
    if pid == "WMA_CROSS_UP":
        return solve_wma_cross(
            state,
            period=int(params["period"]),
            direction="UP",
            predictor_id=pid,
            parameter_set_id=parameter_set_id,
            source_timeframe=source_timeframe,
        )
    if pid == "PROJECT_OSCILLATOR_PREDICTOR_V1":
        return solve_project_oscillator(
            state,
            ma_period=int(params["ma_period"]),
            lookback=int(params["lookback"]),
            k_std=float(params["k_std"]),
            predictor_id=pid,
            parameter_set_id=parameter_set_id,
            source_timeframe=source_timeframe,
        )
    if pid in ("DNO_OB_OS_PREDICTOR_OB", "DNO_OB_OS_PREDICTOR_OS"):
        return solve_dno_level(
            state,
            period=int(params["period"]),
            target_level=float(params["target_level"]),
            predictor_id=pid,
            parameter_set_id=parameter_set_id,
            source_timeframe=source_timeframe,
            band="OB" if pid.endswith("_OB") else "OS",
            gap_flags=state.gap_flags,
        )
    raise KeyError(pid)


BASELINE_SETS = [
    "PRED_DMA_3X3_CROSS_UP_V1",
    "PRED_DMA_7X5_CROSS_UP_V1",
    "PRED_DMA_25X5_CROSS_UP_V1",
    "PRED_RSI_14_30_V1",
    "PRED_RSI_14_50_V1",
    "PRED_RSI_14_70_V1",
    "PRED_MACD_12_26_9_SIGNAL_CROSS_UP_V1",
    "PRED_MACD_12_26_9_HIST_ZERO_V1",
    "PRED_STOCH_14_K_20_POINT_V1",
    "PRED_STOCH_14_K_80_POINT_V1",
    "PRED_PROJECT_OSC_20_50_2_V1",
]


def predict_all_baseline(bars, *, source_timeframe: str, decision_time) -> list[PredictorResult]:
    out: list[PredictorResult] = []
    for ps in BASELINE_SETS:
        r = predict(bars, parameter_set_id=ps, source_timeframe=source_timeframe, decision_time=decision_time)
        if isinstance(r, list):
            out.extend(r)
        else:
            out.append(r)
    return out
