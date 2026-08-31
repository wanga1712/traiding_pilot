"""Incremental streaming oscillator predictor — no full-history recompute."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.bars import TF_MINUTES, parse_ts

from .config import PredictorConfig
from .dynamic_predictor import compute_predictor_feature_series
from .series_engine import PredictorSeriesEngine


class StreamingOscillatorPredictor:
    """Incremental closed-bar updates mirroring batch sequential engine."""

    def __init__(self, *, config: PredictorConfig | None = None) -> None:
        self.config = config or PredictorConfig()
        self._engine = PredictorSeriesEngine(self.config)
        self._closes: list[float] = []
        self._open_times: list[datetime] = []
        self._close_times: list[datetime] = []
        self._gap_flags: list[bool] = []
        self._timeframe: str = "1H"
        self._atr: np.ndarray | None = None
        self._dno_values: list[float] = []
        self._seg_closes: list[float] = []
        self._full_history_recompute_count = 0

    @property
    def full_history_recompute_count(self) -> int:
        return self._full_history_recompute_count

    def set_atr(self, atr: np.ndarray) -> None:
        self._atr = atr

    def _detect_gap(self, bar: dict[str, Any]) -> bool:
        if len(self._open_times) == 0:
            return False
        tf = bar.get("timeframe", self._timeframe)
        expected = TF_MINUTES.get(tf)
        ot = parse_ts(bar["open_time"])
        prev_ot = self._open_times[-1]
        if expected is None:
            prev_ct = self._close_times[-1]
            return ot > prev_ct + timedelta(seconds=1)
        delta = ot - prev_ot
        return abs(delta.total_seconds() - expected * 60) > expected * 60 * 0.51

    def _incremental_dno(self, close: float, *, gap: bool) -> float:
        period = self.config.period
        if gap:
            self._seg_closes = []
        self._seg_closes.append(close)
        if len(self._seg_closes) < period:
            return float("nan")
        sma = sum(self._seg_closes[-period:]) / period
        return close - sma

    def _dno_features_at(self, idx: int) -> dict[str, Any]:
        period = self.config.period
        dv = self._dno_values[idx] if idx < len(self._dno_values) else float("nan")
        if np.isnan(dv):
            return {}
        prev = (
            float(self._dno_values[idx - 1])
            if idx > 0 and not np.isnan(self._dno_values[idx - 1])
            else None
        )
        ma3 = (
            float(self._dno_values[idx - 3])
            if idx >= 3 and not np.isnan(self._dno_values[idx - 3])
            else None
        )
        atr_i = None
        if self._atr is not None and idx < len(self._atr) and not np.isnan(self._atr[idx]):
            atr_i = float(self._atr[idx])
        return {
            "DNO_VALUE": dv,
            "DNO_SLOPE_1": (dv - prev) if prev is not None else None,
            "DNO_SLOPE_3": (dv - ma3) if ma3 is not None else None,
            "DNO_ZERO_CROSS_UP": bool(prev is not None and prev <= 0 and dv > 0),
            "DNO_ZERO_CROSS_DOWN": bool(prev is not None and prev >= 0 and dv < 0),
            "DNO_DISTANCE_FROM_ZERO": abs(dv),
            "DNO_ABS": abs(dv),
            "DNO_ATR_NORMALIZED": (dv / atr_i) if atr_i and atr_i != 0 else None,
        }

    def _bar_arrays_view(self):
        from crypto_trading_bot.research_v2.indicator_engine.bars import BarArrays

        c = np.array(self._closes, dtype=float)
        gap = np.array(self._gap_flags, dtype=bool)
        n = len(c)
        return BarArrays(
            self._open_times,
            self._close_times,
            c,
            c,
            c,
            c,
            np.ones(n),
            gap,
        )

    def on_bar_close(self, bar: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        self._timeframe = str(bar.get("timeframe", self._timeframe))
        gap = self._detect_gap(bar)
        self._gap_flags.append(gap)
        self._open_times.append(parse_ts(bar["open_time"]))
        self._close_times.append(parse_ts(bar["close_time"]))
        close = float(bar["close"])
        self._closes.append(close)
        if gap:
            self._engine.reset_segment()
        dno_v = self._incremental_dno(close, gap=gap)
        self._dno_values.append(dno_v)
        dno_arr = np.array(self._dno_values, dtype=float)
        idx = len(self._closes) - 1
        arrays = self._bar_arrays_view()
        seg_arr = None
        if len(self._closes) > 1:
            from crypto_trading_bot.research_v2.indicator_engine.segments import segment_starts_array

            seg_arr = segment_starts_array(np.array(self._gap_flags, dtype=bool))
        pred = self._engine.step(arrays, idx, dno=dno_arr, atr=self._atr, seg_starts=seg_arr)
        return self._dno_features_at(idx), pred

    def batch_recompute(self) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        from crypto_trading_bot.research_v2.indicator_engine.bars import bars_to_arrays
        from .dno import compute_dno_feature_series

        if not self._closes:
            return []
        bars = [
            {
                "open_time": self._open_times[i],
                "close_time": self._close_times[i],
                "open": self._closes[i],
                "high": self._closes[i],
                "low": self._closes[i],
                "close": self._closes[i],
                "volume": 1.0,
                "timeframe": self._timeframe,
            }
            for i in range(len(self._closes))
        ]
        arrays = bars_to_arrays(bars, timeframe=self._timeframe)
        dno_samples = compute_dno_feature_series(arrays, period=self.config.period, atr=self._atr)
        preds = compute_predictor_feature_series(arrays, config=self.config, atr=self._atr)
        return [
            (dict(dno_samples[i].signal_primitives), preds[i]) for i in range(len(bars))
        ]
