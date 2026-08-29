"""Extract causal indicator state from closed bars only (INDICATOR_ENGINE_V1 conventions)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.bars import bars_to_arrays, parse_ts
from crypto_trading_bot.research_v2.indicator_engine.math_core import ema, rma, true_range
from crypto_trading_bot.research_v2.reversal_events.anti_leakage import filter_history_available_at

from .version import FORBIDDEN_INPUT_KEYS


def assert_no_forbidden(bars: Sequence[dict[str, Any]]) -> None:
    keys = set()
    for b in list(bars)[:80]:
        keys.update(b.keys())
    bad = keys & FORBIDDEN_INPUT_KEYS
    if bad:
        raise ValueError(f"forbidden fields in predictor inputs: {sorted(bad)}")


@dataclass(frozen=True)
class CausalState:
    bars: list[dict[str, Any]]
    closes: np.ndarray
    highs: np.ndarray
    lows: np.ndarray
    volumes: np.ndarray
    close_times: list[datetime]
    open_times: list[datetime]
    gap_flags: np.ndarray
    current_price: float
    decision_time: datetime
    calculated_at: datetime
    atr14: float | None


def build_state(
    bars: Sequence[dict[str, Any]],
    *,
    decision_time: Any,
    timeframe: str,
) -> CausalState | None:
    assert_no_forbidden(bars)
    hist = filter_history_available_at(bars, decision_time, require_closed=True)
    if not hist:
        return None
    arrays = bars_to_arrays(hist, timeframe=timeframe)
    atr = rma(true_range(arrays.high, arrays.low, arrays.close), 14)
    atr_v = float(atr[-1]) if len(atr) and not np.isnan(atr[-1]) else None
    return CausalState(
        bars=hist,
        closes=arrays.close,
        highs=arrays.high,
        lows=arrays.low,
        volumes=arrays.volume,
        close_times=arrays.close_time,
        open_times=arrays.open_time,
        gap_flags=arrays.gap_flags,
        current_price=float(arrays.close[-1]),
        decision_time=parse_ts(decision_time),
        calculated_at=arrays.close_time[-1],
        atr14=atr_v,
    )


def wilder_rsi_state(closes: np.ndarray, period: int = 14) -> tuple[float, float, float] | None:
    """Return (avg_gain, avg_loss, rsi) at last bar, matching INDICATOR_ENGINE_V1."""
    n = len(closes)
    if n <= period:
        return None
    delta = np.diff(closes)
    gain = np.maximum(delta, 0.0)
    loss = np.maximum(-delta, 0.0)
    avg_gain = float(np.mean(gain[:period]))
    avg_loss = float(np.mean(loss[:period]))
    for i in range(period, len(delta)):
        avg_gain = (avg_gain * (period - 1) + float(gain[i])) / period
        avg_loss = (avg_loss * (period - 1) + float(loss[i])) / period
    if avg_loss == 0:
        rsi = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
    return avg_gain, avg_loss, rsi


def ema_last(closes: np.ndarray, period: int) -> float | None:
    series = ema(closes, period)
    if len(series) == 0 or np.isnan(series[-1]):
        return None
    return float(series[-1])
