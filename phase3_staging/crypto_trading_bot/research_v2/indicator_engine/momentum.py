"""Momentum family: ROC, Momentum, CCI, Williams %R."""
from __future__ import annotations

import numpy as np

from .bars import BarArrays, contiguous_ok, displayed_at_for
from .math_core import sma, slope_last
from .types import IndicatorSample


def compute_roc_series(arrays: BarArrays, *, period: int = 12) -> list[IndicatorSample]:
    samples: list[IndicatorSample] = []
    for i in range(len(arrays.close)):
        calc_at = arrays.close_time[i]
        disp = displayed_at_for(arrays.close_time, arrays.open_time, i, 0)
        if i < period:
            samples.append(IndicatorSample(calc_at, calc_at, disp, {"roc": None}, valid=False, invalid_reason="warmup"))
            continue
        if not contiguous_ok(arrays.gap_flags, i - period, i):
            samples.append(
                IndicatorSample(calc_at, calc_at, disp, {"roc": None}, valid=False, invalid_reason="insufficient_contiguous_history")
            )
            continue
        prev = float(arrays.close[i - period])
        val = None if prev == 0 else (float(arrays.close[i]) - prev) / prev * 100.0
        samples.append(
            IndicatorSample(
                calc_at,
                calc_at,
                disp,
                {"roc": val},
                {"ROC_SLOPE": None if i == 0 else (val - ((float(arrays.close[i - 1]) - float(arrays.close[i - 1 - period])) / float(arrays.close[i - 1 - period]) * 100.0 if arrays.close[i - 1 - period] != 0 else 0)) if i > period else None,
                 "ROC_CROSS_UP_ZERO": False,
                 "ROC_CROSS_DOWN_ZERO": False},
                valid=True,
            )
        )
        # fix primitives for crosses
        if i > period:
            prev_roc = (float(arrays.close[i - 1]) - float(arrays.close[i - 1 - period])) / float(arrays.close[i - 1 - period]) * 100.0
            prim = dict(samples[-1].signal_primitives)
            prim["ROC_CROSS_UP_ZERO"] = prev_roc <= 0 and (val or 0) > 0
            prim["ROC_CROSS_DOWN_ZERO"] = prev_roc >= 0 and (val or 0) < 0
            prim["ROC_SLOPE"] = (val or 0) - prev_roc
            samples[-1] = IndicatorSample(calc_at, calc_at, disp, {"roc": val}, prim, True)
    return samples


def compute_momentum_series(arrays: BarArrays, *, period: int = 10) -> list[IndicatorSample]:
    samples: list[IndicatorSample] = []
    for i in range(len(arrays.close)):
        calc_at = arrays.close_time[i]
        disp = displayed_at_for(arrays.close_time, arrays.open_time, i, 0)
        if i < period:
            samples.append(IndicatorSample(calc_at, calc_at, disp, {"momentum": None}, valid=False, invalid_reason="warmup"))
            continue
        if not contiguous_ok(arrays.gap_flags, i - period, i):
            samples.append(
                IndicatorSample(calc_at, calc_at, disp, {"momentum": None}, valid=False, invalid_reason="insufficient_contiguous_history")
            )
            continue
        val = float(arrays.close[i] - arrays.close[i - period])
        prim = {"MOMENTUM_SLOPE": None, "MOMENTUM_CROSS_UP_ZERO": False, "MOMENTUM_CROSS_DOWN_ZERO": False}
        if i > period:
            prev = float(arrays.close[i - 1] - arrays.close[i - 1 - period])
            prim["MOMENTUM_SLOPE"] = val - prev
            prim["MOMENTUM_CROSS_UP_ZERO"] = prev <= 0 and val > 0
            prim["MOMENTUM_CROSS_DOWN_ZERO"] = prev >= 0 and val < 0
        samples.append(IndicatorSample(calc_at, calc_at, disp, {"momentum": val}, prim, True))
    return samples


def compute_cci_series(arrays: BarArrays, *, period: int = 20) -> list[IndicatorSample]:
    tp = (arrays.high + arrays.low + arrays.close) / 3.0
    sma_tp = sma(tp, period)
    samples: list[IndicatorSample] = []
    for i in range(len(arrays.close)):
        calc_at = arrays.close_time[i]
        disp = displayed_at_for(arrays.close_time, arrays.open_time, i, 0)
        if i < period - 1 or np.isnan(sma_tp[i]):
            samples.append(IndicatorSample(calc_at, calc_at, disp, {"cci": None}, valid=False, invalid_reason="warmup"))
            continue
        if not contiguous_ok(arrays.gap_flags, i - period + 1, i):
            samples.append(
                IndicatorSample(calc_at, calc_at, disp, {"cci": None}, valid=False, invalid_reason="insufficient_contiguous_history")
            )
            continue
        window = tp[i - period + 1 : i + 1]
        mad = float(np.mean(np.abs(window - sma_tp[i])))
        cci = 0.0 if mad == 0 else (float(tp[i]) - float(sma_tp[i])) / (0.015 * mad)
        prim = {"CCI_SLOPE": slope_last(np.array([np.nan] * i + [cci]), i) if False else None, "CCI_CROSS_UP_ZERO": False, "CCI_CROSS_DOWN_ZERO": False}
        # slope vs previous valid would need series; compute lightly
        samples.append(IndicatorSample(calc_at, calc_at, disp, {"cci": cci}, prim, True))
    # second pass for slope/cross using values
    cci_arr = np.array([s.values["cci"] if s.valid else np.nan for s in samples], dtype=float)
    out: list[IndicatorSample] = []
    for i, s in enumerate(samples):
        if not s.valid:
            out.append(s)
            continue
        prim = {
            "CCI_SLOPE": slope_last(cci_arr, i),
            "CCI_CROSS_UP_ZERO": False,
            "CCI_CROSS_DOWN_ZERO": False,
        }
        if i > 0 and not np.isnan(cci_arr[i - 1]):
            prim["CCI_CROSS_UP_ZERO"] = cci_arr[i - 1] <= 0 and cci_arr[i] > 0
            prim["CCI_CROSS_DOWN_ZERO"] = cci_arr[i - 1] >= 0 and cci_arr[i] < 0
        out.append(IndicatorSample(s.calculated_at, s.available_at, s.displayed_at, s.values, prim, True))
    return out


def compute_williams_r_series(arrays: BarArrays, *, period: int = 14) -> list[IndicatorSample]:
    samples: list[IndicatorSample] = []
    wr = np.full(len(arrays.close), np.nan)
    for i in range(period - 1, len(arrays.close)):
        hh = float(np.max(arrays.high[i - period + 1 : i + 1]))
        ll = float(np.min(arrays.low[i - period + 1 : i + 1]))
        wr[i] = 0.0 if hh == ll else (hh - float(arrays.close[i])) / (hh - ll) * -100.0
    for i in range(len(arrays.close)):
        calc_at = arrays.close_time[i]
        disp = displayed_at_for(arrays.close_time, arrays.open_time, i, 0)
        if i < period - 1 or np.isnan(wr[i]):
            samples.append(IndicatorSample(calc_at, calc_at, disp, {"williams_r": None}, valid=False, invalid_reason="warmup"))
            continue
        if not contiguous_ok(arrays.gap_flags, i - period + 1, i):
            samples.append(
                IndicatorSample(calc_at, calc_at, disp, {"williams_r": None}, valid=False, invalid_reason="insufficient_contiguous_history")
            )
            continue
        val = float(wr[i])
        prim = {
            "WILLIAMS_R_SLOPE": slope_last(wr, i),
            "OVERSOLD": val <= -80,
            "OVERBOUGHT": val >= -20,
        }
        samples.append(IndicatorSample(calc_at, calc_at, disp, {"williams_r": val}, prim, True))
    return samples
