"""Core study computations — reach, events, outcomes, controls."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from crypto_trading_bot.research_v2.indicator_engine.bars import bars_to_arrays, parse_ts
from crypto_trading_bot.research_v2.indicator_engine.segments import same_segment, segment_starts_array
from crypto_trading_bot.research_v2.oscillator_predictor.config import PredictorConfig
from crypto_trading_bot.research_v2.oscillator_predictor.dno import compute_masked_dno_series
from crypto_trading_bot.research_v2.oscillator_predictor.dynamic_predictor import compute_predictor_feature_series
from crypto_trading_bot.research_v2.oscillator_predictor.inverse import price_for_next_detrended_value_segment_safe

from .config import (
    ATR_CONTROL_MULTIPLIER,
    CONTROL_ATR_BAND,
    CONTROL_DNO_QUANTILE,
    FORWARD_HORIZONS,
    FROZEN_PREDICTOR_CONFIG,
)
from .stats import distance_bin_label, sample_flag, wilson_interval


@dataclass
class ScanContext:
    timeframe: str
    split: str
    bars: list[dict[str, Any]]
    scan_indices: list[int]
    arrays: Any
    atr: np.ndarray
    dno: np.ndarray
    preds: list[dict[str, Any]]
    effective_first: datetime
    effective_last: datetime
    seg_starts: np.ndarray | None = None


def _atr_array(bars: list[dict[str, Any]]) -> np.ndarray:
    """Segment-aware ATR14 as float array — O(n), no per-bar segment scan."""
    from crypto_trading_bot.research_v2.indicator_engine.math_core import rma, true_range

    arrays = bars_to_arrays(bars, timeframe=str(bars[0].get("timeframe", "1H")))
    tr = true_range(arrays.high, arrays.low, arrays.close, gap_flags=arrays.gap_flags)
    atr = rma(tr, 14, gap_flags=arrays.gap_flags)
    seg_starts = segment_starts_array(arrays.gap_flags)
    out = np.full(len(bars), np.nan)
    for i in range(len(bars)):
        seg_start = int(seg_starts[i])
        if i - seg_start + 1 < 14 or np.isnan(atr[i]):
            continue
        out[i] = float(atr[i])
    return out


def build_scan_context(
    *,
    timeframe: str,
    split: str,
    bars: list[dict[str, Any]],
    scan_indices: list[int],
    effective_first: datetime,
    effective_last: datetime,
    config: PredictorConfig = FROZEN_PREDICTOR_CONFIG,
    arrays: Any | None = None,
    atr: np.ndarray | None = None,
    dno: np.ndarray | None = None,
    preds: list[dict[str, Any]] | None = None,
    seg_starts: np.ndarray | None = None,
) -> ScanContext:
    if arrays is None:
        arrays = bars_to_arrays(bars, timeframe=timeframe)
    if atr is None:
        atr = _atr_array(bars)
    if dno is None:
        dno = compute_masked_dno_series(arrays, period=config.period)
    if preds is None:
        preds = compute_predictor_feature_series(arrays, config=config, atr=atr)
    if seg_starts is None:
        seg_starts = segment_starts_array(arrays.gap_flags)
    return ScanContext(
        timeframe=timeframe,
        split=split,
        bars=bars,
        scan_indices=scan_indices,
        arrays=arrays,
        atr=atr,
        dno=dno,
        preds=preds,
        effective_first=effective_first,
        effective_last=effective_last,
        seg_starts=seg_starts,
    )


def precompute_tf_series(
    bars: list[dict[str, Any]],
    *,
    timeframe: str,
    config: PredictorConfig = FROZEN_PREDICTOR_CONFIG,
) -> tuple[Any, np.ndarray, np.ndarray, list[dict[str, Any]], np.ndarray]:
    """Compute shared predictor/DNO/ATR series once per timeframe."""
    arrays = bars_to_arrays(bars, timeframe=timeframe)
    atr = _atr_array(bars)
    dno = compute_masked_dno_series(arrays, period=config.period)
    preds = compute_predictor_feature_series(arrays, config=config, atr=atr)
    seg_starts = segment_starts_array(arrays.gap_flags)
    return arrays, atr, dno, preds, seg_starts


def _quantile_control_prices(
    ctx: ScanContext,
    idx: int,
    *,
    config: PredictorConfig,
) -> tuple[float | None, float | None]:
    lb = config.lookback
    lo = max(0, idx - lb + 1)
    window = ctx.dno[lo : idx + 1]
    valid_vals = []
    seg = int(ctx.seg_starts[idx]) if ctx.seg_starts is not None else None
    for j, v in enumerate(window):
        gi = lo + j
        if np.isnan(v):
            continue
        if seg is not None:
            if int(ctx.seg_starts[gi]) != seg:
                continue
        elif not same_segment(ctx.arrays.gap_flags, gi, idx):
            continue
        valid_vals.append(float(v))
    if len(valid_vals) < max(10, config.period):
        return None, None
    ob_t = float(np.percentile(valid_vals, 80))
    os_t = float(np.percentile(valid_vals, 20))
    ob_p, _ = price_for_next_detrended_value_segment_safe(
        ctx.arrays.close,
        ctx.arrays.gap_flags,
        idx,
        period=config.period,
        target_oscillator_value=ob_t,
        seg_starts=ctx.seg_starts,
    )
    os_p, _ = price_for_next_detrended_value_segment_safe(
        ctx.arrays.close,
        ctx.arrays.gap_flags,
        idx,
        period=config.period,
        target_oscillator_value=os_t,
        seg_starts=ctx.seg_starts,
    )
    return ob_p, os_p


def _atr_control_prices(ctx: ScanContext, idx: int) -> tuple[float | None, float | None]:
    atr_i = ctx.atr[idx] if idx < len(ctx.atr) else np.nan
    if not np.isfinite(atr_i):
        return None, None
    c = float(ctx.arrays.close[idx])
    return c + ATR_CONTROL_MULTIPLIER * float(atr_i), c - ATR_CONTROL_MULTIPLIER * float(atr_i)


def _band_position(close: float, ob: float | None, os: float | None) -> str:
    if ob is None or os is None:
        return "UNKNOWN"
    if close > ob:
        return "ABOVE_OB"
    if close < os:
        return "BELOW_OS"
    return "INSIDE"


def _forward_excursions(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    idx: int,
    horizon: int,
    *,
    direction: str,
) -> tuple[float, float]:
    seg_h = highs[idx + 1 : idx + 1 + horizon]
    seg_l = lows[idx + 1 : idx + 1 + horizon]
    base = float(closes[idx])
    if direction == "OB":
        mfe = (base - float(np.min(seg_l))) / base * 100.0 if seg_l.size else 0.0
        mae = (float(np.max(seg_h)) - base) / base * 100.0 if seg_h.size else 0.0
    else:
        mfe = (float(np.max(seg_h)) - base) / base * 100.0 if seg_h.size else 0.0
        mae = (base - float(np.min(seg_l))) / base * 100.0 if seg_l.size else 0.0
    return mfe, mae


def build_reach_rows(ctx: ScanContext) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    n = len(ctx.bars)
    for idx in ctx.scan_indices:
        pred = ctx.preds[idx]
        if not pred.get("valid"):
            continue
        if idx + 1 >= n:
            continue
        ob = pred.get("PREDICTOR_OB_PRICE_NEXT_BAR")
        os_p = pred.get("PREDICTOR_OS_PRICE_NEXT_BAR")
        if ob is None or os_p is None:
            continue
        close_n = float(ctx.arrays.close[idx + 1])
        high_n = float(ctx.arrays.high[idx + 1])
        low_n = float(ctx.arrays.low[idx + 1])
        decision_time = parse_ts(ctx.bars[idx]["close_time"])
        rows.append(
            {
                "timeframe": ctx.timeframe,
                "split": ctx.split,
                "decision_index": idx,
                "decision_time": decision_time.isoformat(),
                "predicted_for": parse_ts(ctx.bars[idx + 1]["close_time"]).isoformat(),
                "predictor_ob_price": float(ob),
                "predictor_os_price": float(os_p),
                "ob_distance_pct": pred.get("PRICE_DISTANCE_TO_OB_PCT"),
                "os_distance_pct": pred.get("PRICE_DISTANCE_TO_OS_PCT"),
                "ob_distance_atr": pred.get("PRICE_DISTANCE_TO_OB_ATR"),
                "os_distance_atr": pred.get("PRICE_DISTANCE_TO_OS_ATR"),
                "next_close_at_or_above_ob": bool(close_n >= float(ob)),
                "next_close_at_or_below_os": bool(close_n <= float(os_p)),
                "next_high_touch_ob": bool(high_n >= float(ob)),
                "next_low_touch_os": bool(low_n <= float(os_p)),
                "band_position": _band_position(float(ctx.arrays.close[idx]), ob, os_p),
                "geometry_r": None,
                "geometry_r_bin": "UNKNOWN",
            }
        )
    return rows


def build_cross_event_rows(ctx: ScanContext) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    n = len(ctx.bars)
    cfg = FROZEN_PREDICTOR_CONFIG
    for idx in ctx.scan_indices:
        pred = ctx.preds[idx]
        if not pred.get("valid"):
            continue
        decision_time = parse_ts(ctx.bars[idx]["close_time"])
        ob = pred.get("PREDICTOR_OB_PRICE_NEXT_BAR")
        os_p = pred.get("PREDICTOR_OS_PRICE_NEXT_BAR")
        base = {
            "timeframe": ctx.timeframe,
            "split": ctx.split,
            "decision_time": decision_time.isoformat(),
            "event_time": decision_time.isoformat(),
            "event_index": idx,
            "predictor_ob_price": ob,
            "predictor_os_price": os_p,
            "ob_distance_pct": pred.get("PRICE_DISTANCE_TO_OB_PCT"),
            "os_distance_pct": pred.get("PRICE_DISTANCE_TO_OS_PCT"),
            "ob_distance_atr": pred.get("PRICE_DISTANCE_TO_OB_ATR"),
            "os_distance_atr": pred.get("PRICE_DISTANCE_TO_OS_ATR"),
            "control_id": "PROJECT_DYNAMIC_EXTREMA_V1",
            "band_position": _band_position(float(ctx.arrays.close[idx]), ob, os_p),
            "geometry_r": None,
            "geometry_r_bin": "UNKNOWN",
        }
        for etype, flag in (
            ("OB_EVENT", "CROSSED_OB_BAND_UP"),
            ("OS_EVENT", "CROSSED_OS_BAND_DOWN"),
            ("OB_EVENT_SECONDARY", "CROSSED_OB_BAND_DOWN"),
            ("OS_EVENT_SECONDARY", "CROSSED_OS_BAND_UP"),
        ):
            if pred.get(flag):
                row = dict(base)
                row["event_type"] = etype
                row["direction"] = "OB" if "OB" in etype else "OS"
                row["primary"] = etype in ("OB_EVENT", "OS_EVENT")
                _fill_forward_outcomes(row, ctx, idx)
                events.append(row)

        q_ob, q_os = _quantile_control_prices(ctx, idx, config=cfg)
        if q_ob is not None and idx > 0:
            pp = float(ctx.arrays.close[idx - 1])
            cp = float(ctx.arrays.close[idx])
            if pp <= q_ob and cp > q_ob:
                row = {
                    **base,
                    "event_type": "OB_EVENT",
                    "direction": "OB",
                    "primary": True,
                    "control_id": CONTROL_DNO_QUANTILE,
                    "predictor_ob_price": q_ob,
                }
                _fill_forward_outcomes(row, ctx, idx)
                events.append(row)
        if q_os is not None and idx > 0:
            pp = float(ctx.arrays.close[idx - 1])
            cp = float(ctx.arrays.close[idx])
            if pp >= q_os and cp < q_os:
                row = {
                    **base,
                    "event_type": "OS_EVENT",
                    "direction": "OS",
                    "primary": True,
                    "control_id": CONTROL_DNO_QUANTILE,
                    "predictor_os_price": q_os,
                }
                _fill_forward_outcomes(row, ctx, idx)
                events.append(row)

        a_ob, a_os = _atr_control_prices(ctx, idx)
        if a_ob is not None and idx > 0:
            pp = float(ctx.arrays.close[idx - 1])
            cp = float(ctx.arrays.close[idx])
            if pp <= a_ob and cp > a_ob:
                row = {
                    **base,
                    "event_type": "OB_EVENT",
                    "direction": "OB",
                    "primary": True,
                    "control_id": CONTROL_ATR_BAND,
                    "predictor_ob_price": a_ob,
                }
                _fill_forward_outcomes(row, ctx, idx)
                events.append(row)
        if a_os is not None and idx > 0:
            pp = float(ctx.arrays.close[idx - 1])
            cp = float(ctx.arrays.close[idx])
            if pp >= a_os and cp < a_os:
                row = {
                    **base,
                    "event_type": "OS_EVENT",
                    "direction": "OS",
                    "primary": True,
                    "control_id": CONTROL_ATR_BAND,
                    "predictor_os_price": a_os,
                }
                _fill_forward_outcomes(row, ctx, idx)
                events.append(row)
    return events


def _fill_forward_outcomes(row: dict[str, Any], ctx: ScanContext, idx: int) -> None:
    n = len(ctx.bars)
    for h in FORWARD_HORIZONS:
        if idx + h >= n:
            row[f"forward_return_{h}"] = None
            row[f"reversal_success_{h}"] = None
            continue
        ret = float(ctx.arrays.close[idx + h] / ctx.arrays.close[idx] - 1.0)
        row[f"forward_return_{h}"] = ret
        if row["direction"] == "OB":
            row[f"reversal_success_{h}"] = bool(ret < 0)
        else:
            row[f"reversal_success_{h}"] = bool(ret > 0)
    atr_e = ctx.atr[idx] if idx < len(ctx.atr) and np.isfinite(ctx.atr[idx]) else None
    mfe_pct, mae_pct = _forward_excursions(
        ctx.arrays.high,
        ctx.arrays.low,
        ctx.arrays.close,
        idx,
        max(FORWARD_HORIZONS),
        direction=row["direction"],
    )
    row["mfe_pct"] = mfe_pct
    row["mae_pct"] = mae_pct
    row["mfe_atr"] = (mfe_pct / 100.0 * float(ctx.arrays.close[idx]) / atr_e) if atr_e else None
    row["mae_atr"] = (mae_pct / 100.0 * float(ctx.arrays.close[idx]) / atr_e) if atr_e else None


def aggregate_reach_by_tf(reach_rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not reach_rows:
        return pd.DataFrame()
    df = pd.DataFrame(reach_rows)
    out = []
    for (tf, split), g in df.groupby(["timeframe", "split"]):
        out.append(
            {
                "timeframe": tf,
                "split": split,
                "sample_count": len(g),
                "sample_flag": sample_flag(len(g)),
                "ob_next_close_hit_rate": float(g["next_close_at_or_above_ob"].mean()),
                "os_next_close_hit_rate": float(g["next_close_at_or_below_os"].mean()),
                "ob_next_intrabar_touch_rate": float(g["next_high_touch_ob"].mean()),
                "os_next_intrabar_touch_rate": float(g["next_low_touch_os"].mean()),
            }
        )
    return pd.DataFrame(out)


def aggregate_distance_calibration(reach_rows: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    df = pd.DataFrame(reach_rows) if reach_rows else pd.DataFrame()
    if df.empty:
        return pd.DataFrame()
    for direction, dist_col, hit_close, hit_touch in (
        ("OB", "ob_distance_atr", "next_close_at_or_above_ob", "next_high_touch_ob"),
        ("OS", "os_distance_atr", "next_close_at_or_below_os", "next_low_touch_os"),
    ):
        for (tf, split), g in df.groupby(["timeframe", "split"]):
            g = g.copy()
            g["distance_bin"] = g[dist_col].map(distance_bin_label)
            for b, bg in g.groupby("distance_bin"):
                if b is None or (isinstance(b, float) and np.isnan(b)):
                    continue
                n = len(bg)
                succ_close = int(bg[hit_close].sum())
                succ_touch = int(bg[hit_touch].sum())
                wlo, whi = wilson_interval(succ_close, n)
                rows.append(
                    {
                        "timeframe": tf,
                        "split": split,
                        "direction": direction,
                        "distance_bin": b,
                        "sample_count": n,
                        "sample_flag": sample_flag(n),
                        "next_close_hit_rate": succ_close / n,
                        "next_close_hit_wilson_lo": wlo,
                        "next_close_hit_wilson_hi": whi,
                        "next_intrabar_touch_rate": succ_touch / n,
                    }
                )
    return pd.DataFrame(rows)


def aggregate_reversal_outcomes(events: list[dict[str, Any]]) -> pd.DataFrame:
    if not events:
        return pd.DataFrame()
    df = pd.DataFrame(events)
    df = df[df.get("primary", True) == True]  # noqa: E712
    rows = []
    for (tf, split, direction, control), g in df.groupby(
        ["timeframe", "split", "direction", "control_id"], dropna=False
    ):
        for h in FORWARD_HORIZONS:
            col = f"reversal_success_{h}"
            if col not in g.columns:
                continue
            valid = g[g[col].notna()]
            n = len(valid)
            if n == 0:
                continue
            rate = float(valid[col].mean())
            wlo, whi = wilson_interval(int(valid[col].sum()), n)
            rows.append(
                {
                    "timeframe": tf,
                    "split": split,
                    "direction": direction,
                    "control_id": control,
                    "horizon": h,
                    "sample_count": n,
                    "sample_flag": sample_flag(n),
                    "reversal_rate_event": rate,
                    "reversal_wilson_lo": wlo,
                    "reversal_wilson_hi": whi,
                }
            )
    return pd.DataFrame(rows)


def compute_base_rates_from_contexts(
    contexts: list[ScanContext],
    events: list[dict[str, Any]],
) -> pd.DataFrame:
    rows = []
    ev_df = pd.DataFrame(events)
    ev_df = ev_df[(ev_df.get("primary", True) == True) & (ev_df["control_id"] == "PROJECT_DYNAMIC_EXTREMA_V1")]  # noqa: E712
    ctx_map = {(c.timeframe, c.split): c for c in contexts}
    for (tf, split, direction), eg in ev_df.groupby(["timeframe", "split", "direction"]):
        ctx = ctx_map.get((tf, split))
        if ctx is None:
            continue
        for h in FORWARD_HORIZONS:
            base_flags = []
            for idx in ctx.scan_indices:
                pred = ctx.preds[idx]
                if not pred.get("valid"):
                    continue
                if idx + h >= len(ctx.bars):
                    continue
                ret = float(ctx.arrays.close[idx + h] / ctx.arrays.close[idx] - 1.0)
                if direction == "OB":
                    base_flags.append(ret < 0)
                else:
                    base_flags.append(ret > 0)
            if not base_flags:
                continue
            base_rate = float(np.mean(base_flags))
            eg_h = eg[eg[f"reversal_success_{h}"].notna()]
            if eg_h.empty:
                continue
            event_rate = float(eg_h[f"reversal_success_{h}"].mean())
            abs_lift = event_rate - base_rate
            rel_lift = (event_rate / base_rate - 1.0) if base_rate > 0 else None
            wlo, whi = wilson_interval(int(eg_h[f"reversal_success_{h}"].sum()), len(eg_h))
            rows.append(
                {
                    "timeframe": tf,
                    "split": split,
                    "direction": direction,
                    "horizon": h,
                    "sample_count_event": len(eg_h),
                    "sample_count_base": len(base_flags),
                    "sample_flag_event": sample_flag(len(eg_h)),
                    "sample_flag_base": sample_flag(len(base_flags)),
                    "reversal_rate_event": event_rate,
                    "reversal_rate_base": base_rate,
                    "absolute_lift": abs_lift,
                    "relative_lift": rel_lift,
                    "event_wilson_lo": wlo,
                    "event_wilson_hi": whi,
                }
            )
    return pd.DataFrame(rows)
