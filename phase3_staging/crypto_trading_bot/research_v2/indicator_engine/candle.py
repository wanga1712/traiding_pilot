"""Causal candle-structure numerical features."""
from __future__ import annotations

from .bars import BarArrays, displayed_at_for
from .types import IndicatorSample


def compute_candle_series(arrays: BarArrays) -> list[IndicatorSample]:
    samples: list[IndicatorSample] = []
    hh = hl = lh = ll = 0
    for i in range(len(arrays.close)):
        calc_at = arrays.close_time[i]
        disp = displayed_at_for(arrays.close_time, arrays.open_time, i, 0)
        o, h, l, c = float(arrays.open[i]), float(arrays.high[i]), float(arrays.low[i]), float(arrays.close[i])
        body = c - o
        body_abs = abs(body)
        rng = h - l
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        vals = {
            "body_abs": body_abs,
            "body_pct": body_abs / o * 100.0 if o else None,
            "range_abs": rng,
            "range_pct": rng / o * 100.0 if o else None,
            "upper_wick": upper_wick,
            "lower_wick": lower_wick,
            "upper_wick_ratio": upper_wick / rng if rng else None,
            "lower_wick_ratio": lower_wick / rng if rng else None,
            "body_to_range": body_abs / rng if rng else None,
            "close_position_in_range": (c - l) / rng if rng else None,
            "gap": None,
            "successive_higher_high_count": 0,
            "successive_lower_high_count": 0,
            "successive_higher_low_count": 0,
            "successive_lower_low_count": 0,
            "inside_bar": False,
            "outside_bar": False,
            "engulfing_bull": False,
            "engulfing_bear": False,
            "rejection_upper": upper_wick / rng if rng else None,
            "rejection_lower": lower_wick / rng if rng else None,
        }
        if i > 0:
            po, ph, pl, pc = float(arrays.open[i - 1]), float(arrays.high[i - 1]), float(arrays.low[i - 1]), float(arrays.close[i - 1])
            vals["gap"] = o - pc
            if h > ph:
                hh += 1
                lh = 0
            elif h < ph:
                lh += 1
                hh = 0
            else:
                hh = lh = 0
            if l > pl:
                hl += 1
                ll = 0
            elif l < pl:
                ll += 1
                hl = 0
            else:
                hl = ll = 0
            vals["successive_higher_high_count"] = hh
            vals["successive_lower_high_count"] = lh
            vals["successive_higher_low_count"] = hl
            vals["successive_lower_low_count"] = ll
            vals["inside_bar"] = h <= ph and l >= pl
            vals["outside_bar"] = h >= ph and l <= pl
            vals["engulfing_bull"] = body > 0 and (pc - po) < 0 and c >= po and o <= pc
            vals["engulfing_bear"] = body < 0 and (pc - po) > 0 and c <= po and o >= pc
        samples.append(IndicatorSample(calc_at, calc_at, disp, vals, {}, True))
    return samples
