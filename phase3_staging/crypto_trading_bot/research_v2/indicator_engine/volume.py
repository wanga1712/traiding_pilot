"""Basic volume transformations (infrastructure only)."""
from __future__ import annotations

import numpy as np

from .bars import BarArrays, contiguous_ok, displayed_at_for
from .math_core import sma, slope_last
from .types import IndicatorSample


def compute_volume_basic_series(arrays: BarArrays, *, period: int = 20) -> list[IndicatorSample]:
    mean_v = sma(arrays.volume, period)
    samples: list[IndicatorSample] = []
    obv = np.zeros(len(arrays.volume))
    for i in range(1, len(arrays.volume)):
        if arrays.close[i] > arrays.close[i - 1]:
            obv[i] = obv[i - 1] + arrays.volume[i]
        elif arrays.close[i] < arrays.close[i - 1]:
            obv[i] = obv[i - 1] - arrays.volume[i]
        else:
            obv[i] = obv[i - 1]

    for i in range(len(arrays.volume)):
        calc_at = arrays.close_time[i]
        disp = displayed_at_for(arrays.close_time, arrays.open_time, i, 0)
        vol = float(arrays.volume[i])
        if i < period - 1 or np.isnan(mean_v[i]):
            samples.append(
                IndicatorSample(
                    calc_at,
                    calc_at,
                    disp,
                    {
                        "volume": vol,
                        "rolling_mean_volume": None,
                        "relative_volume": None,
                        "volume_zscore": None,
                        "volume_change_pct": None,
                        "volume_slope": None,
                        "obv": float(obv[i]),
                    },
                    valid=False,
                    invalid_reason="warmup",
                )
            )
            continue
        if not contiguous_ok(arrays.gap_flags, i - period + 1, i):
            samples.append(
                IndicatorSample(
                    calc_at,
                    calc_at,
                    disp,
                    {"volume": vol, "rolling_mean_volume": None, "relative_volume": None, "volume_zscore": None,
                     "volume_change_pct": None, "volume_slope": None, "obv": float(obv[i])},
                    valid=False,
                    invalid_reason="insufficient_contiguous_history",
                )
            )
            continue
        mv = float(mean_v[i])
        window = arrays.volume[i - period + 1 : i + 1]
        std = float(np.std(window, ddof=0))
        z = (vol - mv) / std if std else 0.0
        chg = None
        if i > 0 and arrays.volume[i - 1] != 0:
            chg = (vol - float(arrays.volume[i - 1])) / float(arrays.volume[i - 1]) * 100.0
        samples.append(
            IndicatorSample(
                calc_at,
                calc_at,
                disp,
                {
                    "volume": vol,
                    "rolling_mean_volume": mv,
                    "relative_volume": vol / mv if mv else None,
                    "volume_zscore": z,
                    "volume_change_pct": chg,
                    "volume_slope": slope_last(arrays.volume.astype(float), i),
                    "obv": float(obv[i]),
                },
                {},
                True,
            )
        )
    return samples
