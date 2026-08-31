"""O(N) sequential predictor series — shared by batch and streaming."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.bars import BarArrays, contiguous_ok
from crypto_trading_bot.research_v2.indicator_engine.segments import same_segment, segment_starts_array

from .dno import compute_masked_dno_series
from .inverse import price_for_next_detrended_value_segment_safe
from .peaks import ConfirmedExtremum, _is_peak, _is_trough
from .config import PredictorConfig


def _distance_features(
    current: float,
    target_price: float | None,
    atr: float | None,
) -> dict[str, float | None]:
    if target_price is None:
        return {"PRICE_DISTANCE": None, "PRICE_DISTANCE_PCT": None, "PRICE_DISTANCE_ATR": None}
    dist = target_price - current
    return {
        "PRICE_DISTANCE": dist,
        "PRICE_DISTANCE_PCT": (dist / current * 100.0) if current else None,
        "PRICE_DISTANCE_ATR": (dist / atr) if atr and atr != 0 else None,
    }


MANDATORY_DYNAMIC_FIELDS = (
    "DYNAMIC_OB_OSC_TARGET",
    "DYNAMIC_OS_OSC_TARGET",
    "PREDICTOR_OB_PRICE_NEXT_BAR",
    "PREDICTOR_OS_PRICE_NEXT_BAR",
)


@dataclass
class _BarSnapshot:
    index: int
    price: float | None = None
    ob: float | None = None
    os: float | None = None
    valid: bool = False


class PredictorSeriesEngine:
    """Sequential bar-by-bar predictor without recursive recompute."""

    def __init__(self, config: PredictorConfig) -> None:
        self.config = config
        self._confirmed_peaks: list[ConfirmedExtremum] = []
        self._confirmed_troughs: list[ConfirmedExtremum] = []
        self._bar_history: dict[int, _BarSnapshot] = {}

    def reset_segment(self) -> None:
        self._confirmed_peaks.clear()
        self._confirmed_troughs.clear()
        self._bar_history.clear()

    def _snapshot_at(self, idx: int) -> _BarSnapshot:
        return self._bar_history.get(idx, _BarSnapshot(index=idx))

    def _record(
        self,
        idx: int,
        *,
        valid: bool,
        price: float | None = None,
        ob: float | None = None,
        os: float | None = None,
    ) -> None:
        self._bar_history[idx] = _BarSnapshot(idx, price, ob, os, valid)

    def _confirm_at(self, dno: np.ndarray, gap_flags: np.ndarray, idx: int) -> None:
        k = self.config.peak_strength
        cand_i = idx - k
        if cand_i < k:
            return
        if not same_segment(gap_flags, cand_i, idx):
            return
        if not same_segment(gap_flags, cand_i - k, cand_i + k):
            return
        if _is_peak(dno, cand_i, k):
            self._confirmed_peaks.append(
                ConfirmedExtremum(cand_i, float(dno[cand_i]), "PEAK", idx)
            )
        if _is_trough(dno, cand_i, k):
            self._confirmed_troughs.append(
                ConfirmedExtremum(cand_i, float(dno[cand_i]), "TROUGH", idx)
            )

    def _prune_extrema(self, gap_flags: np.ndarray, idx: int) -> None:
        lb = self.config.lookback
        self._confirmed_peaks = [
            p
            for p in self._confirmed_peaks
            if idx - p.index < lb and same_segment(gap_flags, p.index, idx)
        ]
        self._confirmed_troughs = [
            t
            for t in self._confirmed_troughs
            if idx - t.index < lb and same_segment(gap_flags, t.index, idx)
        ]

    def step(
        self,
        arrays: BarArrays,
        idx: int,
        *,
        dno: np.ndarray,
        atr: np.ndarray | None,
        seg_starts: np.ndarray | None = None,
    ) -> dict[str, Any]:
        cfg = self.config
        gap_flags = arrays.gap_flags
        if seg_starts is None:
            seg_starts = segment_starts_array(gap_flags)
        seg_start = int(seg_starts[idx])

        self._confirm_at(dno, gap_flags, idx)
        self._prune_extrema(gap_flags, idx)

        if idx < seg_start + cfg.period - 1 or not contiguous_ok(
            gap_flags, max(seg_start, idx - cfg.period + 1), idx
        ):
            out = {"predictor_state": "INSUFFICIENT_HISTORY", "valid": False}
            self._record(idx, valid=False)
            return out

        current = float(arrays.close[idx])
        atr_i = (
            float(atr[idx])
            if atr is not None and idx < len(atr) and not np.isnan(atr[idx])
            else None
        )

        out: dict[str, Any] = {"valid": False, "predictor_state": "INSUFFICIENT_HISTORY"}

        if cfg.custom_ob is not None:
            ob_price, st = price_for_next_detrended_value_segment_safe(
                arrays.close,
                gap_flags,
                idx,
                period=cfg.period,
                target_oscillator_value=cfg.custom_ob,
                seg_starts=seg_starts,
            )
            dist = _distance_features(current, ob_price, atr_i)
            out.update(
                {
                    "DNO_CUSTOM_OB_TARGET": cfg.custom_ob,
                    "PRICE_TO_CUSTOM_OB": ob_price,
                    "DIST_TO_CUSTOM_OB_PRICE": dist["PRICE_DISTANCE"],
                    "DIST_TO_CUSTOM_OB_PCT": dist["PRICE_DISTANCE_PCT"],
                    "DIST_TO_CUSTOM_OB_ATR": dist["PRICE_DISTANCE_ATR"],
                }
            )
        if cfg.custom_os is not None:
            os_price, st = price_for_next_detrended_value_segment_safe(
                arrays.close,
                gap_flags,
                idx,
                period=cfg.period,
                target_oscillator_value=cfg.custom_os,
                seg_starts=seg_starts,
            )
            dist = _distance_features(current, os_price, atr_i)
            out.update(
                {
                    "DNO_CUSTOM_OS_TARGET": cfg.custom_os,
                    "PRICE_TO_CUSTOM_OS": os_price,
                    "DIST_TO_CUSTOM_OS_PRICE": dist["PRICE_DISTANCE"],
                    "DIST_TO_CUSTOM_OS_PCT": dist["PRICE_DISTANCE_PCT"],
                    "DIST_TO_CUSTOM_OS_ATR": dist["PRICE_DISTANCE_ATR"],
                }
            )

        peaks = [p for p in self._confirmed_peaks if p.value > 0]
        troughs = [t for t in self._confirmed_troughs if t.value < 0]
        pos_peaks = sorted(peaks, key=lambda x: x.index)[-cfg.samples :]
        neg_troughs = sorted(troughs, key=lambda x: x.index)[-cfg.samples :]

        if len(pos_peaks) < cfg.samples or len(neg_troughs) < cfg.samples:
            self._record(idx, valid=False)
            return out

        mean_ob = float(np.mean([p.value for p in pos_peaks]))
        mean_os = float(np.mean([t.value for t in neg_troughs]))
        dynamic_ob = cfg.ob_os_level_percent * mean_ob
        dynamic_os = cfg.ob_os_level_percent * mean_os

        ob_price, ob_st = price_for_next_detrended_value_segment_safe(
            arrays.close,
            gap_flags,
            idx,
            period=cfg.period,
            target_oscillator_value=dynamic_ob,
            seg_starts=seg_starts,
        )
        os_price, os_st = price_for_next_detrended_value_segment_safe(
            arrays.close,
            gap_flags,
            idx,
            period=cfg.period,
            target_oscillator_value=dynamic_os,
            seg_starts=seg_starts,
        )
        if ob_st != "OK" or os_st != "OK" or ob_price is None or os_price is None:
            out["predictor_state"] = ob_st if ob_st != "OK" else os_st
            self._record(idx, valid=False)
            return out

        ob_dist = _distance_features(current, ob_price, atr_i)
        os_dist = _distance_features(current, os_price, atr_i)
        band_width = ob_price - os_price
        pos_in_band = (current - os_price) / band_width if band_width else None

        prev1 = self._snapshot_at(idx - 1)
        prev3 = self._snapshot_at(idx - 3)

        out.update(
            {
                "valid": True,
                "predictor_state": "OK",
                "DYNAMIC_OB_OSC_TARGET": dynamic_ob,
                "DYNAMIC_OS_OSC_TARGET": dynamic_os,
                "PREDICTOR_OB_PRICE_NEXT_BAR": ob_price,
                "PREDICTOR_OS_PRICE_NEXT_BAR": os_price,
                "PRICE_DISTANCE_TO_OB": ob_dist["PRICE_DISTANCE"],
                "PRICE_DISTANCE_TO_OS": os_dist["PRICE_DISTANCE"],
                "PRICE_DISTANCE_TO_OB_PCT": ob_dist["PRICE_DISTANCE_PCT"],
                "PRICE_DISTANCE_TO_OS_PCT": os_dist["PRICE_DISTANCE_PCT"],
                "PRICE_DISTANCE_TO_OB_ATR": ob_dist["PRICE_DISTANCE_ATR"],
                "PRICE_DISTANCE_TO_OS_ATR": os_dist["PRICE_DISTANCE_ATR"],
                "BAND_WIDTH": band_width,
                "BAND_WIDTH_PCT": (band_width / current * 100.0) if current else None,
                "BAND_WIDTH_ATR": (band_width / atr_i) if atr_i else None,
                "CURRENT_PRICE_POSITION_IN_BAND": pos_in_band,
                "ABOVE_PREDICTOR_OB": bool(current > ob_price),
                "BELOW_PREDICTOR_OS": bool(current < os_price),
                "INSIDE_PREDICTOR_BAND": bool(os_price <= current <= ob_price),
                "OB_BAND_SLOPE_1": (ob_price - prev1.ob)
                if prev1.valid and prev1.ob is not None
                else None,
                "OS_BAND_SLOPE_1": (os_price - prev1.os)
                if prev1.valid and prev1.os is not None
                else None,
                "OB_BAND_SLOPE_3": (ob_price - prev3.ob)
                if prev3.valid and prev3.ob is not None and same_segment(gap_flags, idx - 3, idx)
                else None,
                "OS_BAND_SLOPE_3": (os_price - prev3.os)
                if prev3.valid and prev3.os is not None and same_segment(gap_flags, idx - 3, idx)
                else None,
            }
        )

        if prev1.valid and prev1.price is not None and prev1.ob is not None:
            out["CROSSED_OB_BAND_UP"] = bool(prev1.price <= prev1.ob and current > ob_price)
            out["CROSSED_OB_BAND_DOWN"] = bool(prev1.price >= prev1.ob and current < ob_price)
            out["OB_BAND_CONVERGING_TO_PRICE"] = bool(
                abs(ob_price - current) < abs(prev1.ob - prev1.price)
            )
        if prev1.valid and prev1.price is not None and prev1.os is not None:
            out["CROSSED_OS_BAND_UP"] = bool(prev1.price <= prev1.os and current > os_price)
            out["CROSSED_OS_BAND_DOWN"] = bool(prev1.price >= prev1.os and current < os_price)
            out["OS_BAND_CONVERGING_TO_PRICE"] = bool(
                abs(os_price - current) < abs(prev1.os - prev1.price)
            )
        if prev1.valid and prev1.ob is not None and prev1.os is not None:
            prev_bw = prev1.ob - prev1.os
            out["BAND_COMPRESSION"] = bool(prev_bw and band_width < prev_bw - 1e-9)
            out["BAND_EXPANSION"] = bool(prev_bw and band_width > prev_bw + 1e-9)

        self._record(idx, valid=True, price=current, ob=ob_price, os=os_price)
        return out

    def compute_series(
        self,
        arrays: BarArrays,
        *,
        atr: np.ndarray | None = None,
    ) -> list[dict[str, Any]]:
        self.reset_segment()
        dno = compute_masked_dno_series(arrays, period=self.config.period)
        seg_arr = segment_starts_array(arrays.gap_flags)
        n = len(arrays.close)
        out: list[dict[str, Any]] = []
        prev_seg_start = 0
        for idx in range(n):
            seg_start = int(seg_arr[idx])
            if seg_start != prev_seg_start:
                self.reset_segment()
                prev_seg_start = seg_start
            out.append(self.step(arrays, idx, dno=dno, atr=atr, seg_starts=seg_arr))
        return out
