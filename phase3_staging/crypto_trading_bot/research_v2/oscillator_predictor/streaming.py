"""Streaming parity wrapper for oscillator predictor."""
from __future__ import annotations

from typing import Any

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.bars import BarArrays, bars_to_arrays

from .dynamic_predictor import PredictorConfig, compute_predictor_at_index
from .dno import compute_dno_feature_series


class StreamingOscillatorPredictor:
    """Incremental closed-bar updates mirroring batch recompute."""

    def __init__(self, *, config: PredictorConfig | None = None) -> None:
        self.config = config or PredictorConfig()
        self._bars: list[dict[str, Any]] = []
        self._atr: np.ndarray | None = None

    def set_atr(self, atr: np.ndarray) -> None:
        self._atr = atr

    def on_bar_close(self, bar: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        self._bars.append(bar)
        arrays = bars_to_arrays(self._bars, timeframe=bar.get("timeframe", "1H"))
        idx = len(self._bars) - 1
        dno_samples = compute_dno_feature_series(
            arrays, period=self.config.period, atr=self._atr
        )
        pred = compute_predictor_at_index(arrays, idx, config=self.config, atr=self._atr)
        dno_feats = dno_samples[idx].signal_primitives if idx < len(dno_samples) else {}
        return dict(dno_feats), pred

    def batch_recompute(self) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        if not self._bars:
            return []
        arrays = bars_to_arrays(self._bars, timeframe=self._bars[0].get("timeframe", "1H"))
        dno_samples = compute_dno_feature_series(arrays, period=self.config.period, atr=self._atr)
        out: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for i in range(len(self._bars)):
            pred = compute_predictor_at_index(arrays, i, config=self.config, atr=self._atr)
            dno_feats = dno_samples[i].signal_primitives if i < len(dno_samples) else {}
            out.append((dict(dno_feats), pred))
        return out
