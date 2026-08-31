"""Methodology-fix event builders — forecast realization + causal controls."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from crypto_trading_bot.research_v2.indicator_engine.bars import parse_ts

from .config import (
    ATR_CONTROL_MULTIPLIER,
    BOOTSTRAP_SAMPLES,
    BOOTSTRAP_SEED,
    CONTROL_ATR_BAND,
    CONTROL_DNO_QUANTILE,
    FORWARD_HORIZONS,
    FROZEN_PREDICTOR_CONFIG,
)
from .stats import bootstrap_ci, distance_bin_label, sample_flag, wilson_interval
from .study_engine import ScanContext, _band_position, _forward_excursions, _quantile_control_prices

CONTROL_DYNAMIC = "PROJECT_DYNAMIC_EXTREMA_V1"
SEMANTICS_FORECAST = "FORECAST_REALIZATION"
SEMANTICS_STATE = "STATE_BAND_CROSS"

DISTANCE_BIN_ORDER = (
    "0.00-0.25",
    "0.25-0.50",
    "0.50-0.75",
    "0.75-1.00",
    "1.00-1.50",
    "1.50-2.00",
    ">2.00",
)


def _ts(bars: list[dict[str, Any]], idx: int) -> datetime:
    t = parse_ts(bars[idx]["close_time"])
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t


def _outcome_in_split(bars: list[dict[str, Any]], idx: int, horizon: int, split_end: datetime) -> bool:
    j = idx + horizon
    if j >= len(bars):
        return False
    return _ts(bars, j) < split_end


def fill_forward_outcomes_boundary_safe(
    row: dict[str, Any],
    ctx: ScanContext,
    event_idx: int,
    *,
    split_end: datetime,
) -> None:
    n = len(ctx.bars)
    for h in FORWARD_HORIZONS:
        if event_idx + h >= n or not _outcome_in_split(ctx.bars, event_idx, h, split_end):
            row[f"forward_return_{h}"] = None
            row[f"reversal_success_{h}"] = None
            continue
        ret = float(ctx.arrays.close[event_idx + h] / ctx.arrays.close[event_idx] - 1.0)
        row[f"forward_return_{h}"] = ret
        row[f"reversal_success_{h}"] = bool(ret < 0) if row["direction"] == "OB" else bool(ret > 0)
    atr_e = ctx.atr[event_idx] if event_idx < len(ctx.atr) and np.isfinite(ctx.atr[event_idx]) else None
    # only use horizons that remain inside split
    max_h = 0
    for h in FORWARD_HORIZONS:
        if event_idx + h < n and _outcome_in_split(ctx.bars, event_idx, h, split_end):
            max_h = h
    if max_h == 0:
        row["mfe_pct"] = None
        row["mae_pct"] = None
        row["mfe_atr"] = None
        row["mae_atr"] = None
        return
    mfe_pct, mae_pct = _forward_excursions(
        ctx.arrays.high, ctx.arrays.low, ctx.arrays.close, event_idx, max_h, direction=row["direction"]
    )
    row["mfe_pct"] = mfe_pct
    row["mae_pct"] = mae_pct
    row["mfe_atr"] = (mfe_pct / 100.0 * float(ctx.arrays.close[event_idx]) / atr_e) if atr_e else None
    row["mae_atr"] = (mae_pct / 100.0 * float(ctx.arrays.close[event_idx]) / atr_e) if atr_e else None


def precompute_control_forecast_bands(
    ctx: ScanContext,
    *,
    decision_indices: list[int] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """At decision t: next-bar forecast bands for quantile and ATR controls.

    Quantile bands are computed only at needed decision indices (scan ∪ scan-1)
    for causality-safe forecast and state-cross comparisons.
    ATR bands are cheap and filled for all finite-ATR bars.
    """
    n = len(ctx.bars)
    q_ob = np.full(n, np.nan)
    q_os = np.full(n, np.nan)
    a_ob = np.full(n, np.nan)
    a_os = np.full(n, np.nan)
    cfg = FROZEN_PREDICTOR_CONFIG
    for idx in range(n):
        if not np.isfinite(ctx.atr[idx]):
            continue
        c = float(ctx.arrays.close[idx])
        a_ob[idx] = c + ATR_CONTROL_MULTIPLIER * float(ctx.atr[idx])
        a_os[idx] = c - ATR_CONTROL_MULTIPLIER * float(ctx.atr[idx])
    if decision_indices is None:
        needed = set(range(n))
    else:
        needed = set()
        for e in decision_indices:
            if e >= 0:
                needed.add(e)
            if e - 1 >= 0:
                needed.add(e - 1)
    for idx in sorted(needed):
        if idx < 0 or idx >= n:
            continue
        if np.isnan(ctx.dno[idx]) and not ctx.preds[idx].get("valid"):
            continue
        ob_p, os_p = _quantile_control_prices(ctx, idx, config=cfg)
        if ob_p is not None:
            q_ob[idx] = ob_p
        if os_p is not None:
            q_os[idx] = os_p
    return q_ob, q_os, a_ob, a_os


def build_methodology_events(
    ctx: ScanContext,
    *,
    split_end: datetime,
    q_ob: np.ndarray,
    q_os: np.ndarray,
    a_ob: np.ndarray,
    a_os: np.ndarray,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    n = len(ctx.bars)
    for e in ctx.scan_indices:
        if e < 1:
            continue
        pred_e = ctx.preds[e]
        pred_prev = ctx.preds[e - 1]
        decision_prev = e - 1
        event_time = _ts(ctx.bars, e)
        decision_time = _ts(ctx.bars, decision_prev)
        cp = float(ctx.arrays.close[e])
        pp = float(ctx.arrays.close[e - 1])
        high_e = float(ctx.arrays.high[e])
        low_e = float(ctx.arrays.low[e])

        # --- FORECAST REALIZATION: dynamic ---
        if pred_prev.get("valid"):
            f_ob = pred_prev.get("PREDICTOR_OB_PRICE_NEXT_BAR")
            f_os = pred_prev.get("PREDICTOR_OS_PRICE_NEXT_BAR")
            if f_ob is not None and pp <= float(f_ob) and cp > float(f_ob):
                row = {
                    "timeframe": ctx.timeframe,
                    "split": ctx.split,
                    "event_semantics": SEMANTICS_FORECAST,
                    "event_type": "FORECAST_OB_CROSS",
                    "direction": "OB",
                    "primary": True,
                    "control_id": CONTROL_DYNAMIC,
                    "decision_index": decision_prev,
                    "event_index": e,
                    "decision_time": decision_time.isoformat(),
                    "event_time": event_time.isoformat(),
                    "forecast_level": float(f_ob),
                    "intrabar_touch": bool(high_e >= float(f_ob)),
                    "band_position": _band_position(pp, f_ob, f_os),
                    "geometry_r": None,
                    "geometry_r_bin": "UNKNOWN",
                }
                fill_forward_outcomes_boundary_safe(row, ctx, e, split_end=split_end)
                events.append(row)
            if f_os is not None and pp >= float(f_os) and cp < float(f_os):
                row = {
                    "timeframe": ctx.timeframe,
                    "split": ctx.split,
                    "event_semantics": SEMANTICS_FORECAST,
                    "event_type": "FORECAST_OS_CROSS",
                    "direction": "OS",
                    "primary": True,
                    "control_id": CONTROL_DYNAMIC,
                    "decision_index": decision_prev,
                    "event_index": e,
                    "decision_time": decision_time.isoformat(),
                    "event_time": event_time.isoformat(),
                    "forecast_level": float(f_os),
                    "intrabar_touch": bool(low_e <= float(f_os)),
                    "band_position": _band_position(pp, f_ob, f_os),
                    "geometry_r": None,
                    "geometry_r_bin": "UNKNOWN",
                }
                fill_forward_outcomes_boundary_safe(row, ctx, e, split_end=split_end)
                events.append(row)

        # --- FORECAST REALIZATION: quantile (band from e-1) ---
        if np.isfinite(q_ob[decision_prev]) and pp <= float(q_ob[decision_prev]) and cp > float(q_ob[decision_prev]):
            row = {
                "timeframe": ctx.timeframe,
                "split": ctx.split,
                "event_semantics": SEMANTICS_FORECAST,
                "event_type": "FORECAST_OB_CROSS",
                "direction": "OB",
                "primary": True,
                "control_id": CONTROL_DNO_QUANTILE,
                "decision_index": decision_prev,
                "event_index": e,
                "decision_time": decision_time.isoformat(),
                "event_time": event_time.isoformat(),
                "forecast_level": float(q_ob[decision_prev]),
                "intrabar_touch": bool(high_e >= float(q_ob[decision_prev])),
                "geometry_r_bin": "UNKNOWN",
            }
            fill_forward_outcomes_boundary_safe(row, ctx, e, split_end=split_end)
            events.append(row)
        if np.isfinite(q_os[decision_prev]) and pp >= float(q_os[decision_prev]) and cp < float(q_os[decision_prev]):
            row = {
                "timeframe": ctx.timeframe,
                "split": ctx.split,
                "event_semantics": SEMANTICS_FORECAST,
                "event_type": "FORECAST_OS_CROSS",
                "direction": "OS",
                "primary": True,
                "control_id": CONTROL_DNO_QUANTILE,
                "decision_index": decision_prev,
                "event_index": e,
                "decision_time": decision_time.isoformat(),
                "event_time": event_time.isoformat(),
                "forecast_level": float(q_os[decision_prev]),
                "intrabar_touch": bool(low_e <= float(q_os[decision_prev])),
                "geometry_r_bin": "UNKNOWN",
            }
            fill_forward_outcomes_boundary_safe(row, ctx, e, split_end=split_end)
            events.append(row)

        # --- FORECAST REALIZATION: ATR (band from e-1 = Close[e-1] ± ATR[e-1]) ---
        if np.isfinite(a_ob[decision_prev]) and pp <= float(a_ob[decision_prev]) and cp > float(a_ob[decision_prev]):
            row = {
                "timeframe": ctx.timeframe,
                "split": ctx.split,
                "event_semantics": SEMANTICS_FORECAST,
                "event_type": "FORECAST_OB_CROSS",
                "direction": "OB",
                "primary": True,
                "control_id": CONTROL_ATR_BAND,
                "decision_index": decision_prev,
                "event_index": e,
                "decision_time": decision_time.isoformat(),
                "event_time": event_time.isoformat(),
                "forecast_level": float(a_ob[decision_prev]),
                "intrabar_touch": bool(high_e >= float(a_ob[decision_prev])),
                "geometry_r_bin": "UNKNOWN",
            }
            fill_forward_outcomes_boundary_safe(row, ctx, e, split_end=split_end)
            events.append(row)
        if np.isfinite(a_os[decision_prev]) and pp >= float(a_os[decision_prev]) and cp < float(a_os[decision_prev]):
            row = {
                "timeframe": ctx.timeframe,
                "split": ctx.split,
                "event_semantics": SEMANTICS_FORECAST,
                "event_type": "FORECAST_OS_CROSS",
                "direction": "OS",
                "primary": True,
                "control_id": CONTROL_ATR_BAND,
                "decision_index": decision_prev,
                "event_index": e,
                "decision_time": decision_time.isoformat(),
                "event_time": event_time.isoformat(),
                "forecast_level": float(a_os[decision_prev]),
                "intrabar_touch": bool(low_e <= float(a_os[decision_prev])),
                "geometry_r_bin": "UNKNOWN",
            }
            fill_forward_outcomes_boundary_safe(row, ctx, e, split_end=split_end)
            events.append(row)

        # --- STATE_BAND_CROSS: keep engine moving-band events (dynamic) ---
        if pred_e.get("valid"):
            for etype, flag, direction in (
                ("STATE_OB_CROSS_UP", "CROSSED_OB_BAND_UP", "OB"),
                ("STATE_OS_CROSS_DOWN", "CROSSED_OS_BAND_DOWN", "OS"),
                ("STATE_OB_CROSS_DOWN", "CROSSED_OB_BAND_DOWN", "OB"),
                ("STATE_OS_CROSS_UP", "CROSSED_OS_BAND_UP", "OS"),
            ):
                if pred_e.get(flag):
                    row = {
                        "timeframe": ctx.timeframe,
                        "split": ctx.split,
                        "event_semantics": SEMANTICS_STATE,
                        "event_type": etype,
                        "direction": direction,
                        "primary": etype in ("STATE_OB_CROSS_UP", "STATE_OS_CROSS_DOWN"),
                        "control_id": CONTROL_DYNAMIC,
                        "decision_index": e,
                        "event_index": e,
                        "decision_time": event_time.isoformat(),
                        "event_time": event_time.isoformat(),
                        "geometry_r_bin": "UNKNOWN",
                    }
                    fill_forward_outcomes_boundary_safe(row, ctx, e, split_end=split_end)
                    events.append(row)

        # --- STATE_BAND_CROSS: quantile with prev_band vs current_band ---
        if (
            np.isfinite(q_ob[e - 1])
            and np.isfinite(q_ob[e])
            and pp <= float(q_ob[e - 1])
            and cp > float(q_ob[e])
        ):
            row = {
                "timeframe": ctx.timeframe,
                "split": ctx.split,
                "event_semantics": SEMANTICS_STATE,
                "event_type": "STATE_OB_CROSS_UP",
                "direction": "OB",
                "primary": True,
                "control_id": CONTROL_DNO_QUANTILE,
                "decision_index": e,
                "event_index": e,
                "decision_time": event_time.isoformat(),
                "event_time": event_time.isoformat(),
                "prev_band": float(q_ob[e - 1]),
                "curr_band": float(q_ob[e]),
                "geometry_r_bin": "UNKNOWN",
            }
            fill_forward_outcomes_boundary_safe(row, ctx, e, split_end=split_end)
            events.append(row)
        if (
            np.isfinite(q_os[e - 1])
            and np.isfinite(q_os[e])
            and pp >= float(q_os[e - 1])
            and cp < float(q_os[e])
        ):
            row = {
                "timeframe": ctx.timeframe,
                "split": ctx.split,
                "event_semantics": SEMANTICS_STATE,
                "event_type": "STATE_OS_CROSS_DOWN",
                "direction": "OS",
                "primary": True,
                "control_id": CONTROL_DNO_QUANTILE,
                "decision_index": e,
                "event_index": e,
                "decision_time": event_time.isoformat(),
                "event_time": event_time.isoformat(),
                "prev_band": float(q_os[e - 1]),
                "curr_band": float(q_os[e]),
                "geometry_r_bin": "UNKNOWN",
            }
            fill_forward_outcomes_boundary_safe(row, ctx, e, split_end=split_end)
            events.append(row)

    return events


def classify_distance_calibration(cal_df: pd.DataFrame) -> pd.DataFrame:
    """Expect reach probability to decrease as distance increases."""
    rows = []
    if cal_df.empty:
        return pd.DataFrame()
    for (tf, split, direction), g in cal_df.groupby(["timeframe", "split", "direction"]):
        ordered = []
        for b in DISTANCE_BIN_ORDER:
            sub = g[g["distance_bin"] == b]
            if sub.empty or int(sub["sample_count"].iloc[0]) < 30:
                continue
            ordered.append(float(sub["next_close_hit_rate"].iloc[0]))
        if len(ordered) < 3:
            label = "INSUFFICIENT"
        else:
            dec = all(ordered[i] >= ordered[i + 1] - 1e-12 for i in range(len(ordered) - 1))
            # mostly: at most one adjacent increase, and first > last
            increases = sum(1 for i in range(len(ordered) - 1) if ordered[i] < ordered[i + 1] - 1e-12)
            if dec:
                label = "MONOTONIC_DECREASING"
            elif increases <= 1 and ordered[0] > ordered[-1]:
                label = "MOSTLY_MONOTONIC_DECREASING"
            else:
                label = "NON_MONOTONIC"
        rows.append(
            {
                "timeframe": tf,
                "split": split,
                "direction": direction,
                "distance_calibration_class": label,
                "bins_used": len(ordered),
            }
        )
    return pd.DataFrame(rows)


def aggregate_control_comparison(
    events: list[dict[str, Any]],
    contexts: list[ScanContext],
    *,
    event_semantics: str = SEMANTICS_FORECAST,
    split_ends: dict[str, datetime] | None = None,
) -> pd.DataFrame:
    if not events:
        return pd.DataFrame()
    df = pd.DataFrame(events)
    df = df[(df["event_semantics"] == event_semantics) & (df["primary"] == True)]  # noqa: E712
    ctx_map = {(c.timeframe, c.split): c for c in contexts}
    split_ends = split_ends or {}
    rows = []
    for (tf, split, direction, control), g in df.groupby(["timeframe", "split", "direction", "control_id"]):
        ctx = ctx_map.get((tf, split))
        if ctx is None:
            continue
        split_end = split_ends.get(split)
        for horizon in FORWARD_HORIZONS:
            col = f"reversal_success_{horizon}"
            if col not in g.columns:
                continue
            eg = g[g[col].notna()]
            n_ev = len(eg)
            if n_ev == 0:
                continue
            base_flags = []
            for idx in ctx.scan_indices:
                if not ctx.preds[idx].get("valid"):
                    continue
                if idx + horizon >= len(ctx.bars):
                    continue
                if split_end is not None and not _outcome_in_split(ctx.bars, idx, horizon, split_end):
                    continue
                ret = float(ctx.arrays.close[idx + horizon] / ctx.arrays.close[idx] - 1.0)
                base_flags.append(ret < 0 if direction == "OB" else ret > 0)
            if not base_flags:
                continue
            base_rate = float(np.mean(base_flags))
            event_rate = float(eg[col].mean())
            abs_lift = event_rate - base_rate
            rel_lift = (event_rate / base_rate - 1.0) if base_rate > 0 else None
            wlo, whi = wilson_interval(int(eg[col].sum()), n_ev)
            rets = eg[f"forward_return_{horizon}"].dropna().astype(float).to_numpy()
            mean_ret, ret_lo, ret_hi = bootstrap_ci(rets, seed=BOOTSTRAP_SEED, n_boot=min(BOOTSTRAP_SAMPLES, 500))
            mfe = eg["mfe_pct"].dropna().astype(float).to_numpy() if "mfe_pct" in eg else np.array([])
            mae = eg["mae_pct"].dropna().astype(float).to_numpy() if "mae_pct" in eg else np.array([])
            mfe_mean, mfe_lo, mfe_hi = bootstrap_ci(mfe, seed=BOOTSTRAP_SEED + 1, n_boot=min(BOOTSTRAP_SAMPLES, 500))
            mae_mean, mae_lo, mae_hi = bootstrap_ci(mae, seed=BOOTSTRAP_SEED + 2, n_boot=min(BOOTSTRAP_SAMPLES, 500))
            rows.append(
                {
                    "timeframe": tf,
                    "split": split,
                    "direction": direction,
                    "control_id": control,
                    "event_semantics": event_semantics,
                    "horizon": horizon,
                    "event_count": n_ev,
                    "sample_flag": sample_flag(n_ev),
                    "reversal_rate": event_rate,
                    "reversal_wilson_lo": wlo,
                    "reversal_wilson_hi": whi,
                    "base_rate": base_rate,
                    "absolute_lift": abs_lift,
                    "relative_lift": rel_lift,
                    "forward_return_mean": mean_ret,
                    "forward_return_median": float(np.median(rets)) if rets.size else None,
                    "forward_return_mean_ci_lo": ret_lo,
                    "forward_return_mean_ci_hi": ret_hi,
                    "mfe_mean": mfe_mean,
                    "mfe_median": float(np.median(mfe)) if mfe.size else None,
                    "mfe_mean_ci_lo": mfe_lo,
                    "mfe_mean_ci_hi": mfe_hi,
                    "mae_mean": mae_mean,
                    "mae_median": float(np.median(mae)) if mae.size else None,
                    "mae_mean_ci_lo": mae_lo,
                    "mae_mean_ci_hi": mae_hi,
                }
            )
    return pd.DataFrame(rows)


def events_per_1000(
    events: list[dict[str, Any]],
    valid_counts: dict[tuple[str, str], int],
    *,
    event_semantics: str = SEMANTICS_FORECAST,
) -> pd.DataFrame:
    if not events:
        return pd.DataFrame()
    df = pd.DataFrame(events)
    df = df[(df["event_semantics"] == event_semantics) & (df["primary"] == True)]  # noqa: E712
    rows = []
    for (tf, split, direction, control), g in df.groupby(["timeframe", "split", "direction", "control_id"]):
        n_valid = valid_counts.get((tf, split), 0)
        n_ev = len(g)
        rows.append(
            {
                "timeframe": tf,
                "split": split,
                "direction": direction,
                "control_id": control,
                "event_semantics": event_semantics,
                "event_count": n_ev,
                "valid_predictor_rows": n_valid,
                "events_per_1000_valid_bars": (n_ev / n_valid * 1000.0) if n_valid else None,
            }
        )
    return pd.DataFrame(rows)


def compare_dynamic_vs_controls(comp_df: pd.DataFrame) -> pd.DataFrame:
    if comp_df.empty:
        return pd.DataFrame()
    rows = []
    keys = ["timeframe", "split", "direction", "horizon", "event_semantics"]
    for key_vals, g in comp_df.groupby(keys):
        dyn = g[g["control_id"] == CONTROL_DYNAMIC]
        q = g[g["control_id"] == CONTROL_DNO_QUANTILE]
        a = g[g["control_id"] == CONTROL_ATR_BAND]
        if dyn.empty:
            continue
        d = dyn.iloc[0]
        row = {k: v for k, v in zip(keys, key_vals)}
        row.update(
            {
                "dynamic_event_count": int(d["event_count"]),
                "dynamic_reversal_rate": float(d["reversal_rate"]),
                "dynamic_absolute_lift": float(d["absolute_lift"]),
            }
        )
        for name, ctrl in (("quantile", q), ("atr", a)):
            if ctrl.empty or sample_flag(int(d["event_count"])) == "N_LT_30" or sample_flag(int(ctrl.iloc[0]["event_count"])) == "N_LT_30":
                row[f"dynamic_minus_{name}_lift"] = None
                row[f"dynamic_minus_{name}_reversal_rate"] = None
                row[f"vs_{name}_class"] = "INSUFFICIENT"
                continue
            c = ctrl.iloc[0]
            d_lift = float(d["absolute_lift"])
            c_lift = float(c["absolute_lift"])
            d_rr = float(d["reversal_rate"])
            c_rr = float(c["reversal_rate"])
            row[f"dynamic_minus_{name}_lift"] = d_lift - c_lift
            row[f"dynamic_minus_{name}_reversal_rate"] = d_rr - c_rr
            delta = d_lift - c_lift
            if abs(delta) < 0.01:
                row[f"vs_{name}_class"] = "SIMILAR"
            elif delta > 0:
                row[f"vs_{name}_class"] = "BETTER"
            else:
                row[f"vs_{name}_class"] = "WORSE"
        rows.append(row)
    return pd.DataFrame(rows)


def summarize_vs_control(cmp_df: pd.DataFrame, col: str) -> str:
    if cmp_df.empty or col not in cmp_df.columns:
        return "INSUFFICIENT"
    val = cmp_df[(cmp_df["split"] == "VALIDATION") & (cmp_df[col] != "INSUFFICIENT")]
    if val.empty:
        return "INSUFFICIENT"
    counts = val[col].value_counts()
    if len(counts) == 1:
        return str(counts.index[0])
    top = counts.index[0]
    if counts.get("BETTER", 0) and counts.get("WORSE", 0):
        return "MIXED"
    return str(top)


def classify_distance_summary(dist_class_df: pd.DataFrame, split: str) -> str:
    if dist_class_df.empty:
        return "INSUFFICIENT"
    g = dist_class_df[dist_class_df["split"] == split]
    if g.empty:
        return "INSUFFICIENT"
    vc = g["distance_calibration_class"].value_counts()
    return str(vc.index[0])


def research_verdict_control_aware(
    *,
    forecast_comp: pd.DataFrame,
    stability: pd.DataFrame,
    vs_q: str,
    vs_a: str,
) -> dict[str, str]:
    # base-rate association from dynamic forecast validation lifts
    dyn = forecast_comp[
        (forecast_comp["control_id"] == CONTROL_DYNAMIC)
        & (forecast_comp["split"] == "VALIDATION")
        & (forecast_comp["horizon"] == 5)
        & (forecast_comp["sample_flag"] != "N_LT_30")
    ] if not forecast_comp.empty else pd.DataFrame()
    if dyn.empty:
        base_assoc = "NOT_SUPPORTED"
        forecast_eff = "NOT_SUPPORTED"
    else:
        pos = (dyn["absolute_lift"] > 0.01).sum()
        neg = (dyn["absolute_lift"] < -0.01).sum()
        if pos >= max(2, len(dyn) // 2):
            base_assoc = "SUPPORTED"
        elif pos >= 1:
            base_assoc = "WEAK"
        else:
            base_assoc = "NOT_SUPPORTED"
        stable_pos = 0
        if not stability.empty:
            stable_pos = len(stability[stability["classification"].isin(["STABLE_POSITIVE", "WEAK_POSITIVE"])])
        if base_assoc == "SUPPORTED" and stable_pos >= 3:
            forecast_eff = "SUPPORTED"
        elif base_assoc in ("SUPPORTED", "WEAK") or stable_pos >= 1:
            forecast_eff = "WEAK"
        else:
            forecast_eff = "NOT_SUPPORTED"

    beyond_control = vs_q in ("BETTER",) or vs_a in ("BETTER",)
    similar_ok = vs_q in ("SIMILAR", "BETTER") or vs_a in ("SIMILAR", "BETTER")
    if forecast_eff == "SUPPORTED" and beyond_control:
        final = "PREDICTOR_EFFECT_SUPPORTED"
    elif forecast_eff in ("SUPPORTED", "WEAK") and similar_ok:
        final = "PREDICTOR_EFFECT_WEAK"
    elif forecast_eff == "SUPPORTED" and vs_q in ("MIXED", "INSUFFICIENT") and vs_a in ("MIXED", "INSUFFICIENT", "SIMILAR"):
        final = "PREDICTOR_EFFECT_WEAK"
    else:
        final = "PREDICTOR_EFFECT_NOT_SUPPORTED"

    low_tfs = {"5m", "15m", "30m", "1H"}
    high_tfs = {"2H", "4H", "6H", "8H", "12H", "1D"}
    low_stab = high_stab = "INSUFFICIENT"
    if not stability.empty:
        low = stability[stability["timeframe"].isin(low_tfs)]
        high = stability[stability["timeframe"].isin(high_tfs)]
        if not low.empty:
            low_stab = str(low["classification"].value_counts().index[0])
        if not high.empty:
            high_stab = str(high["classification"].value_counts().index[0])

    return {
        "BASE_RATE_ASSOCIATION": base_assoc,
        "FORECAST_REALIZATION_EFFECT": forecast_eff,
        "DYNAMIC_VS_DNO_QUANTILE": vs_q,
        "DYNAMIC_VS_ATR": vs_a,
        "LOW_TF_STABILITY": low_stab,
        "HIGH_TF_STABILITY": high_stab,
        "RESEARCH_VERDICT": final,
    }


def best_tf_table(stability: pd.DataFrame, forecast_comp: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if forecast_comp.empty:
        return pd.DataFrame()
    dyn = forecast_comp[
        (forecast_comp["control_id"] == CONTROL_DYNAMIC)
        & (forecast_comp["event_semantics"] == SEMANTICS_FORECAST)
        & (forecast_comp["horizon"] == 5)
    ]
    for (tf, direction), g in dyn.groupby(["timeframe", "direction"]):
        disc = g[g["split"] == "DISCOVERY"]
        val = g[g["split"] == "VALIDATION"]
        if val.empty:
            continue
        vn = int(val.iloc[0]["event_count"])
        if vn < 30:
            continue
        rows.append(
            {
                "timeframe": tf,
                "direction": direction,
                "validation_event_n": vn,
                "sample_flag": sample_flag(vn),
                "validation_lift": float(val.iloc[0]["absolute_lift"]),
                "discovery_lift": float(disc.iloc[0]["absolute_lift"]) if not disc.empty else None,
                "eligible": "PREFERRED" if vn >= 100 else "LOW_SAMPLE",
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["_elig_rank"] = out["eligible"].map({"PREFERRED": 0, "LOW_SAMPLE": 1}).fillna(2)
    return out.sort_values(["_elig_rank", "validation_lift"], ascending=[True, False]).drop(columns=["_elig_rank"])
