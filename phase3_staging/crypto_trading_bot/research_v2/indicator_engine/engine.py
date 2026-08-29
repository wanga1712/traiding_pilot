"""Public compute API — history must already be causal (closed bars <= T)."""
from __future__ import annotations

from typing import Any, Sequence

from crypto_trading_bot.research_v2.reversal_events.anti_leakage import (
    filter_history_available_at,
    get_event_history,
)

from .adx import compute_adx_series
from .bars import bars_to_arrays
from .cache import SeriesCache, fingerprint_bars
from .candle import compute_candle_series
from .dma import compute_dma_series
from .macd import compute_macd_series
from .momentum import (
    compute_cci_series,
    compute_momentum_series,
    compute_roc_series,
    compute_williams_r_series,
)
from .registry import PARAMETER_REGISTRY
from .rsi import compute_rsi_series
from .stochastic import compute_stochastic_series
from .trend import compute_ma_pair_distance, compute_ma_series
from .types import IndicatorResult, IndicatorSample
from .version import INDICATOR_ENGINE_VERSION
from .volatility import compute_atr_series, compute_bollinger_series, compute_realized_vol_series
from .volume import compute_volume_basic_series

_CACHE = SeriesCache()


def _dispatch(arrays, indicator_id: str, params: dict[str, Any]) -> list[IndicatorSample]:
    if indicator_id == "DMA":
        atr_samples = compute_atr_series(arrays, period=14)
        atr = []
        import numpy as np

        atr_arr = np.array(
            [s.values["atr"] if s.valid else np.nan for s in atr_samples], dtype=float
        )
        return compute_dma_series(
            arrays,
            period=int(params["period"]),
            display_shift=int(params["display_shift"]),
            atr=atr_arr,
        )
    if indicator_id in ("STOCHASTIC", "DISPLACED_STOCHASTIC"):
        return compute_stochastic_series(
            arrays,
            k_period=int(params.get("k_period", 14)),
            k_smooth=int(params.get("k_smooth", 3)),
            d_period=int(params.get("d_period", 3)),
            display_shift=int(params.get("display_shift", 0)),
            overbought=float(params.get("overbought", 80)),
            oversold=float(params.get("oversold", 20)),
        )
    if indicator_id in ("MACD", "DISPLACED_MACD"):
        return compute_macd_series(
            arrays,
            fast=int(params.get("fast", 12)),
            slow=int(params.get("slow", 26)),
            signal=int(params.get("signal", 9)),
            display_shift=int(params.get("display_shift", 0)),
        )
    if indicator_id == "RSI":
        return compute_rsi_series(arrays, period=int(params["period"]))
    if indicator_id == "ROC":
        return compute_roc_series(arrays, period=int(params["period"]))
    if indicator_id == "MOMENTUM":
        return compute_momentum_series(arrays, period=int(params["period"]))
    if indicator_id == "CCI":
        return compute_cci_series(arrays, period=int(params["period"]))
    if indicator_id == "WILLIAMS_R":
        return compute_williams_r_series(arrays, period=int(params["period"]))
    if indicator_id in ("SMA", "EMA", "WMA"):
        return compute_ma_series(arrays, kind=indicator_id, period=int(params["period"]))
    if indicator_id == "MA_CROSS":
        return compute_ma_pair_distance(
            arrays,
            kind=params.get("kind", "SMA"),
            fast=int(params["fast"]),
            slow=int(params["slow"]),
        )
    if indicator_id == "ADX_DMI":
        return compute_adx_series(arrays, period=int(params["period"]))
    if indicator_id == "ATR":
        return compute_atr_series(arrays, period=int(params["period"]))
    if indicator_id == "BOLLINGER":
        return compute_bollinger_series(
            arrays, period=int(params.get("period", 20)), std_mult=float(params.get("std_mult", 2.0))
        )
    if indicator_id == "REALIZED_VOLATILITY":
        return compute_realized_vol_series(arrays, period=int(params["period"]))
    if indicator_id == "CANDLE_STRUCTURE":
        return compute_candle_series(arrays)
    if indicator_id == "BASIC_VOLUME":
        return compute_volume_basic_series(arrays, period=int(params.get("period", 20)))
    raise KeyError(f"unknown indicator_id={indicator_id}")


def compute_series(
    bars: Sequence[dict[str, Any]],
    *,
    parameter_set_id: str,
    source_timeframe: str,
    market_data_version: str = "unspecified",
    use_cache: bool = True,
) -> IndicatorResult:
    """
    Compute full series from a CAUSAL bar list only.

    Callers MUST NOT pass future-containing event windows.
    Prefer get_event_history(...) or filter_history_available_at(...) first.
    """
    if parameter_set_id not in PARAMETER_REGISTRY:
        raise KeyError(f"unknown parameter_set_id={parameter_set_id}")
    params = PARAMETER_REGISTRY[parameter_set_id]
    indicator_id = params["indicator_id"]
    bar_list = list(bars)
    key = SeriesCache.make_key(
        market_data_version=market_data_version,
        timeframe=source_timeframe,
        indicator_id=indicator_id,
        parameter_set_id=parameter_set_id,
        bars_fingerprint=fingerprint_bars(bar_list),
    )
    if use_cache:
        hit = _CACHE.get(key)
        if hit is not None:
            return hit

    arrays = bars_to_arrays(bar_list, timeframe=source_timeframe)
    samples = tuple(_dispatch(arrays, indicator_id, params))
    result = IndicatorResult(
        indicator_engine_version=INDICATOR_ENGINE_VERSION,
        indicator_id=indicator_id,
        parameter_set_id=parameter_set_id,
        source_timeframe=source_timeframe,
        samples=samples,
    )
    if use_cache:
        _CACHE.put(key, result)
    return result


def compute_indicator(
    bars: Sequence[dict[str, Any]],
    *,
    parameter_set_id: str,
    source_timeframe: str,
    decision_time: Any,
    market_data_version: str = "unspecified",
) -> IndicatorSample | None:
    """Filter to closed bars <= decision_time, then return last valid sample."""
    hist = filter_history_available_at(bars, decision_time, require_closed=True)
    series = compute_series(
        hist,
        parameter_set_id=parameter_set_id,
        source_timeframe=source_timeframe,
        market_data_version=market_data_version,
        use_cache=False,
    )
    return series.last_valid()


def compute_from_event_history(
    event_bars: Sequence[dict[str, Any]],
    *,
    event_id: str,
    timeframe: str,
    decision_time: Any,
    parameter_set_id: str,
) -> IndicatorSample | None:
    """Approved path: get_event_history → compute."""
    hist = get_event_history(
        event_bars,
        event_id=event_id,
        timeframe=timeframe,
        decision_time=decision_time,
        require_closed=True,
    )
    return compute_indicator(
        hist,
        parameter_set_id=parameter_set_id,
        source_timeframe=timeframe,
        decision_time=decision_time,
    )
