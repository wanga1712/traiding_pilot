"""Batch causal inverse threshold series — O(N) alternative to per-bar predict()."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.bars import bars_to_arrays
from crypto_trading_bot.research_v2.indicator_engine.macd import compute_macd_series
from crypto_trading_bot.research_v2.indicator_engine.math_core import ema
from crypto_trading_bot.research_v2.indicator_engine.segments import segment_starts_array
from crypto_trading_bot.research_v2.oscillator_predictor.inverse import (
    INSUFFICIENT_CONTIGUOUS_HISTORY,
    price_for_next_detrended_value_segment_safe,
)
from crypto_trading_bot.research_v2.reversal_signal_study.signals import _trigger_price

from .registry import PARAMETER_REGISTRY

AUTHORIZED_INVERSE_PARAMETER_SETS = (
    "PRED_DMA_3X3_CROSS_UP_V1",
    "PRED_DMA_3X3_CROSS_DOWN_V1",
    "PRED_DMA_7X5_CROSS_UP_V1",
    "PRED_DMA_7X5_CROSS_DOWN_V1",
    "PRED_DMA_25X5_CROSS_UP_V1",
    "PRED_DMA_25X5_CROSS_DOWN_V1",
    "PRED_MACD_12_26_9_SIGNAL_CROSS_UP_V1",
    "PRED_MACD_12_26_9_SIGNAL_CROSS_DOWN_V1",
    "PRED_STOCH_14_K_20_POINT_V1",
    "PRED_STOCH_14_K_80_POINT_V1",
    "PRED_DNO_OS_V1",
    "PRED_DNO_OB_V1",
)

_THRESHOLD_CACHE: dict[tuple, "InverseThresholdSeries"] = {}


@dataclass(frozen=True)
class InverseThresholdSeries:
    parameter_set_id: str
    source_timeframe: str
    predicted_trigger_prices: np.ndarray
    solution_statuses: tuple[str | None, ...]
    usable_thresholds: np.ndarray

    @property
    def threshold_count(self) -> int:
        return int(np.isfinite(self.usable_thresholds).sum())


def clear_threshold_cache() -> None:
    _THRESHOLD_CACHE.clear()


def _cache_key(bars: list[dict[str, Any]], *, parameter_set_id: str, source_timeframe: str) -> tuple:
    return (
        source_timeframe,
        parameter_set_id,
        len(bars),
        str(bars[0]["close_time"]),
        str(bars[-1]["close_time"]),
    )


def _fill_from_solver_results(
    n: int,
    prices: list[float | None],
    statuses: list[str | None],
) -> InverseThresholdSeries:
    pred = np.array([np.nan if p is None else float(p) for p in prices], dtype=float)
    usable = np.array(
        [_trigger_price({"predicted_trigger_price": p, "solution_status": s}) for p, s in zip(prices, statuses)],
        dtype=float,
    )
    return InverseThresholdSeries(
        parameter_set_id="",
        source_timeframe="",
        predicted_trigger_prices=pred,
        solution_statuses=tuple(statuses),
        usable_thresholds=usable,
    )


def _batch_dma(closes: np.ndarray, *, period: int, direction: str) -> tuple[list[float | None], list[str | None]]:
    n = len(closes)
    prices: list[float | None] = [None] * n
    statuses: list[str | None] = [None] * n
    if period < 2:
        return prices, statuses
    for i in range(period - 1, n):
        window = closes[i - period + 2 : i + 1]
        if len(window) != period - 1:
            statuses[i] = "INSUFFICIENT_HISTORY"
            continue
        threshold = float(np.sum(window) / (period - 1))
        sma_now = float(np.mean(closes[i - period + 1 : i + 1]))
        price = float(closes[i])
        if direction == "UP":
            status = "ALREADY_TRIGGERED" if price > sma_now else "EXACT_ANALYTIC"
        else:
            status = "ALREADY_TRIGGERED" if price < sma_now else "EXACT_ANALYTIC"
        prices[i] = threshold
        statuses[i] = status
    return prices, statuses


def _batch_macd(
    closes: np.ndarray,
    *,
    fast: int,
    slow: int,
    signal: int,
    mode: str,
    arrays,
    source_timeframe: str,
) -> tuple[list[float | None], list[str | None]]:
    n = len(closes)
    prices: list[float | None] = [None] * n
    statuses: list[str | None] = [None] * n
    series = compute_macd_series(arrays, fast=fast, slow=slow, signal=signal, display_shift=0)
    ef = ema(closes, fast)
    es = ema(closes, slow)
    a_f = 2.0 / (fast + 1.0)
    a_s = 2.0 / (slow + 1.0)
    coef = a_f - a_s
    for i in range(n):
        last = series[i]
        if not last.valid:
            statuses[i] = "INSUFFICIENT_HISTORY"
            continue
        if abs(coef) < 1e-15:
            statuses[i] = "NO_FINITE_SOLUTION"
            continue
        e_f, e_s = float(ef[i]), float(es[i])
        sig_prev = float(last.values["signal"])
        macd_now = float(last.values["macd"])
        const = (1.0 - a_f) * e_f - (1.0 - a_s) * e_s
        x = (sig_prev - const) / coef
        if mode == "HIST_ZERO":
            status = "ALREADY_TRIGGERED" if abs(float(last.values["histogram"])) < 1e-12 else "EXACT_ANALYTIC"
        elif mode == "SIGNAL_CROSS_UP":
            status = "ALREADY_TRIGGERED" if macd_now > sig_prev else "EXACT_ANALYTIC"
        else:
            status = "ALREADY_TRIGGERED" if macd_now < sig_prev else "EXACT_ANALYTIC"
        prices[i] = float(x)
        statuses[i] = status
    return prices, statuses


def _batch_stoch(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    *,
    k_period: int,
    level: float,
) -> tuple[list[float | None], list[str | None]]:
    n = len(closes)
    prices: list[float | None] = [None] * n
    statuses: list[str | None] = [None] * n
    for i in range(k_period - 1, n):
        prev_h = highs[i - k_period + 2 : i + 1]
        prev_l = lows[i - k_period + 2 : i + 1]
        hh0 = float(np.max(prev_h))
        ll0 = float(np.min(prev_l))
        if hh0 == ll0:
            statuses[i] = "NO_FINITE_SOLUTION"
            continue
        x_interior = ll0 + (level / 100.0) * (hh0 - ll0)
        if ll0 <= x_interior <= hh0:
            prices[i] = float(x_interior)
            statuses[i] = "EXACT_ANALYTIC"
            continue
        if level >= 100:
            prices[i] = hh0
            statuses[i] = "AMBIGUOUS"
        elif level <= 0:
            prices[i] = ll0
            statuses[i] = "AMBIGUOUS"
        else:
            statuses[i] = "REQUIRES_INTRABAR_ASSUMPTION"
    return prices, statuses


def _batch_dno(
    closes: np.ndarray,
    gap_flags: np.ndarray,
    *,
    period: int,
    target_level: float,
) -> tuple[list[float | None], list[str | None]]:
    n = len(closes)
    prices: list[float | None] = [None] * n
    statuses: list[str | None] = [None] * n
    seg_starts = segment_starts_array(gap_flags)
    for i in range(n):
        trigger, status = price_for_next_detrended_value_segment_safe(
            closes,
            gap_flags,
            i,
            period=period,
            target_oscillator_value=target_level,
            seg_starts=seg_starts,
        )
        if status == INSUFFICIENT_CONTIGUOUS_HISTORY:
            statuses[i] = INSUFFICIENT_CONTIGUOUS_HISTORY
        else:
            prices[i] = trigger
            statuses[i] = "EXACT_ANALYTIC" if trigger is not None else "INSUFFICIENT_HISTORY"
    return prices, statuses


def compute_inverse_threshold_series(
    bars: list[dict[str, Any]],
    *,
    parameter_set_id: str,
    source_timeframe: str,
    cache: dict[tuple, InverseThresholdSeries] | None = None,
) -> InverseThresholdSeries:
    if parameter_set_id not in PARAMETER_REGISTRY:
        raise KeyError(parameter_set_id)
    store = _THRESHOLD_CACHE if cache is None else cache
    key = _cache_key(bars, parameter_set_id=parameter_set_id, source_timeframe=source_timeframe)
    if key in store:
        return store[key]

    params = PARAMETER_REGISTRY[parameter_set_id]
    arrays = bars_to_arrays(bars, timeframe=source_timeframe)
    closes = arrays.close
    n = len(closes)
    pid = params["predictor_id"]

    if pid in ("DMA_CROSS_UP", "DMA_CROSS_DOWN"):
        prices, statuses = _batch_dma(
            closes,
            period=int(params["period"]),
            direction=params["direction"],
        )
    elif pid in ("MACD_SIGNAL_CROSS_UP", "MACD_SIGNAL_CROSS_DOWN", "MACD_HIST_ZERO"):
        prices, statuses = _batch_macd(
            closes,
            fast=int(params["fast"]),
            slow=int(params["slow"]),
            signal=int(params["signal"]),
            mode=params["mode"],
            arrays=arrays,
            source_timeframe=source_timeframe,
        )
    elif pid == "STOCH_K_LEVEL_POINT_BAR":
        prices, statuses = _batch_stoch(
            arrays.high,
            arrays.low,
            closes,
            k_period=int(params["k_period"]),
            level=float(params["level"]),
        )
    elif pid in ("DNO_OB_OS_PREDICTOR_OB", "DNO_OB_OS_PREDICTOR_OS"):
        prices, statuses = _batch_dno(
            closes,
            arrays.gap_flags,
            period=int(params["period"]),
            target_level=float(params["target_level"]),
        )
    else:
        raise KeyError(f"unsupported batch route: {parameter_set_id}")

    out = _fill_from_solver_results(n, prices, statuses)
    out = InverseThresholdSeries(
        parameter_set_id=parameter_set_id,
        source_timeframe=source_timeframe,
        predicted_trigger_prices=out.predicted_trigger_prices,
        solution_statuses=out.solution_statuses,
        usable_thresholds=out.usable_thresholds,
    )
    store[key] = out
    return out


def slow_reference_threshold_at(
    bars: list[dict[str, Any]],
    *,
    index: int,
    parameter_set_id: str,
    source_timeframe: str,
) -> float | None:
    """Slow authority: predict() on causal prefix ending at index."""
    from .engine import predict

    prefix = bars[: index + 1]
    decision = prefix[-1]["close_time"]
    return _trigger_price(
        predict(prefix, parameter_set_id=parameter_set_id, source_timeframe=source_timeframe, decision_time=decision)
    )


def batch_threshold_at(series: InverseThresholdSeries, index: int) -> float | None:
    thr = series.usable_thresholds[index]
    if not np.isfinite(thr):
        return None
    return float(thr)


def apply_stride_forward_fill(thresholds: np.ndarray, *, stride: int) -> np.ndarray:
    n = len(thresholds)
    if stride <= 1:
        return thresholds.copy()
    out = np.full(n, np.nan, dtype=float)
    stride = max(1, stride)
    indices = list(range(0, n, stride))
    if indices[-1] != n - 1:
        indices.append(n - 1)
    idx_set = set(indices)
    last = np.nan
    for i in range(n):
        if i in idx_set and np.isfinite(thresholds[i]):
            last = thresholds[i]
        if np.isfinite(last):
            out[i] = last
    return out
