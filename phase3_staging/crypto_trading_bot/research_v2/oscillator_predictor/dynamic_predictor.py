"""Project DiNapoli-style dynamic OB/OS oscillator predictor (reconstruction)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.bars import BarArrays, contiguous_ok
from crypto_trading_bot.research_v2.indicator_engine.segments import same_segment

from .dno import compute_dno_series
from .inverse import price_for_next_detrended_value
from .peaks import confirmed_extrema_at

PROJECT_DINAPOLI_STYLE_PREDICTOR_VERSION = "PROJECT_DINAPOLI_STYLE_OSCILLATOR_PREDICTOR_V1"
REFERENCE_STATUS = "PROJECT_RECONSTRUCTION"
TARGET_AGGREGATION = "PROJECT_MEAN_CONFIRMED_EXTREMA_V1"


@dataclass
class PredictorConfig:
    period: int = 7
    peak_strength: int = 2
    lookback: int = 100
    samples: int = 5
    ob_os_level_percent: float = 0.80
    custom_ob: float | None = None
    custom_os: float | None = None


DEFAULT_PREDICTOR_CONFIG = PredictorConfig()


def _distance_features(
    current: float,
    target_price: float | None,
    atr: float | None,
) -> dict[str, float | None]:
    if target_price is None:
        return {
            "PRICE_DISTANCE": None,
            "PRICE_DISTANCE_PCT": None,
            "PRICE_DISTANCE_ATR": None,
        }
    dist = target_price - current
    return {
        "PRICE_DISTANCE": dist,
        "PRICE_DISTANCE_PCT": (dist / current * 100.0) if current else None,
        "PRICE_DISTANCE_ATR": (dist / atr) if atr and atr != 0 else None,
    }


def compute_predictor_at_index(
    arrays: BarArrays,
    idx: int,
    *,
    config: PredictorConfig,
    atr: np.ndarray | None = None,
) -> dict[str, Any]:
    dno, _ = compute_dno_series(arrays, period=config.period)
    if idx < config.period - 1 or not contiguous_ok(arrays.gap_flags, idx - config.period + 1, idx):
        return {"predictor_state": "INSUFFICIENT_HISTORY", "valid": False}

    peaks, troughs = confirmed_extrema_at(
        dno,
        arrays.gap_flags,
        idx,
        peak_strength=config.peak_strength,
        lookback=config.lookback,
    )
    pos_peaks = sorted([p for p in peaks if p.value > 0], key=lambda x: x.index)[-config.samples :]
    neg_troughs = sorted([t for t in troughs if t.value < 0], key=lambda x: x.index)[-config.samples :]

    out: dict[str, Any] = {"valid": True, "predictor_state": "OK"}
    current = float(arrays.close[idx])
    atr_i = float(atr[idx]) if atr is not None and idx < len(atr) and not np.isnan(atr[idx]) else None

    # Custom explicit targets
    ob_tgt = config.custom_ob
    os_tgt = config.custom_os
    if ob_tgt is not None:
        ob_price = price_for_next_detrended_value(
            arrays.close[: idx + 1], period=config.period, target_oscillator_value=ob_tgt
        )
        dist = _distance_features(current, ob_price, atr_i)
        out.update(
            {
                "DNO_CUSTOM_OB_TARGET": ob_tgt,
                "PRICE_TO_CUSTOM_OB": ob_price,
                "DIST_TO_CUSTOM_OB_PRICE": dist["PRICE_DISTANCE"],
                "DIST_TO_CUSTOM_OB_PCT": dist["PRICE_DISTANCE_PCT"],
                "DIST_TO_CUSTOM_OB_ATR": dist["PRICE_DISTANCE_ATR"],
            }
        )
    if os_tgt is not None:
        os_price = price_for_next_detrended_value(
            arrays.close[: idx + 1], period=config.period, target_oscillator_value=os_tgt
        )
        dist = _distance_features(current, os_price, atr_i)
        out.update(
            {
                "DNO_CUSTOM_OS_TARGET": os_tgt,
                "PRICE_TO_CUSTOM_OS": os_price,
                "DIST_TO_CUSTOM_OS_PRICE": dist["PRICE_DISTANCE"],
                "DIST_TO_CUSTOM_OS_PCT": dist["PRICE_DISTANCE_PCT"],
                "DIST_TO_CUSTOM_OS_ATR": dist["PRICE_DISTANCE_ATR"],
            }
        )

    if len(pos_peaks) < config.samples or len(neg_troughs) < config.samples:
        out["predictor_state"] = "INSUFFICIENT_HISTORY"
        out["valid"] = False
        return out

    mean_ob = float(np.mean([p.value for p in pos_peaks]))
    mean_os = float(np.mean([t.value for t in neg_troughs]))
    dynamic_ob = config.ob_os_level_percent * mean_ob
    dynamic_os = config.ob_os_level_percent * mean_os
    ob_price = price_for_next_detrended_value(
        arrays.close[: idx + 1], period=config.period, target_oscillator_value=dynamic_ob
    )
    os_price = price_for_next_detrended_value(
        arrays.close[: idx + 1], period=config.period, target_oscillator_value=dynamic_os
    )

    ob_dist = _distance_features(current, ob_price, atr_i)
    os_dist = _distance_features(current, os_price, atr_i)
    band_width = (ob_price - os_price) if ob_price is not None and os_price is not None else None
    pos_in_band = None
    if band_width and band_width != 0 and ob_price is not None and os_price is not None:
        pos_in_band = (current - os_price) / band_width

    prev_idx = idx - 1
    prev3_idx = idx - 3
    prev_ob = prev_os = prev3_ob = prev3_os = None
    if prev_idx >= config.period - 1 and same_segment(arrays.gap_flags, prev_idx, idx):
        prev_out = compute_predictor_at_index(arrays, prev_idx, config=config, atr=atr)
        if prev_out.get("valid"):
            prev_ob = prev_out.get("PREDICTOR_OB_PRICE_NEXT_BAR")
            prev_os = prev_out.get("PREDICTOR_OS_PRICE_NEXT_BAR")
    if prev3_idx >= config.period - 1 and same_segment(arrays.gap_flags, prev3_idx, idx):
        prev3_out = compute_predictor_at_index(arrays, prev3_idx, config=config, atr=atr)
        if prev3_out.get("valid"):
            prev3_ob = prev3_out.get("PREDICTOR_OB_PRICE_NEXT_BAR")
            prev3_os = prev3_out.get("PREDICTOR_OS_PRICE_NEXT_BAR")

    out.update(
        {
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
            "BAND_WIDTH_PCT": (band_width / current * 100.0) if band_width and current else None,
            "BAND_WIDTH_ATR": (band_width / atr_i) if band_width and atr_i else None,
            "CURRENT_PRICE_POSITION_IN_BAND": pos_in_band,
            "ABOVE_PREDICTOR_OB": bool(ob_price is not None and current > ob_price),
            "BELOW_PREDICTOR_OS": bool(os_price is not None and current < os_price),
            "INSIDE_PREDICTOR_BAND": bool(
                ob_price is not None and os_price is not None and os_price <= current <= ob_price
            ),
            "OB_BAND_SLOPE_1": (ob_price - prev_ob) if ob_price is not None and prev_ob is not None else None,
            "OS_BAND_SLOPE_1": (os_price - prev_os) if os_price is not None and prev_os is not None else None,
            "OB_BAND_SLOPE_3": (ob_price - prev3_ob) if ob_price is not None and prev3_ob is not None else None,
            "OS_BAND_SLOPE_3": (os_price - prev3_os) if os_price is not None and prev3_os is not None else None,
            "OB_BAND_CONVERGING_TO_PRICE": bool(
                ob_price is not None and prev_ob is not None and abs(ob_price - current) < abs(prev_ob - current)
            ),
            "OS_BAND_CONVERGING_TO_PRICE": bool(
                os_price is not None and prev_os is not None and abs(os_price - current) < abs(prev_os - current)
            ),
        }
    )
    if prev_ob is not None and ob_price is not None:
        out["CROSSED_OB_BAND_UP"] = bool(prev_ob >= current and ob_price < current)
        out["CROSSED_OB_BAND_DOWN"] = bool(prev_ob <= current and ob_price > current)
    if prev_os is not None and os_price is not None:
        out["CROSSED_OS_BAND_UP"] = bool(prev_os >= current and os_price < current)
        out["CROSSED_OS_BAND_DOWN"] = bool(prev_os <= current and os_price > current)
    if band_width is not None and prev_ob is not None and prev_os is not None:
        prev_bw = prev_ob - prev_os
        out["BAND_COMPRESSION"] = bool(prev_bw and band_width < prev_bw)
        out["BAND_EXPANSION"] = bool(prev_bw and band_width > prev_bw)
    return out


def compute_predictor_feature_series(
    arrays: BarArrays,
    *,
    config: PredictorConfig,
    atr: np.ndarray | None = None,
) -> list[dict[str, Any]]:
    n = len(arrays.close)
    return [compute_predictor_at_index(arrays, i, config=config, atr=atr) for i in range(n)]
