"""Multi-timeframe FeatureSnapshot API — batch and streaming."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Sequence

from crypto_trading_bot.research_v2.indicator_engine.bars import parse_ts
from crypto_trading_bot.research_v2.indicator_engine.bars import bars_to_arrays
from crypto_trading_bot.research_v2.indicator_engine.macd import compute_macd_series
from crypto_trading_bot.research_v2.indicator_engine.stochastic import compute_stochastic_series
from crypto_trading_bot.research_v2.indicator_engine.types import IndicatorSample
from crypto_trading_bot.research_v2.resampling import UI_TIMEFRAMES

from .displacement import display_aligned_usable_at
from .ma_features import compute_dma_feature_series
from .registries import DMA_REGISTRY, MACD_REGISTRY, STOCHASTIC_REGISTRY
from .version import FEATURE_BANK_VERSION


@dataclass
class FeatureSnapshot:
    decision_time: datetime
    features: dict[str, float | bool | None] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def namespace(self, timeframe: str) -> dict[str, float | bool | None]:
        prefix = f"{timeframe}."
        return {k[len(prefix) :]: v for k, v in self.features.items() if k.startswith(prefix)}


def _last_completed_bar_index(bars: Sequence[dict[str, Any]], decision_time: datetime) -> int | None:
    idx = None
    for i, b in enumerate(bars):
        ct = parse_ts(b["close_time"])
        if ct <= decision_time:
            idx = i
        else:
            break
    return idx


def _extract_stoch_features(samples: Sequence[IndicatorSample], idx: int, shift: int) -> dict[str, Any]:
    s = samples[idx]
    if not s.valid:
        return {}
    k, d = s.values.get("k"), s.values.get("d")
    da_k = display_aligned_usable_at(samples, idx, shift, s.available_at, value_key="k") if shift else k
    da_d = display_aligned_usable_at(samples, idx, shift, s.available_at, value_key="d") if shift else d
    prim = s.signal_primitives
    return {
        "K": k,
        "D": d,
        "DISPLAY_ALIGNED_K": da_k,
        "DISPLAY_ALIGNED_D": da_d,
        "K_MINUS_D": (k - d) if k is not None and d is not None else None,
        "K_SLOPE": prim.get("SLOPE_K"),
        "D_SLOPE": prim.get("SLOPE_D"),
        "K_CROSS_UP_D": prim.get("K_CROSS_UP_D"),
        "K_CROSS_DOWN_D": prim.get("K_CROSS_DOWN_D"),
        "DIST_TO_OVERSOLD": prim.get("DISTANCE_TO_OVERSOLD"),
        "DIST_TO_OVERBOUGHT": prim.get("DISTANCE_TO_OVERBOUGHT"),
        "OVERBOUGHT_80": prim.get("OVERBOUGHT"),
        "OVERSOLD_20": prim.get("OVERSOLD"),
    }


def _extract_macd_features(samples: Sequence[IndicatorSample], idx: int, shift: int) -> dict[str, Any]:
    s = samples[idx]
    if not s.valid:
        return {}
    macd, sig, hist = s.values.get("macd"), s.values.get("signal"), s.values.get("hist")
    prim = s.signal_primitives
    return {
        "MACD": macd,
        "SIGNAL": sig,
        "HIST": hist,
        "DISPLAY_ALIGNED_MACD": display_aligned_usable_at(samples, idx, shift, s.available_at, value_key="macd")
        if shift
        else macd,
        "MACD_MINUS_SIGNAL": prim.get("MACD_MINUS_SIGNAL"),
        "MACD_SLOPE": prim.get("SLOPE_MACD"),
        "SIGNAL_SLOPE": prim.get("SLOPE_SIGNAL"),
        "HIST_SLOPE": prim.get("SLOPE_HIST"),
        "MACD_CROSS_UP_SIGNAL": prim.get("MACD_CROSS_UP_SIGNAL"),
        "MACD_CROSS_DOWN_SIGNAL": prim.get("MACD_CROSS_DOWN_SIGNAL"),
        "HIST_CROSS_UP_ZERO": prim.get("HIST_CROSS_UP_ZERO"),
        "HIST_CROSS_DOWN_ZERO": prim.get("HIST_CROSS_DOWN_ZERO"),
        "HIST_CONTRACTING_NEGATIVE": prim.get("HIST_CONTRACTING_NEGATIVE"),
        "HIST_CONTRACTING_POSITIVE": prim.get("HIST_CONTRACTING_POSITIVE"),
    }


def _stoch_samples(bars: list[dict], tf: str, meta: dict) -> tuple[Any, ...]:
    arrays = bars_to_arrays(bars, timeframe=tf)
    return tuple(
        compute_stochastic_series(
            arrays,
            k_period=int(meta["k_period"]),
            k_smooth=int(meta["k_smooth"]),
            d_period=int(meta["d_period"]),
            display_shift=int(meta["display_shift"]),
            overbought=float(meta.get("overbought", 80)),
            oversold=float(meta.get("oversold", 20)),
        )
    )


def _macd_samples(bars: list[dict], tf: str, meta: dict) -> tuple[Any, ...]:
    arrays = bars_to_arrays(bars, timeframe=tf)
    return tuple(
        compute_macd_series(
            arrays,
            fast=int(meta["fast"]),
            slow=int(meta["slow"]),
            signal=int(meta["signal"]),
            display_shift=int(meta["display_shift"]),
        )
    )


class FeatureBank:
    """Batch precomputation + point-in-time snapshots."""

    def __init__(self, bars_by_tf: dict[str, list[dict[str, Any]]]) -> None:
        self.bars_by_tf = bars_by_tf
        self._cache: dict[tuple[str, str], Any] = {}

    def snapshot(self, decision_time: datetime) -> FeatureSnapshot:
        feats: dict[str, float | bool | None] = {}
        meta: dict[str, Any] = {"feature_bank_version": FEATURE_BANK_VERSION}
        for tf in UI_TIMEFRAMES:
            bars = self.bars_by_tf.get(tf) or []
            if not bars:
                continue
            idx = _last_completed_bar_index(bars, decision_time)
            if idx is None:
                continue
            for ps_id, meta_ps in DMA_REGISTRY.items():
                key = (tf, ps_id)
                if key not in self._cache:
                    from crypto_trading_bot.research_v2.indicator_engine.volatility import compute_atr_series

                    arrays = bars_to_arrays(bars, timeframe=tf)
                    atr_s = compute_atr_series(arrays, period=14)
                    atr = __import__("numpy").array(
                        [s.values["atr"] if s.valid else float("nan") for s in atr_s], dtype=float
                    )
                    self._cache[key] = compute_dma_feature_series(
                        arrays,
                        ma_type=meta_ps["ma_type"],
                        period=meta_ps["period"],
                        display_shift=meta_ps["display_shift"],
                        atr=atr,
                    )
                samples = self._cache[key]
                if idx < len(samples) and samples[idx].valid:
                    for fk, fv in samples[idx].signal_primitives.items():
                        feats[f"{tf}.{ps_id}.{fk}"] = fv
            for ps_id, meta_ps in STOCHASTIC_REGISTRY.items():
                key = (tf, ps_id)
                if key not in self._cache:
                    self._cache[key] = _stoch_samples(bars, tf, meta_ps)
                samples = self._cache[key]
                if idx < len(samples) and samples[idx].valid:
                    ext = _extract_stoch_features(samples, idx, int(meta_ps["display_shift"]))
                    for fk, fv in ext.items():
                        feats[f"{tf}.{ps_id}.{fk}"] = fv
            for ps_id, meta_ps in MACD_REGISTRY.items():
                key = (tf, ps_id)
                if key not in self._cache:
                    self._cache[key] = _macd_samples(bars, tf, meta_ps)
                samples = self._cache[key]
                if idx < len(samples) and samples[idx].valid:
                    ext = _extract_macd_features(samples, idx, int(meta_ps["display_shift"]))
                    for fk, fv in ext.items():
                        feats[f"{tf}.{ps_id}.{fk}"] = fv
        return FeatureSnapshot(decision_time=decision_time, features=feats, metadata=meta)
