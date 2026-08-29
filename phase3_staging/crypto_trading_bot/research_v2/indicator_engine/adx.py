"""ADX / DMI (Wilder)."""
from __future__ import annotations

import numpy as np

from .bars import BarArrays, contiguous_ok, displayed_at_for
from .math_core import rma, true_range
from .types import IndicatorSample


def compute_adx_series(arrays: BarArrays, *, period: int = 14) -> list[IndicatorSample]:
    n = len(arrays.close)
    tr = true_range(arrays.high, arrays.low, arrays.close)
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    for i in range(1, n):
        up = float(arrays.high[i] - arrays.high[i - 1])
        down = float(arrays.low[i - 1] - arrays.low[i])
        plus_dm[i] = up if up > down and up > 0 else 0.0
        minus_dm[i] = down if down > up and down > 0 else 0.0

    atr = rma(tr, period)
    plus_di = np.full(n, np.nan)
    minus_di = np.full(n, np.nan)
    dx = np.full(n, np.nan)
    sm_plus = rma(plus_dm, period)
    sm_minus = rma(minus_dm, period)
    for i in range(n):
        if np.isnan(atr[i]) or atr[i] == 0:
            continue
        plus_di[i] = 100.0 * sm_plus[i] / atr[i]
        minus_di[i] = 100.0 * sm_minus[i] / atr[i]
        s = plus_di[i] + minus_di[i]
        dx[i] = 0.0 if s == 0 else 100.0 * abs(plus_di[i] - minus_di[i]) / s

    adx = np.full(n, np.nan)
    # ADX is RMA of DX; first ADX after 2*period-1
    first = 2 * period - 1
    if n > first:
        window = dx[period : first + 1]
        if not np.any(np.isnan(window)):
            adx[first] = float(np.mean(window))
            for i in range(first + 1, n):
                if np.isnan(dx[i]) or np.isnan(adx[i - 1]):
                    continue
                adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period

    samples: list[IndicatorSample] = []
    for i in range(n):
        calc_at = arrays.close_time[i]
        disp = displayed_at_for(arrays.close_time, arrays.open_time, i, 0)
        if i < first or np.isnan(adx[i]):
            samples.append(
                IndicatorSample(
                    calc_at,
                    calc_at,
                    disp,
                    {"adx": None, "plus_di": None, "minus_di": None},
                    valid=False,
                    invalid_reason="warmup",
                )
            )
            continue
        if not contiguous_ok(arrays.gap_flags, max(0, i - first), i):
            samples.append(
                IndicatorSample(
                    calc_at,
                    calc_at,
                    disp,
                    {"adx": None, "plus_di": None, "minus_di": None},
                    valid=False,
                    invalid_reason="insufficient_contiguous_history",
                )
            )
            continue
        pdi, mdi, av = float(plus_di[i]), float(minus_di[i]), float(adx[i])
        prim = {
            "DI_CROSS_UP": False,
            "DI_CROSS_DOWN": False,
            "ADX_RISING": False,
            "ADX_FALLING": False,
            "TREND_STRENGTH": av,
        }
        if i > 0 and not np.isnan(plus_di[i - 1]) and not np.isnan(minus_di[i - 1]):
            prim["DI_CROSS_UP"] = plus_di[i - 1] <= minus_di[i - 1] and pdi > mdi
            prim["DI_CROSS_DOWN"] = plus_di[i - 1] >= minus_di[i - 1] and pdi < mdi
        if i > 0 and not np.isnan(adx[i - 1]):
            prim["ADX_RISING"] = av > float(adx[i - 1])
            prim["ADX_FALLING"] = av < float(adx[i - 1])
        samples.append(
            IndicatorSample(
                calc_at,
                calc_at,
                disp,
                {"adx": av, "plus_di": pdi, "minus_di": mdi},
                prim,
                True,
            )
        )
    return samples
