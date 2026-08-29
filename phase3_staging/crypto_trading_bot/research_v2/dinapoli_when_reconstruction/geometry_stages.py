"""Geometry progress, COP/OP/XOP stages, and SEARCH_FOR_WHEN arms."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from crypto_trading_bot.research_v2.indicator_engine.bars import bars_to_arrays, parse_ts
from crypto_trading_bot.research_v2.indicator_engine.math_core import rma, true_range

from .config import FIB_COP, FIB_OP, FIB_XOP


def stage_from_r(r: float) -> str:
    if r != r or r is None:
        return "UNKNOWN"
    if r < FIB_COP:
        return "PRE_COP"
    if r < FIB_OP:
        return "COP_TO_OP"
    if r < FIB_XOP:
        return "OP_TO_XOP"
    return "POST_XOP"


def build_geometry_frame(
    bars: list[dict[str, Any]],
    wave_pivots: pd.DataFrame,
    *,
    geometry_tf: str,
) -> pd.DataFrame:
    """
    Causal progress_r from last confirmed pivot on geometry_tf.
    progress_r = |close - last_pivot| / max(|prev_leg|, ATR).
    """
    arrays = bars_to_arrays(bars, timeframe=geometry_tf)
    tr = true_range(arrays.high, arrays.low, arrays.close)
    atr = rma(tr, 14)

    piv = wave_pivots.copy()
    if "timeframe" in piv.columns:
        same = piv[piv["timeframe"] == geometry_tf]
        if len(same) >= 30:
            piv = same
    piv["confirmation_time"] = pd.to_datetime(piv["confirmation_time"], utc=True)
    piv = piv.sort_values("confirmation_time").reset_index(drop=True)
    conf_ns = piv["confirmation_time"].astype("int64").to_numpy()
    prices = piv["pivot_price"].astype(float).to_numpy()

    rows = []
    last_j = -1
    for i, b in enumerate(bars):
        ct = parse_ts(b["close_time"])
        ct_ns = pd.Timestamp(ct).value
        while last_j + 1 < len(conf_ns) and conf_ns[last_j + 1] <= ct_ns:
            last_j += 1
        ct_iso = b["close_time"] if isinstance(b["close_time"], str) else ct.isoformat()
        if last_j < 1 or np.isnan(atr[i]):
            rows.append(
                {
                    "close_time": ct_iso,
                    "progress_r": np.nan,
                    "geometry_stage": "UNKNOWN",
                    "last_pivot_price": np.nan,
                }
            )
            continue
        pivot_px = float(prices[last_j])
        prev_px = float(prices[last_j - 1])
        leg = abs(pivot_px - prev_px)
        denom = max(leg, float(atr[i]), 1e-12)
        progress = abs(float(arrays.close[i]) - pivot_px) / denom
        rows.append(
            {
                "close_time": ct_iso,
                "progress_r": progress,
                "geometry_stage": stage_from_r(progress),
                "last_pivot_price": pivot_px,
            }
        )
    return pd.DataFrame(rows)


def empirical_arm_threshold(geometry: pd.DataFrame, events: pd.DataFrame) -> float:
    g = geometry.copy()
    g["close_time"] = pd.to_datetime(g["close_time"], utc=True)
    g = g.sort_values("close_time")
    vals = []
    for _, ev in events.iterrows():
        t = pd.Timestamp(parse_ts(ev["true_pivot_time"]))
        hit = g[g["close_time"] >= t].head(1)
        if hit.empty or pd.isna(hit.iloc[0]["progress_r"]):
            continue
        vals.append(float(hit.iloc[0]["progress_r"]))
    if len(vals) < 20:
        s = geometry["progress_r"].dropna()
        return float(s.quantile(0.50)) if len(s) else 0.5
    return float(np.median(vals))


def geometry_arm_enabled(progress_r: float, stage: str, arm: str, empirical_thr: float) -> bool:
    """SEARCH_FOR_WHEN enabled — not ENTRY."""
    if arm == "NO_GEOMETRY_ARM":
        return True
    if progress_r != progress_r:
        return False
    if arm == "R_GE_0618":
        return progress_r >= FIB_COP
    if arm == "R_GE_1000":
        return progress_r >= FIB_OP
    if arm == "R_GE_1618":
        return progress_r >= FIB_XOP
    if arm == "EMPIRICAL_R_PERCENTILE_ARM":
        return progress_r >= empirical_thr
    if arm == "LEG_PERSISTENCE_R1_ZONE":
        # around OP ±20% as persistence / R≈1 search zone
        return 0.8 <= progress_r <= 1.2
    return True


def map_geometry_to_decision_times(
    geo: pd.DataFrame,
    decision_close_times: list[str],
) -> pd.DataFrame:
    """As-of map: at decision close T, use last geometry sample with close_time <= T."""
    g = geo.copy()
    g["close_time"] = pd.to_datetime(g["close_time"], utc=True)
    g = g.sort_values("close_time")
    dec = pd.DataFrame({"close_time": pd.to_datetime(decision_close_times, utc=True)})
    merged = pd.merge_asof(dec.sort_values("close_time"), g, on="close_time", direction="backward")
    merged["close_time"] = merged["close_time"].map(lambda x: x.isoformat())
    return merged
