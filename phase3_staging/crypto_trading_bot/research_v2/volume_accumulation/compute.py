"""Batch feature computation for VOLUME_ACCUMULATION_ENGINE_V1."""
from __future__ import annotations

from typing import Any, Sequence

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.bars import bars_to_arrays, contiguous_ok
from crypto_trading_bot.research_v2.indicator_engine.math_core import rma, rolling_std, sma, true_range
from crypto_trading_bot.research_v2.reversal_events.anti_leakage import filter_history_available_at

from .guards import assert_no_forbidden_fields, overlap_ratio, percentile_rank, rolling_median, sanitize_bars
from .registry import PARAMETER_REGISTRY
from .types import FeatureResult, FeatureSample
from .version import FEATURE_ENGINE_VERSION


def _invalid(calc_at, reason: str) -> FeatureSample:
    return FeatureSample(calc_at, calc_at, {}, False, reason)


def _obv(close: np.ndarray, volume: np.ndarray) -> np.ndarray:
    out = np.zeros(len(close))
    for i in range(1, len(close)):
        if close[i] > close[i - 1]:
            out[i] = out[i - 1] + volume[i]
        elif close[i] < close[i - 1]:
            out[i] = out[i - 1] - volume[i]
        else:
            out[i] = out[i - 1]
    return out


def _clv(h, l, c) -> float:
    if h == l:
        return 0.0
    return ((c - l) - (h - c)) / (h - l)


def compute_volume_intensity(arrays, window: int) -> list[FeatureSample]:
    mean = sma(arrays.volume, window)
    med = rolling_median(arrays.volume, window)
    pct = percentile_rank(arrays.volume, window)
    samples = []
    for i in range(len(arrays.volume)):
        ct = arrays.close_time[i]
        vol = float(arrays.volume[i])
        vals = {
            "VOLUME_RAW": vol,
            "VOLUME_ROLLING_MEAN": None,
            "VOLUME_ROLLING_MEDIAN": None,
            "VOLUME_RELATIVE_TO_MEAN": None,
            "VOLUME_RELATIVE_TO_MEDIAN": None,
            "VOLUME_ZSCORE": None,
            "VOLUME_CHANGE_1": None,
            "VOLUME_CHANGE_N": None,
            "VOLUME_SLOPE": None,
            "VOLUME_PERCENTILE": None,
            "VOLUME_CV": None,
        }
        if i >= 1:
            vals["VOLUME_SLOPE"] = vol - float(arrays.volume[i - 1])
            if arrays.volume[i - 1] != 0:
                vals["VOLUME_CHANGE_1"] = vals["VOLUME_SLOPE"] / float(arrays.volume[i - 1]) * 100.0
        if i < window - 1 or np.isnan(mean[i]):
            samples.append(FeatureSample(ct, ct, vals, False, "INVALID_WARMUP"))
            continue
        if not contiguous_ok(arrays.gap_flags, i - window + 1, i):
            samples.append(FeatureSample(ct, ct, vals, False, "insufficient_contiguous_history"))
            continue
        w = arrays.volume[i - window + 1 : i + 1]
        std = float(np.std(w, ddof=0))
        mv, md = float(mean[i]), float(med[i])
        vals.update(
            {
                "VOLUME_ROLLING_MEAN": mv,
                "VOLUME_ROLLING_MEDIAN": md,
                "VOLUME_RELATIVE_TO_MEAN": vol / mv if mv else None,
                "VOLUME_RELATIVE_TO_MEDIAN": vol / md if md else None,
                "VOLUME_ZSCORE": (vol - mv) / std if std else 0.0,
                "VOLUME_PERCENTILE": float(pct[i]),
                "VOLUME_CV": std / mv if mv else None,
                "VOLUME_CHANGE_N": (vol - float(arrays.volume[i - window + 1])) / float(arrays.volume[i - window + 1]) * 100.0
                if arrays.volume[i - window + 1]
                else None,
            }
        )
        samples.append(FeatureSample(ct, ct, vals, True))
    return samples


def compute_price_volume(arrays, window: int) -> list[FeatureSample]:
    tp = (arrays.high + arrays.low + arrays.close) / 3.0
    obv = _obv(arrays.close, arrays.volume)
    atr = rma(true_range(arrays.high, arrays.low, arrays.close), 14)
    samples = []
    for i in range(len(arrays.close)):
        ct = arrays.close_time[i]
        clv = _clv(float(arrays.high[i]), float(arrays.low[i]), float(arrays.close[i]))
        vals: dict[str, Any] = {
            "OBV": float(obv[i]),
            "OBV_SLOPE": float(obv[i] - obv[i - 1]) if i else None,
            "CLOSE_LOCATION_VALUE": clv,
            "VOLUME_WEIGHTED_CLOSE_LOCATION": clv * float(arrays.volume[i]),
            "UP_BAR_VOLUME": float(arrays.volume[i]) if i and arrays.close[i] > arrays.close[i - 1] else 0.0,
            "DOWN_BAR_VOLUME": float(arrays.volume[i]) if i and arrays.close[i] < arrays.close[i - 1] else 0.0,
            "VWAP_ROLLING": None,
            "DISTANCE_TO_VWAP_PCT": None,
            "DISTANCE_TO_VWAP_ATR": None,
            "CMF": None,
            "MFI": None,
            "UP_DOWN_VOLUME_RATIO": None,
            "TYPICAL_PRICE_VOLUME": float(tp[i] * arrays.volume[i]),
        }
        if i < window - 1:
            samples.append(FeatureSample(ct, ct, vals, False, "INVALID_WARMUP"))
            continue
        if not contiguous_ok(arrays.gap_flags, i - window + 1, i):
            samples.append(FeatureSample(ct, ct, vals, False, "insufficient_contiguous_history"))
            continue
        sl = slice(i - window + 1, i + 1)
        vol_sum = float(np.sum(arrays.volume[sl]))
        vwap = float(np.sum(tp[sl] * arrays.volume[sl]) / vol_sum) if vol_sum else None
        # CMF
        mf_mult = np.array([_clv(float(arrays.high[j]), float(arrays.low[j]), float(arrays.close[j])) for j in range(i - window + 1, i + 1)])
        mf_vol = mf_mult * arrays.volume[sl]
        cmf = float(np.sum(mf_vol) / vol_sum) if vol_sum else None
        # MFI
        mfi = None
        if i >= window:
            pos = neg = 0.0
            for j in range(i - window + 1, i + 1):
                raw = float(tp[j] * arrays.volume[j])
                if j > 0 and tp[j] > tp[j - 1]:
                    pos += raw
                elif j > 0 and tp[j] < tp[j - 1]:
                    neg += raw
            mfi = 100.0 if neg == 0 else 100.0 - (100.0 / (1.0 + pos / neg))
        up = down = 0.0
        for j in range(i - window + 1, i + 1):
            if j > 0 and arrays.close[j] > arrays.close[j - 1]:
                up += float(arrays.volume[j])
            elif j > 0 and arrays.close[j] < arrays.close[j - 1]:
                down += float(arrays.volume[j])
        vals.update(
            {
                "VWAP_ROLLING": vwap,
                "DISTANCE_TO_VWAP_PCT": (float(arrays.close[i]) - vwap) / vwap * 100.0 if vwap else None,
                "DISTANCE_TO_VWAP_ATR": (float(arrays.close[i]) - vwap) / float(atr[i])
                if vwap and i < len(atr) and not np.isnan(atr[i]) and atr[i]
                else None,
                "CMF": cmf,
                "MFI": mfi,
                "UP_DOWN_VOLUME_RATIO": up / down if down else None,
            }
        )
        samples.append(FeatureSample(ct, ct, vals, True))
    return samples


def _range_width(high, low, i, window):
    hh = float(np.max(high[i - window + 1 : i + 1]))
    ll = float(np.min(low[i - window + 1 : i + 1]))
    return hh, ll, hh - ll


def compute_compression(arrays, short_w: int, long_w: int, threshold: float = 0.5) -> list[FeatureSample]:
    atr = rma(true_range(arrays.high, arrays.low, arrays.close), 14)
    mid20 = sma(arrays.close, 20)
    sd20 = rolling_std(arrays.close, 20)
    bb_width = np.full(len(arrays.close), np.nan)
    for i in range(len(arrays.close)):
        if not np.isnan(mid20[i]) and not np.isnan(sd20[i]) and mid20[i] != 0:
            bb_width[i] = (2 * sd20[i] * 2) / mid20[i]  # (upper-lower)/mid with mult=2
    samples = []
    for i in range(len(arrays.close)):
        ct = arrays.close_time[i]
        vals = {k: None for k in (
            "ROLLING_HIGH", "ROLLING_LOW", "RANGE_WIDTH_ABS", "RANGE_WIDTH_PCT", "RANGE_WIDTH_ATR",
            "ROLLING_STD", "REALIZED_VOLATILITY", "ATR_RELATIVE", "ATR_PERCENTILE",
            "BOLLINGER_WIDTH", "BOLLINGER_WIDTH_PERCENTILE", "COMPRESSION_RATIO", "COMPRESSION_STATE",
        )}
        if i < long_w - 1:
            samples.append(FeatureSample(ct, ct, vals, False, "INVALID_WARMUP"))
            continue
        if not contiguous_ok(arrays.gap_flags, i - long_w + 1, i):
            samples.append(FeatureSample(ct, ct, vals, False, "insufficient_contiguous_history"))
            continue
        sh, sl, sw = _range_width(arrays.high, arrays.low, i, short_w)
        lh, ll, lw = _range_width(arrays.high, arrays.low, i, long_w)
        mid = (sh + sl) / 2.0
        logret = np.diff(np.log(np.maximum(arrays.close[i - long_w + 1 : i + 1], 1e-12)))
        atr_i = float(atr[i]) if not np.isnan(atr[i]) else None
        atr_win = atr[i - long_w + 1 : i + 1]
        atr_pct = float(np.sum(atr_win <= atr[i]) / long_w * 100.0) if atr_i is not None and not np.any(np.isnan(atr_win)) else None
        bb = float(bb_width[i]) if not np.isnan(bb_width[i]) else None
        bb_win = bb_width[max(0, i - long_w + 1) : i + 1]
        bb_pct = float(np.sum(~np.isnan(bb_win) & (bb_win <= bb)) / max(np.sum(~np.isnan(bb_win)), 1) * 100.0) if bb is not None else None
        ratio = sw / lw if lw else None
        vals.update(
            {
                "ROLLING_HIGH": sh,
                "ROLLING_LOW": sl,
                "RANGE_WIDTH_ABS": sw,
                "RANGE_WIDTH_PCT": sw / mid * 100.0 if mid else None,
                "RANGE_WIDTH_ATR": sw / atr_i if atr_i else None,
                "ROLLING_STD": float(np.std(arrays.close[i - short_w + 1 : i + 1], ddof=0)),
                "REALIZED_VOLATILITY": float(np.std(logret, ddof=0)) if len(logret) else None,
                "ATR_RELATIVE": atr_i / float(arrays.close[i]) if atr_i and arrays.close[i] else None,
                "ATR_PERCENTILE": atr_pct,
                "BOLLINGER_WIDTH": bb,
                "BOLLINGER_WIDTH_PERCENTILE": bb_pct,
                "COMPRESSION_RATIO": ratio,
                "COMPRESSION_STATE": bool(ratio is not None and ratio < threshold),
            }
        )
        samples.append(FeatureSample(ct, ct, vals, True))
    return samples


def compute_efficiency(arrays, window: int) -> list[FeatureSample]:
    samples = []
    for i in range(len(arrays.close)):
        ct = arrays.close_time[i]
        vals = {k: None for k in (
            "NET_MOVE", "PATH_LENGTH", "EFFICIENCY_RATIO", "DIRECTIONAL_EFFICIENCY",
            "BAR_OVERLAP_RATIO", "AVERAGE_BAR_OVERLAP", "CLOSE_DISPERSION", "HIGH_LOW_DISPERSION",
        )}
        if i >= 1:
            vals["BAR_OVERLAP_RATIO"] = overlap_ratio(
                float(arrays.high[i - 1]), float(arrays.low[i - 1]), float(arrays.high[i]), float(arrays.low[i])
            )
        if i < window:
            samples.append(FeatureSample(ct, ct, vals, False, "INVALID_WARMUP"))
            continue
        if not contiguous_ok(arrays.gap_flags, i - window, i):
            samples.append(FeatureSample(ct, ct, vals, False, "insufficient_contiguous_history"))
            continue
        net = float(arrays.close[i] - arrays.close[i - window])
        path = float(np.sum(np.abs(np.diff(arrays.close[i - window : i + 1]))))
        overlaps = [
            overlap_ratio(float(arrays.high[j - 1]), float(arrays.low[j - 1]), float(arrays.high[j]), float(arrays.low[j]))
            for j in range(i - window + 1, i + 1)
        ]
        vals.update(
            {
                "NET_MOVE": net,
                "PATH_LENGTH": path,
                "EFFICIENCY_RATIO": abs(net) / path if path else None,
                "DIRECTIONAL_EFFICIENCY": net / path if path else None,
                "AVERAGE_BAR_OVERLAP": float(np.mean(overlaps)),
                "CLOSE_DISPERSION": float(np.std(arrays.close[i - window + 1 : i + 1], ddof=0)),
                "HIGH_LOW_DISPERSION": float(np.mean(arrays.high[i - window + 1 : i + 1] - arrays.low[i - window + 1 : i + 1])),
            }
        )
        samples.append(FeatureSample(ct, ct, vals, True))
    return samples


def compute_range_balance(arrays, window: int) -> list[FeatureSample]:
    samples = []
    for i in range(len(arrays.close)):
        ct = arrays.close_time[i]
        vals = {k: None for k in (
            "BARS_IN_RANGE", "RANGE_OCCUPANCY", "TIME_NEAR_RANGE_MID", "TIME_NEAR_RANGE_HIGH",
            "TIME_NEAR_RANGE_LOW", "CLOSES_INSIDE_CORE_RANGE", "CORE_RANGE_WIDTH", "PRICE_DENSITY",
        )}
        if i < window - 1:
            samples.append(FeatureSample(ct, ct, vals, False, "INVALID_WARMUP"))
            continue
        if not contiguous_ok(arrays.gap_flags, i - window + 1, i):
            samples.append(FeatureSample(ct, ct, vals, False, "insufficient_contiguous_history"))
            continue
        # Range defined by prior bars only within window ending at i (causal)
        hh = float(np.max(arrays.high[i - window + 1 : i + 1]))
        ll = float(np.min(arrays.low[i - window + 1 : i + 1]))
        width = hh - ll
        mid = (hh + ll) / 2.0
        core_lo, core_hi = ll + 0.25 * width, ll + 0.75 * width
        closes = arrays.close[i - window + 1 : i + 1]
        in_range = int(np.sum((closes >= ll) & (closes <= hh)))
        near_mid = int(np.sum(np.abs(closes - mid) <= 0.1 * max(width, 1e-12)))
        near_hi = int(np.sum(closes >= hh - 0.1 * max(width, 1e-12)))
        near_lo = int(np.sum(closes <= ll + 0.1 * max(width, 1e-12)))
        core = int(np.sum((closes >= core_lo) & (closes <= core_hi)))
        vals.update(
            {
                "BARS_IN_RANGE": in_range,
                "RANGE_OCCUPANCY": in_range / window,
                "TIME_NEAR_RANGE_MID": near_mid / window,
                "TIME_NEAR_RANGE_HIGH": near_hi / window,
                "TIME_NEAR_RANGE_LOW": near_lo / window,
                "CLOSES_INSIDE_CORE_RANGE": core,
                "CORE_RANGE_WIDTH": core_hi - core_lo,
                "PRICE_DENSITY": window / width if width else None,
            }
        )
        samples.append(FeatureSample(ct, ct, vals, True))
    return samples


def compute_concentration(arrays, window: int) -> list[FeatureSample]:
    samples = []
    for i in range(len(arrays.close)):
        ct = arrays.close_time[i]
        vals = {k: None for k in (
            "CUMULATIVE_VOLUME_N", "VOLUME_PER_PRICE_RANGE", "VOLUME_PER_ATR_MOVE",
            "CUMULATIVE_VOLUME_OVER_RANGE", "CUMULATIVE_VOLUME_OVER_ABS_NET",
            "HIGH_VOLUME_LOW_PROGRESS_SCORE", "LOW_VOLUME_HIGH_PROGRESS_SCORE",
        )}
        if i < window:
            samples.append(FeatureSample(ct, ct, vals, False, "INVALID_WARMUP"))
            continue
        if not contiguous_ok(arrays.gap_flags, i - window, i):
            samples.append(FeatureSample(ct, ct, vals, False, "insufficient_contiguous_history"))
            continue
        cum_v = float(np.sum(arrays.volume[i - window + 1 : i + 1]))
        hh = float(np.max(arrays.high[i - window + 1 : i + 1]))
        ll = float(np.min(arrays.low[i - window + 1 : i + 1]))
        width = hh - ll
        net = abs(float(arrays.close[i] - arrays.close[i - window]))
        atr = rma(true_range(arrays.high, arrays.low, arrays.close), 14)
        atr_i = float(atr[i]) if not np.isnan(atr[i]) else None
        vals.update(
            {
                "CUMULATIVE_VOLUME_N": cum_v,
                "VOLUME_PER_PRICE_RANGE": cum_v / width if width else None,
                "VOLUME_PER_ATR_MOVE": cum_v / atr_i if atr_i else None,
                "CUMULATIVE_VOLUME_OVER_RANGE": cum_v / width if width else None,
                "CUMULATIVE_VOLUME_OVER_ABS_NET": cum_v / net if net else None,
                "HIGH_VOLUME_LOW_PROGRESS_SCORE": cum_v / (1.0 + net),
                "LOW_VOLUME_HIGH_PROGRESS_SCORE": net / (1.0 + cum_v),
            }
        )
        samples.append(FeatureSample(ct, ct, vals, True))
    return samples


def compute_exhaustion(arrays, window: int) -> list[FeatureSample]:
    atr = rma(true_range(arrays.high, arrays.low, arrays.close), 14)
    body = np.abs(arrays.close - arrays.open)
    samples = []
    # precompute efficiency series for slope
    eff = np.full(len(arrays.close), np.nan)
    for i in range(window, len(arrays.close)):
        net = abs(float(arrays.close[i] - arrays.close[i - window]))
        path = float(np.sum(np.abs(np.diff(arrays.close[i - window : i + 1]))))
        eff[i] = net / path if path else np.nan
    for i in range(len(arrays.close)):
        ct = arrays.close_time[i]
        vals = {k: None for k in (
            "PRICE_SLOPE", "VOLUME_SLOPE", "ATR_SLOPE", "BODY_SIZE_SLOPE", "EFFICIENCY_SLOPE",
            "PRICE_PROGRESS_PER_VOLUME", "PRICE_PROGRESS_PER_ATR",
        )}
        if i >= 1:
            vals["PRICE_SLOPE"] = float(arrays.close[i] - arrays.close[i - 1])
            vals["VOLUME_SLOPE"] = float(arrays.volume[i] - arrays.volume[i - 1])
            if not np.isnan(atr[i]) and not np.isnan(atr[i - 1]):
                vals["ATR_SLOPE"] = float(atr[i] - atr[i - 1])
            vals["BODY_SIZE_SLOPE"] = float(body[i] - body[i - 1])
            if not np.isnan(eff[i]) and not np.isnan(eff[i - 1]):
                vals["EFFICIENCY_SLOPE"] = float(eff[i] - eff[i - 1])
        if i < window:
            samples.append(FeatureSample(ct, ct, vals, False, "INVALID_WARMUP"))
            continue
        net = float(arrays.close[i] - arrays.close[i - window])
        cum_v = float(np.sum(arrays.volume[i - window + 1 : i + 1]))
        atr_i = float(atr[i]) if not np.isnan(atr[i]) else None
        vals["PRICE_PROGRESS_PER_VOLUME"] = net / cum_v if cum_v else None
        vals["PRICE_PROGRESS_PER_ATR"] = net / atr_i if atr_i else None
        samples.append(FeatureSample(ct, ct, vals, True))
    return samples


def compute_rejection_breakout(arrays, window: int, confirm_bars: int = 1) -> list[FeatureSample]:
    """Rejection + breakout attempt counters with causal confirm=1 (same-bar close back inside)."""
    samples = []
    up_att = dn_att = fail_up = fail_dn = 0
    last_attempt_i = last_fail_i = None
    for i in range(len(arrays.close)):
        ct = arrays.close_time[i]
        vals = {k: None for k in (
            "DISTANCE_TO_ROLLING_HIGH", "DISTANCE_TO_ROLLING_LOW", "NEW_HIGH_FLAG", "NEW_LOW_FLAG",
            "BREAKOUT_DISTANCE", "BREAKOUT_VOLUME_RATIO", "BREAKOUT_BODY_RATIO", "BREAKOUT_CLOSE_LOCATION",
            "RETURN_INSIDE_PREVIOUS_RANGE", "UPPER_REJECTION_STRENGTH", "LOWER_REJECTION_STRENGTH",
            "WICK_VOLUME_INTERACTION", "COUNT_UPSIDE_BREAKOUT_ATTEMPTS", "COUNT_DOWNSIDE_BREAKOUT_ATTEMPTS",
            "COUNT_FAILED_UPSIDE_BREAKOUTS", "COUNT_FAILED_DOWNSIDE_BREAKOUTS",
            "TIME_SINCE_LAST_BREAKOUT_ATTEMPT", "TIME_SINCE_LAST_FAILED_BREAKOUT",
        )}
        if i < window:
            samples.append(FeatureSample(ct, ct, vals, False, "INVALID_WARMUP"))
            continue
        # prior range excludes current bar
        prev_h = float(np.max(arrays.high[i - window : i]))
        prev_l = float(np.min(arrays.low[i - window : i]))
        h, l, o, c, v = float(arrays.high[i]), float(arrays.low[i]), float(arrays.open[i]), float(arrays.close[i]), float(arrays.volume[i])
        rng = h - l
        mean_v = float(np.mean(arrays.volume[i - window : i]))
        new_high = h > prev_h
        new_low = l < prev_l
        return_inside = (new_high or new_low) and (prev_l <= c <= prev_h)
        if new_high:
            up_att += 1
            last_attempt_i = i
            if return_inside and confirm_bars >= 1:
                fail_up += 1
                last_fail_i = i
        if new_low:
            dn_att += 1
            last_attempt_i = i
            if return_inside and confirm_bars >= 1:
                fail_dn += 1
                last_fail_i = i
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        vals.update(
            {
                "DISTANCE_TO_ROLLING_HIGH": (c - prev_h) / prev_h * 100.0 if prev_h else None,
                "DISTANCE_TO_ROLLING_LOW": (c - prev_l) / prev_l * 100.0 if prev_l else None,
                "NEW_HIGH_FLAG": new_high,
                "NEW_LOW_FLAG": new_low,
                "BREAKOUT_DISTANCE": (h - prev_h) if new_high else ((prev_l - l) if new_low else 0.0),
                "BREAKOUT_VOLUME_RATIO": v / mean_v if mean_v else None,
                "BREAKOUT_BODY_RATIO": abs(c - o) / rng if rng else None,
                "BREAKOUT_CLOSE_LOCATION": (c - l) / rng if rng else None,
                "RETURN_INSIDE_PREVIOUS_RANGE": return_inside,
                "UPPER_REJECTION_STRENGTH": upper_wick / rng if rng and new_high else (upper_wick / rng if rng else None),
                "LOWER_REJECTION_STRENGTH": lower_wick / rng if rng and new_low else (lower_wick / rng if rng else None),
                "WICK_VOLUME_INTERACTION": (upper_wick + lower_wick) * v if rng else None,
                "COUNT_UPSIDE_BREAKOUT_ATTEMPTS": up_att,
                "COUNT_DOWNSIDE_BREAKOUT_ATTEMPTS": dn_att,
                "COUNT_FAILED_UPSIDE_BREAKOUTS": fail_up,
                "COUNT_FAILED_DOWNSIDE_BREAKOUTS": fail_dn,
                "TIME_SINCE_LAST_BREAKOUT_ATTEMPT": (i - last_attempt_i) if last_attempt_i is not None else None,
                "TIME_SINCE_LAST_FAILED_BREAKOUT": (i - last_fail_i) if last_fail_i is not None else None,
            }
        )
        samples.append(FeatureSample(ct, ct, vals, True))
    return samples


def compute_compression_expansion_duration(arrays, short_w: int, long_w: int, threshold: float, vol_spike_z: float = 2.0) -> list[FeatureSample]:
    """Stateful compression → expansion + duration features. Batch path for streaming parity tests."""
    comp = compute_compression(arrays, short_w, long_w, threshold)
    mean_v = sma(arrays.volume, 20)
    samples = []
    bars_in_comp = 0
    bars_in_balance = 0
    bars_since_exp = 0
    bars_since_spike = 0
    bars_since_nh = 0
    bars_since_nl = 0
    prev_state = False
    for i, base in enumerate(comp):
        ct = arrays.close_time[i]
        if not base.valid:
            samples.append(FeatureSample(ct, ct, {**base.values, "COMPRESSION_DURATION": None, "SECONDS_IN_COMPRESSION": None,
                                                   "BARS_IN_COMPRESSION": None, "BARS_IN_BALANCE": None,
                                                   "SECONDS_IN_BALANCE": None, "BARS_SINCE_RANGE_EXPANSION": None,
                                                   "BARS_SINCE_VOLUME_SPIKE": None, "BARS_SINCE_NEW_HIGH": None,
                                                   "BARS_SINCE_NEW_LOW": None, "CURRENT_RANGE_OVER_PREVIOUS_RANGE": None,
                                                   "CURRENT_ATR_OVER_PREVIOUS_ATR": None, "CURRENT_VOLUME_OVER_COMPRESSION_VOLUME": None,
                                                   "EXPANSION_AFTER_COMPRESSION": False, "BREAKOUT_AFTER_COMPRESSION": False,
                                                   "REJECTION_AFTER_COMPRESSION": False}, False, base.invalid_reason))
            continue
        state = bool(base.values["COMPRESSION_STATE"])
        if state:
            bars_in_comp += 1
            bars_in_balance += 1
        else:
            bars_in_comp = 0
            bars_in_balance = 0
            bars_since_exp += 1
        expansion_after = prev_state and not state
        if expansion_after:
            bars_since_exp = 0
        # volume spike
        z = None
        if i >= 19 and not np.isnan(mean_v[i]):
            w = arrays.volume[i - 19 : i + 1]
            std = float(np.std(w, ddof=0))
            z = (float(arrays.volume[i]) - float(mean_v[i])) / std if std else 0.0
            if z >= vol_spike_z:
                bars_since_spike = 0
            else:
                bars_since_spike += 1
        else:
            bars_since_spike += 1
        if i >= long_w:
            prev_h = float(np.max(arrays.high[i - long_w : i]))
            prev_l = float(np.min(arrays.low[i - long_w : i]))
            if arrays.high[i] > prev_h:
                bars_since_nh = 0
            else:
                bars_since_nh += 1
            if arrays.low[i] < prev_l:
                bars_since_nl = 0
            else:
                bars_since_nl += 1
        # ratios
        cur_r = base.values["RANGE_WIDTH_ABS"]
        # previous range: prior long window ending i-1
        prev_range = None
        if i >= long_w:
            ph = float(np.max(arrays.high[i - long_w : i]))
            pl = float(np.min(arrays.low[i - long_w : i]))
            prev_range = ph - pl
        atr = rma(true_range(arrays.high, arrays.low, arrays.close), 14)
        atr_ratio = None
        if i >= 1 and not np.isnan(atr[i]) and not np.isnan(atr[i - 1]) and atr[i - 1]:
            atr_ratio = float(atr[i] / atr[i - 1])
        # compression volume = mean vol while in compression streak
        vol_ratio = None
        if bars_in_comp > 0:
            vol_ratio = float(arrays.volume[i]) / float(np.mean(arrays.volume[i - bars_in_comp + 1 : i + 1]))
        breakout_after = expansion_after and (
            (i >= long_w and float(arrays.high[i]) > float(np.max(arrays.high[i - long_w : i])))
            or (i >= long_w and float(arrays.low[i]) < float(np.min(arrays.low[i - long_w : i])))
        )
        rejection_after = expansion_after and bool(
            i >= long_w
            and (
                (
                    float(arrays.high[i]) > float(np.max(arrays.high[i - long_w : i]))
                    and float(np.min(arrays.low[i - long_w : i]))
                    <= float(arrays.close[i])
                    <= float(np.max(arrays.high[i - long_w : i]))
                )
                or (
                    float(arrays.low[i]) < float(np.min(arrays.low[i - long_w : i]))
                    and float(np.min(arrays.low[i - long_w : i]))
                    <= float(arrays.close[i])
                    <= float(np.max(arrays.high[i - long_w : i]))
                )
            )
        )
        # seconds approx from bar spacing
        if i >= 1:
            sec = (arrays.close_time[i] - arrays.close_time[i - 1]).total_seconds()
        else:
            sec = 0.0
        vals = {
            **base.values,
            "BARS_IN_COMPRESSION": bars_in_comp,
            "SECONDS_IN_COMPRESSION": bars_in_comp * sec,
            "BARS_IN_BALANCE": bars_in_balance,
            "SECONDS_IN_BALANCE": bars_in_balance * sec,
            "COMPRESSION_DURATION": bars_in_comp,
            "BARS_SINCE_RANGE_EXPANSION": bars_since_exp,
            "BARS_SINCE_VOLUME_SPIKE": bars_since_spike,
            "BARS_SINCE_NEW_HIGH": bars_since_nh,
            "BARS_SINCE_NEW_LOW": bars_since_nl,
            "CURRENT_RANGE_OVER_PREVIOUS_RANGE": (cur_r / prev_range) if (cur_r is not None and prev_range) else None,
            "CURRENT_ATR_OVER_PREVIOUS_ATR": atr_ratio,
            "CURRENT_VOLUME_OVER_COMPRESSION_VOLUME": vol_ratio,
            "EXPANSION_AFTER_COMPRESSION": expansion_after,
            "BREAKOUT_AFTER_COMPRESSION": breakout_after,
            "REJECTION_AFTER_COMPRESSION": rejection_after,
        }
        samples.append(FeatureSample(ct, ct, vals, True))
        prev_state = state
    return samples


def _merge_samples(*series_list: list[FeatureSample]) -> list[FeatureSample]:
    n = len(series_list[0])
    out = []
    for i in range(n):
        vals = {}
        valid = True
        reason = None
        ct = series_list[0][i].calculated_at
        for s in series_list:
            vals.update(s[i].values)
            if not s[i].valid:
                valid = False
                reason = s[i].invalid_reason or reason
        out.append(FeatureSample(ct, ct, vals, valid, None if valid else reason))
    return out


def compute_context_bundle(arrays, params: dict[str, Any]) -> list[FeatureSample]:
    vw = int(params["volume_window"])
    ew = int(params["efficiency_window"])
    rw = int(params["range_window"])
    sw = int(params["short_window"])
    lw = int(params["long_window"])
    thr = float(params["threshold"])
    return _merge_samples(
        compute_volume_intensity(arrays, vw),
        compute_price_volume(arrays, vw),
        compute_efficiency(arrays, ew),
        compute_range_balance(arrays, rw),
        compute_concentration(arrays, vw),
        compute_exhaustion(arrays, vw),
        compute_rejection_breakout(arrays, rw, confirm_bars=1),
        compute_compression_expansion_duration(arrays, sw, lw, thr),
    )


def compute_feature_series(
    bars: Sequence[dict[str, Any]],
    *,
    parameter_set_id: str,
    source_timeframe: str,
) -> FeatureResult:
    if parameter_set_id not in PARAMETER_REGISTRY:
        raise KeyError(parameter_set_id)
    params = PARAMETER_REGISTRY[parameter_set_id]
    clean = sanitize_bars(bars)
    arrays = bars_to_arrays(clean, timeframe=source_timeframe)
    family = params["family"]
    if family == "VOLUME_INTENSITY":
        samples = compute_volume_intensity(arrays, int(params["window"]))
    elif family == "PRICE_VOLUME_INTERACTION":
        samples = compute_price_volume(arrays, int(params["window"]))
    elif family == "EFFICIENCY_CHOP":
        samples = compute_efficiency(arrays, int(params["window"]))
    elif family == "RANGE_BALANCE":
        samples = compute_range_balance(arrays, int(params["window"]))
    elif family == "COMPRESSION":
        samples = compute_compression(arrays, int(params["short_window"]), int(params["long_window"]), float(params["threshold"]))
    elif family == "VOLUME_CONCENTRATION":
        samples = compute_concentration(arrays, int(params["window"]))
    elif family == "EXHAUSTION":
        samples = compute_exhaustion(arrays, int(params["window"]))
    elif family in ("REJECTION", "BREAKOUT_ATTEMPTS"):
        samples = compute_rejection_breakout(arrays, int(params["window"]), int(params.get("confirm_bars", 1)))
    elif family in ("COMPRESSION_EXPANSION", "DURATION"):
        samples = compute_compression_expansion_duration(
            arrays,
            int(params.get("short_window", 10)),
            int(params.get("long_window", 50)),
            float(params.get("threshold", 0.5)),
            float(params.get("vol_spike_z", 2.0)),
        )
    elif family == "CONTEXT_BUNDLE":
        samples = compute_context_bundle(arrays, params)
    else:
        raise KeyError(family)
    return FeatureResult(
        feature_engine_version=FEATURE_ENGINE_VERSION,
        feature_family=family,
        parameter_set_id=parameter_set_id,
        source_timeframe=source_timeframe,
        samples=tuple(samples),
    )


def compute_at_decision_time(
    bars: Sequence[dict[str, Any]],
    *,
    parameter_set_id: str,
    source_timeframe: str,
    decision_time: Any,
) -> FeatureSample | None:
    hist = filter_history_available_at(bars, decision_time, require_closed=True)
    assert_no_forbidden_fields(hist)
    series = compute_feature_series(hist, parameter_set_id=parameter_set_id, source_timeframe=source_timeframe)
    return series.last_valid()
