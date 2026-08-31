"""Multi-timeframe FeatureSnapshot API — batch and streaming."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Sequence

from crypto_trading_bot.research_v2.indicator_engine.bars import bars_to_arrays, parse_ts
from crypto_trading_bot.research_v2.indicator_engine.types import IndicatorSample
from crypto_trading_bot.research_v2.resampling import UI_TIMEFRAMES

from .aligned_features import provenance_at
from .geometry import compute_geometry_features
from .macd_features import compute_macd_feature_series
from .ma_features import compute_dma_feature_series
from .pivots import PivotRecord, confirmed_pivots_at
from .registries import DMA_REGISTRY, FEATURE_OUTPUTS, MACD_REGISTRY, STOCHASTIC_REGISTRY
from .stoch_features import compute_stoch_feature_series
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


def _emit_declared(
    feats: dict[str, float | bool | None],
    *,
    prefix: str,
    family: str,
    prim: dict[str, Any],
) -> None:
    for name in FEATURE_OUTPUTS[family]:
        feats[f"{prefix}.{name}"] = prim.get(name)


class FeatureBank:
    """Batch precomputation + point-in-time snapshots."""

    def __init__(
        self,
        bars_by_tf: dict[str, list[dict[str, Any]]],
        *,
        pivots_by_tf: dict[str, list[PivotRecord]] | None = None,
    ) -> None:
        self.bars_by_tf = bars_by_tf
        self.pivots_by_tf = pivots_by_tf or {}
        self._cache: dict[tuple[str, str], Any] = {}

    def snapshot(self, decision_time: datetime) -> FeatureSnapshot:
        feats: dict[str, float | bool | None] = {}
        meta: dict[str, Any] = {"feature_bank_version": FEATURE_BANK_VERSION, "provenance": {}}
        for tf in UI_TIMEFRAMES:
            bars = self.bars_by_tf.get(tf) or []
            if not bars:
                continue
            idx = _last_completed_bar_index(bars, decision_time)
            if idx is None:
                continue
            for ps_id, meta_ps in DMA_REGISTRY.items():
                key = (tf, ps_id)
                shift = int(meta_ps["display_shift"])
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
                        display_shift=shift,
                        atr=atr,
                    )
                samples = self._cache[key]
                if idx < len(samples) and samples[idx].valid:
                    pref = f"{tf}.{ps_id}"
                    prim = samples[idx].signal_primitives
                    _emit_declared(feats, prefix=pref, family="DMA", prim=prim)
                    if shift > 0:
                        meta["provenance"][f"{pref}.DISPLAY_ALIGNED_MA_VALUE"] = provenance_at(samples, idx, shift)
            for ps_id, meta_ps in STOCHASTIC_REGISTRY.items():
                key = (tf, ps_id)
                shift = int(meta_ps["display_shift"])
                if key not in self._cache:
                    arrays = bars_to_arrays(bars, timeframe=tf)
                    self._cache[key] = compute_stoch_feature_series(
                        arrays,
                        k_period=int(meta_ps["k_period"]),
                        k_smooth=int(meta_ps["k_smooth"]),
                        d_period=int(meta_ps["d_period"]),
                        display_shift=shift,
                        overbought=float(meta_ps.get("overbought", 80)),
                        oversold=float(meta_ps.get("oversold", 20)),
                    )
                samples = self._cache[key]
                if idx < len(samples) and samples[idx].valid:
                    pref = f"{tf}.{ps_id}"
                    prim = samples[idx].signal_primitives
                    _emit_declared(feats, prefix=pref, family="STOCHASTIC", prim=prim)
                    if shift > 0:
                        meta["provenance"][f"{pref}.DISPLAY_ALIGNED_K"] = provenance_at(samples, idx, shift)
            for ps_id, meta_ps in MACD_REGISTRY.items():
                key = (tf, ps_id)
                shift = int(meta_ps["display_shift"])
                if key not in self._cache:
                    arrays = bars_to_arrays(bars, timeframe=tf)
                    self._cache[key] = compute_macd_feature_series(
                        arrays,
                        fast=int(meta_ps["fast"]),
                        slow=int(meta_ps["slow"]),
                        signal=int(meta_ps["signal"]),
                        display_shift=shift,
                    )
                samples = self._cache[key]
                if idx < len(samples) and samples[idx].valid:
                    pref = f"{tf}.{ps_id}"
                    prim = samples[idx].signal_primitives
                    _emit_declared(feats, prefix=pref, family="MACD", prim=prim)
                    if shift > 0:
                        meta["provenance"][f"{pref}.DISPLAY_ALIGNED_MACD"] = provenance_at(samples, idx, shift)
            self._attach_geometry(feats, tf, bars, idx, decision_time)
        return FeatureSnapshot(decision_time=decision_time, features=feats, metadata=meta)

    def _attach_geometry(
        self,
        feats: dict[str, float | bool | None],
        tf: str,
        bars: list[dict[str, Any]],
        idx: int,
        decision_time: datetime,
    ) -> None:
        pivots = self.pivots_by_tf.get(tf) or []
        confirmed = confirmed_pivots_at(pivots, decision_time)
        if len(confirmed) < 3:
            return
        a, b, c = confirmed[-3], confirmed[-2], confirmed[-1]
        current = float(bars[idx]["close"])
        atr_val = None
        atr_key = (tf, "__atr14__")
        if atr_key not in self._cache:
            arrays = bars_to_arrays(bars, timeframe=tf)
            from crypto_trading_bot.research_v2.indicator_engine.volatility import compute_atr_series

            atr_s = compute_atr_series(arrays, period=14)
            self._cache[atr_key] = atr_s
        atr_s = self._cache[atr_key]
        if idx < len(atr_s) and atr_s[idx].valid:
            atr_val = float(atr_s[idx].values["atr"])  # type: ignore

        prev_leg = None
        if len(confirmed) >= 4:
            p_prev = confirmed[-4]
            prev_leg = abs(b.pivot_price - p_prev.pivot_price)

        geo = compute_geometry_features(
            a_price=a.pivot_price,
            b_price=b.pivot_price,
            c_price=c.pivot_price,
            current_price=current,
            atr=atr_val,
            prev_same_direction_leg=prev_leg,
        )
        prefix = f"{tf}.GEOMETRY_ABC"
        _emit_declared(feats, prefix=prefix, family="GEOMETRY", prim=geo)
