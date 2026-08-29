"""Activity + volume-context gates (filter only; not direction)."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from crypto_trading_bot.research_v2.indicator_engine.bars import bars_to_arrays, parse_ts
from crypto_trading_bot.research_v2.volume_accumulation.compute import (
    compute_compression,
    compute_efficiency,
    compute_volume_intensity,
)


def build_context_frame(bars: list[dict[str, Any]], *, decision_tf: str) -> pd.DataFrame:
    arrays = bars_to_arrays(bars, timeframe=decision_tf)
    vol = compute_volume_intensity(arrays, 20)
    comp = compute_compression(arrays, 10, 50, 0.5)
    eff = compute_efficiency(arrays, 20)
    rows = []
    for i, b in enumerate(bars):
        vv = vol[i].values if vol[i].valid else {}
        cv = comp[i].values if comp[i].valid else {}
        ev = eff[i].values if eff[i].valid else {}
        atr_pct = cv.get("ATR_PERCENTILE")
        bb_pct = cv.get("BOLLINGER_WIDTH_PERCENTILE")
        er = ev.get("EFFICIENCY_RATIO")
        parts = []
        if atr_pct is not None:
            parts.append(float(atr_pct))
        if bb_pct is not None:
            parts.append(float(bb_pct))
        if er is not None:
            parts.append(float(er) * 100.0)
        score = float(np.mean(parts)) if parts else np.nan
        rows.append(
            {
                "close_time": b["close_time"] if isinstance(b["close_time"], str) else parse_ts(b["close_time"]).isoformat(),
                "ATR_PERCENTILE": atr_pct,
                "BOLLINGER_WIDTH_PERCENTILE": bb_pct,
                "EFFICIENCY_RATIO": er,
                "VOLUME_RELATIVE_TO_MEAN": vv.get("VOLUME_RELATIVE_TO_MEAN"),
                "VOLUME_ZSCORE": vv.get("VOLUME_ZSCORE"),
                "COMPRESSION_RATIO": cv.get("COMPRESSION_RATIO"),
                "ACTIVITY_SCORE": score,
            }
        )
    return pd.DataFrame(rows)


def assign_activity(ctx: pd.DataFrame, low_cut: float, high_cut: float) -> pd.DataFrame:
    out = ctx.copy()

    def st(v):
        if pd.isna(v):
            return "UNKNOWN"
        if v < low_cut:
            return "LOW_ACTIVITY"
        if v >= high_cut:
            return "HIGH_ACTIVITY"
        return "NORMAL_ACTIVITY"

    out["ACTIVITY_STATE"] = out["ACTIVITY_SCORE"].map(st)
    return out


def discovery_cuts(ctx: pd.DataFrame) -> tuple[float, float, dict[str, float]]:
    s = ctx["ACTIVITY_SCORE"].dropna()
    low = float(s.quantile(0.33)) if len(s) else 33.0
    high = float(s.quantile(0.66)) if len(s) else 66.0
    thr = {
        "rel_vol_p50": float(ctx["VOLUME_RELATIVE_TO_MEAN"].dropna().quantile(0.50)) if ctx["VOLUME_RELATIVE_TO_MEAN"].notna().any() else 1.0,
        "vz_abs_p50": float(ctx["VOLUME_ZSCORE"].dropna().abs().quantile(0.50)) if ctx["VOLUME_ZSCORE"].notna().any() else 0.5,
        "er_p50": float(ctx["EFFICIENCY_RATIO"].dropna().quantile(0.50)) if ctx["EFFICIENCY_RATIO"].notna().any() else 0.3,
        "comp_p50": float(ctx["COMPRESSION_RATIO"].dropna().quantile(0.50)) if ctx["COMPRESSION_RATIO"].notna().any() else 0.5,
    }
    return low, high, thr


def vol_gate_ok(state: str, gate: str) -> bool:
    if gate == "NO_VOL_GATE":
        return True
    if state == "UNKNOWN":
        return False
    if gate == "EXCLUDE_LOW_ACTIVITY":
        return state != "LOW_ACTIVITY"
    if gate == "REQUIRE_NORMAL_OR_HIGH":
        return state in ("NORMAL_ACTIVITY", "HIGH_ACTIVITY")
    if gate == "REQUIRE_HIGH_ACTIVITY":
        return state == "HIGH_ACTIVITY"
    return True


def volume_gate_ok(row: dict[str, Any], gate: str, thr: dict[str, float]) -> bool:
    if gate == "NO_VOLUME_GATE":
        return True
    if gate == "REL_VOLUME_P50":
        v = row.get("VOLUME_RELATIVE_TO_MEAN")
        return v is not None and v == v and float(v) >= thr["rel_vol_p50"]
    if gate == "VOLUME_ZSCORE_ABS_P50":
        v = row.get("VOLUME_ZSCORE")
        return v is not None and v == v and abs(float(v)) >= thr["vz_abs_p50"]
    if gate == "EFFICIENCY_P50":
        v = row.get("EFFICIENCY_RATIO")
        return v is not None and v == v and float(v) >= thr["er_p50"]
    if gate == "NOT_COMPRESSED":
        v = row.get("COMPRESSION_RATIO")
        return v is not None and v == v and float(v) >= thr["comp_p50"]
    return True
