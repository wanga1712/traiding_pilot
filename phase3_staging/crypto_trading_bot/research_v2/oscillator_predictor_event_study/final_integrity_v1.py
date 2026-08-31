"""FINAL-CONTROL-UNIVERSE-AND-RISK-METRICS-FIX-1 helpers."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from .config import (
    BOOTSTRAP_SAMPLES,
    BOOTSTRAP_SEED,
    CONTROL_ATR_BAND,
    CONTROL_DNO_QUANTILE,
    FORWARD_HORIZONS,
)
from .methodology_v2 import (
    CONTROL_DYNAMIC,
    SEMANTICS_FORECAST,
    _outcome_in_split,
    _ts,
)
from .stats import bootstrap_ci, sample_flag, wilson_interval
from .study_engine import ScanContext, _forward_excursions

SCOPE_COMMON = "COMMON_ELIGIBILITY"
SCOPE_NATIVE = "NATIVE_AVAILABILITY"


def fill_forward_outcomes_per_horizon(
    row: dict[str, Any],
    ctx: ScanContext,
    event_idx: int,
    *,
    split_end: datetime,
) -> None:
    """Forward returns + exact-horizon MFE/MAE (pct and ATR)."""
    n = len(ctx.bars)
    atr_e = ctx.atr[event_idx] if event_idx < len(ctx.atr) and np.isfinite(ctx.atr[event_idx]) else None
    base = float(ctx.arrays.close[event_idx])
    for h in FORWARD_HORIZONS:
        if event_idx + h >= n or not _outcome_in_split(ctx.bars, event_idx, h, split_end):
            row[f"forward_return_{h}"] = None
            row[f"reversal_success_{h}"] = None
            row[f"mfe_pct_{h}"] = None
            row[f"mae_pct_{h}"] = None
            row[f"mfe_atr_{h}"] = None
            row[f"mae_atr_{h}"] = None
            continue
        ret = float(ctx.arrays.close[event_idx + h] / base - 1.0)
        row[f"forward_return_{h}"] = ret
        row[f"reversal_success_{h}"] = bool(ret < 0) if row["direction"] == "OB" else bool(ret > 0)
        mfe_pct, mae_pct = _forward_excursions(
            ctx.arrays.high, ctx.arrays.low, ctx.arrays.close, event_idx, h, direction=row["direction"]
        )
        row[f"mfe_pct_{h}"] = mfe_pct
        row[f"mae_pct_{h}"] = mae_pct
        row[f"mfe_atr_{h}"] = (mfe_pct / 100.0 * base / atr_e) if atr_e else None
        row[f"mae_atr_{h}"] = (mae_pct / 100.0 * base / atr_e) if atr_e else None


def common_eligible_mask(
    ctx: ScanContext,
    q_ob: np.ndarray,
    q_os: np.ndarray,
    a_ob: np.ndarray,
    a_os: np.ndarray,
) -> np.ndarray:
    """Decision-bar common eligibility: dynamic valid + ATR + quantile bands available."""
    n = len(ctx.bars)
    mask = np.zeros(n, dtype=bool)
    for t in range(n):
        if not ctx.preds[t].get("valid"):
            continue
        if not np.isfinite(ctx.atr[t]):
            continue
        if not (np.isfinite(q_ob[t]) and np.isfinite(q_os[t])):
            continue
        if not (np.isfinite(a_ob[t]) and np.isfinite(a_os[t])):
            continue
        mask[t] = True
    return mask


def build_final_integrity_events(
    ctx: ScanContext,
    *,
    split_end: datetime,
    q_ob: np.ndarray,
    q_os: np.ndarray,
    a_ob: np.ndarray,
    a_os: np.ndarray,
    common_mask: np.ndarray,
) -> list[dict[str, Any]]:
    """Forecast realization events for all three controls with common-eligible flag."""
    events: list[dict[str, Any]] = []
    for e in ctx.scan_indices:
        if e < 1:
            continue
        decision_prev = e - 1
        pred_prev = ctx.preds[decision_prev]
        event_time = _ts(ctx.bars, e)
        decision_time = _ts(ctx.bars, decision_prev)
        cp = float(ctx.arrays.close[e])
        pp = float(ctx.arrays.close[e - 1])
        high_e = float(ctx.arrays.high[e])
        low_e = float(ctx.arrays.low[e])
        common = bool(common_mask[decision_prev])

        def _emit(control: str, direction: str, level: float, touch: bool) -> None:
            etype = f"FORECAST_{direction}_CROSS"
            row = {
                "timeframe": ctx.timeframe,
                "split": ctx.split,
                "event_semantics": SEMANTICS_FORECAST,
                "event_type": etype,
                "direction": direction,
                "primary": True,
                "control_id": control,
                "decision_index": decision_prev,
                "event_index": e,
                "decision_time": decision_time.isoformat(),
                "event_time": event_time.isoformat(),
                "forecast_level": float(level),
                "intrabar_touch": touch,
                "common_eligible": common,
                "geometry_r_bin": "UNKNOWN",
            }
            fill_forward_outcomes_per_horizon(row, ctx, e, split_end=split_end)
            events.append(row)

        if pred_prev.get("valid"):
            f_ob = pred_prev.get("PREDICTOR_OB_PRICE_NEXT_BAR")
            f_os = pred_prev.get("PREDICTOR_OS_PRICE_NEXT_BAR")
            if f_ob is not None and pp <= float(f_ob) and cp > float(f_ob):
                _emit(CONTROL_DYNAMIC, "OB", float(f_ob), high_e >= float(f_ob))
            if f_os is not None and pp >= float(f_os) and cp < float(f_os):
                _emit(CONTROL_DYNAMIC, "OS", float(f_os), low_e <= float(f_os))

        if np.isfinite(q_ob[decision_prev]) and pp <= float(q_ob[decision_prev]) and cp > float(q_ob[decision_prev]):
            _emit(CONTROL_DNO_QUANTILE, "OB", float(q_ob[decision_prev]), high_e >= float(q_ob[decision_prev]))
        if np.isfinite(q_os[decision_prev]) and pp >= float(q_os[decision_prev]) and cp < float(q_os[decision_prev]):
            _emit(CONTROL_DNO_QUANTILE, "OS", float(q_os[decision_prev]), low_e <= float(q_os[decision_prev]))

        if np.isfinite(a_ob[decision_prev]) and pp <= float(a_ob[decision_prev]) and cp > float(a_ob[decision_prev]):
            _emit(CONTROL_ATR_BAND, "OB", float(a_ob[decision_prev]), high_e >= float(a_ob[decision_prev]))
        if np.isfinite(a_os[decision_prev]) and pp >= float(a_os[decision_prev]) and cp < float(a_os[decision_prev]):
            _emit(CONTROL_ATR_BAND, "OS", float(a_os[decision_prev]), low_e <= float(a_os[decision_prev]))

    return events


def common_eligible_decision_indices(ctx: ScanContext, common_mask: np.ndarray) -> list[int]:
    """Decision bars in split where e=t+1 is also a scan bar (forecast can realize in-split)."""
    scan = set(ctx.scan_indices)
    out = []
    for e in ctx.scan_indices:
        if e < 1:
            continue
        t = e - 1
        if common_mask[t] and e in scan:
            out.append(t)
    return sorted(set(out))


def native_decision_indices(
    ctx: ScanContext,
    control: str,
    *,
    q_ob: np.ndarray,
    q_os: np.ndarray,
) -> list[int]:
    """Control-native decision bars with a possible next-bar realization in-split."""
    out = []
    for e in ctx.scan_indices:
        if e < 1:
            continue
        t = e - 1
        if control == CONTROL_DYNAMIC:
            if ctx.preds[t].get("valid"):
                out.append(t)
        elif control == CONTROL_ATR_BAND:
            if np.isfinite(ctx.atr[t]):
                out.append(t)
        else:
            if np.isfinite(q_ob[t]) and np.isfinite(q_os[t]):
                out.append(t)
    return sorted(set(out))


def _base_rate_on_decisions(
    ctx: ScanContext,
    decisions: list[int],
    *,
    direction: str,
    horizon: int,
    split_end: datetime,
) -> tuple[float | None, int]:
    flags = []
    for t in decisions:
        e = t + 1
        if e >= len(ctx.bars):
            continue
        if e + horizon >= len(ctx.bars):
            continue
        if not _outcome_in_split(ctx.bars, e, horizon, split_end):
            continue
        ret = float(ctx.arrays.close[e + horizon] / ctx.arrays.close[e] - 1.0)
        flags.append(ret < 0 if direction == "OB" else ret > 0)
    if not flags:
        return None, 0
    return float(np.mean(flags)), len(flags)


def aggregate_scoped_comparison(
    events: list[dict[str, Any]],
    contexts: list[ScanContext],
    common_masks: dict[tuple[str, str], np.ndarray],
    control_bands: dict[tuple[str, str], tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]],
    split_ends: dict[str, datetime],
    *,
    comparison_scope: str,
) -> pd.DataFrame:
    if not events:
        return pd.DataFrame()
    df = pd.DataFrame(events)
    df = df[(df["event_semantics"] == SEMANTICS_FORECAST) & (df["primary"] == True)]  # noqa: E712
    if comparison_scope == SCOPE_COMMON:
        df = df[df["common_eligible"] == True]  # noqa: E712
    ctx_map = {(c.timeframe, c.split): c for c in contexts}
    rows = []
    for (tf, split, direction, control), g in df.groupby(["timeframe", "split", "direction", "control_id"]):
        ctx = ctx_map.get((tf, split))
        if ctx is None:
            continue
        split_end = split_ends[split]
        mask = common_masks[(tf, split)]
        q_ob, q_os, _a_ob, _a_os = control_bands[(tf, split)]
        if comparison_scope == SCOPE_COMMON:
            decisions = common_eligible_decision_indices(ctx, mask)
        else:
            decisions = native_decision_indices(ctx, control, q_ob=q_ob, q_os=q_os)

        for horizon in FORWARD_HORIZONS:
            col = f"reversal_success_{horizon}"
            if col not in g.columns:
                continue
            eg = g[g[col].notna()]
            n_ev = len(eg)
            if n_ev == 0:
                continue
            base_rate, n_base = _base_rate_on_decisions(
                ctx, decisions, direction=direction, horizon=horizon, split_end=split_end
            )
            if base_rate is None:
                continue
            event_rate = float(eg[col].mean())
            abs_lift = event_rate - base_rate
            rel_lift = (event_rate / base_rate - 1.0) if base_rate > 0 else None
            wlo, whi = wilson_interval(int(eg[col].sum()), n_ev)
            rets = eg[f"forward_return_{horizon}"].dropna().astype(float).to_numpy()
            mean_ret, ret_lo, ret_hi = bootstrap_ci(rets, seed=BOOTSTRAP_SEED, n_boot=min(BOOTSTRAP_SAMPLES, 500))
            mfe = eg[f"mfe_pct_{horizon}"].dropna().astype(float).to_numpy() if f"mfe_pct_{horizon}" in eg else np.array([])
            mae = eg[f"mae_pct_{horizon}"].dropna().astype(float).to_numpy() if f"mae_pct_{horizon}" in eg else np.array([])
            mfe_atr = eg[f"mfe_atr_{horizon}"].dropna().astype(float).to_numpy() if f"mfe_atr_{horizon}" in eg else np.array([])
            mae_atr = eg[f"mae_atr_{horizon}"].dropna().astype(float).to_numpy() if f"mae_atr_{horizon}" in eg else np.array([])
            mfe_mean, mfe_lo, mfe_hi = bootstrap_ci(mfe, seed=BOOTSTRAP_SEED + 1, n_boot=min(BOOTSTRAP_SAMPLES, 500))
            mae_mean, mae_lo, mae_hi = bootstrap_ci(mae, seed=BOOTSTRAP_SEED + 2, n_boot=min(BOOTSTRAP_SAMPLES, 500))
            mfea_mean, mfea_lo, mfea_hi = bootstrap_ci(mfe_atr, seed=BOOTSTRAP_SEED + 3, n_boot=min(BOOTSTRAP_SAMPLES, 500))
            maea_mean, maea_lo, maea_hi = bootstrap_ci(mae_atr, seed=BOOTSTRAP_SEED + 4, n_boot=min(BOOTSTRAP_SAMPLES, 500))
            rows.append(
                {
                    "timeframe": tf,
                    "split": split,
                    "direction": direction,
                    "control_id": control,
                    "event_semantics": SEMANTICS_FORECAST,
                    "comparison_scope": comparison_scope,
                    "horizon": horizon,
                    "event_count": n_ev,
                    "base_sample_count": n_base,
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
                    "mfe_pct_mean": mfe_mean,
                    "mfe_pct_median": float(np.median(mfe)) if mfe.size else None,
                    "mfe_pct_mean_ci_lo": mfe_lo,
                    "mfe_pct_mean_ci_hi": mfe_hi,
                    "mae_pct_mean": mae_mean,
                    "mae_pct_median": float(np.median(mae)) if mae.size else None,
                    "mae_pct_mean_ci_lo": mae_lo,
                    "mae_pct_mean_ci_hi": mae_hi,
                    "mfe_atr_mean": mfea_mean,
                    "mfe_atr_median": float(np.median(mfe_atr)) if mfe_atr.size else None,
                    "mfe_atr_mean_ci_lo": mfea_lo,
                    "mfe_atr_mean_ci_hi": mfea_hi,
                    "mae_atr_mean": maea_mean,
                    "mae_atr_median": float(np.median(mae_atr)) if mae_atr.size else None,
                    "mae_atr_mean_ci_lo": maea_lo,
                    "mae_atr_mean_ci_hi": maea_hi,
                }
            )
    return pd.DataFrame(rows)


def verify_common_base_rates_identical(comp_df: pd.DataFrame) -> tuple[str, pd.DataFrame]:
    """Numerically assert base_rate identical across 3 controls for each TF/split/dir/horizon."""
    if comp_df.empty:
        return "FAIL", pd.DataFrame()
    g = comp_df[comp_df["comparison_scope"] == SCOPE_COMMON]
    rows = []
    all_ok = True
    for keys, sub in g.groupby(["timeframe", "split", "direction", "horizon"]):
        rates = {}
        for _, r in sub.iterrows():
            rates[r["control_id"]] = float(r["base_rate"])
        needed = {CONTROL_DYNAMIC, CONTROL_DNO_QUANTILE, CONTROL_ATR_BAND}
        if not needed.issubset(rates):
            ok = False
            all_ok = False
        else:
            vals = [rates[c] for c in needed]
            ok = max(vals) - min(vals) < 1e-12
            if not ok:
                all_ok = False
        rows.append(
            {
                "timeframe": keys[0],
                "split": keys[1],
                "direction": keys[2],
                "horizon": keys[3],
                "base_rates": rates,
                "identical": ok,
            }
        )
    return ("PASS" if all_ok and rows else "FAIL"), pd.DataFrame(rows)


def events_per_1000_scoped(
    events: list[dict[str, Any]],
    denominators: dict[tuple[str, str, str], int],
    *,
    comparison_scope: str,
    denominator_label: str,
) -> pd.DataFrame:
    if not events:
        return pd.DataFrame()
    df = pd.DataFrame(events)
    df = df[(df["event_semantics"] == SEMANTICS_FORECAST) & (df["primary"] == True)]  # noqa: E712
    if comparison_scope == SCOPE_COMMON:
        df = df[df["common_eligible"] == True]  # noqa: E712
    rows = []
    for (tf, split, direction, control), g in df.groupby(["timeframe", "split", "direction", "control_id"]):
        if comparison_scope == SCOPE_COMMON:
            denom = denominators.get((tf, split, "COMMON"), 0)
        else:
            denom = denominators.get((tf, split, control), 0)
        n_ev = len(g)
        rows.append(
            {
                "timeframe": tf,
                "split": split,
                "direction": direction,
                "control_id": control,
                "comparison_scope": comparison_scope,
                "denominator_label": denominator_label,
                "denominator_count": denom,
                "event_count": n_ev,
                "events_per_1000": (n_ev / denom * 1000.0) if denom else None,
            }
        )
    return pd.DataFrame(rows)


def compare_dynamic_vs_controls_scoped(comp_df: pd.DataFrame) -> pd.DataFrame:
    if comp_df.empty:
        return pd.DataFrame()
    g = comp_df[comp_df["comparison_scope"] == SCOPE_COMMON]
    rows = []
    keys = ["timeframe", "split", "direction", "horizon", "event_semantics", "comparison_scope"]
    for key_vals, sub in g.groupby(keys):
        dyn = sub[sub["control_id"] == CONTROL_DYNAMIC]
        q = sub[sub["control_id"] == CONTROL_DNO_QUANTILE]
        a = sub[sub["control_id"] == CONTROL_ATR_BAND]
        if dyn.empty:
            continue
        d = dyn.iloc[0]
        row = {k: v for k, v in zip(keys, key_vals)}
        row.update(
            {
                "dynamic_event_count": int(d["event_count"]),
                "dynamic_reversal_rate": float(d["reversal_rate"]),
                "dynamic_absolute_lift": float(d["absolute_lift"]),
                "shared_base_rate": float(d["base_rate"]),
            }
        )
        for name, ctrl in (("quantile", q), ("atr", a)):
            if (
                ctrl.empty
                or sample_flag(int(d["event_count"])) == "N_LT_30"
                or sample_flag(int(ctrl.iloc[0]["event_count"])) == "N_LT_30"
            ):
                row[f"dynamic_minus_{name}_lift"] = None
                row[f"dynamic_minus_{name}_reversal_rate"] = None
                row[f"vs_{name}_class"] = "INSUFFICIENT"
                continue
            c = ctrl.iloc[0]
            d_lift = float(d["absolute_lift"])
            c_lift = float(c["absolute_lift"])
            delta = d_lift - c_lift
            row[f"dynamic_minus_{name}_lift"] = delta
            row[f"dynamic_minus_{name}_reversal_rate"] = float(d["reversal_rate"]) - float(c["reversal_rate"])
            if abs(delta) < 0.01:
                row[f"vs_{name}_class"] = "SIMILAR"
            elif delta > 0:
                row[f"vs_{name}_class"] = "BETTER"
            else:
                row[f"vs_{name}_class"] = "WORSE"
        rows.append(row)
    return pd.DataFrame(rows)


def risk_metrics_complete(comp_df: pd.DataFrame) -> str:
    if comp_df.empty:
        return "FAIL"
    required = [
        "forward_return_mean",
        "forward_return_median",
        "forward_return_mean_ci_lo",
        "forward_return_mean_ci_hi",
        "mfe_pct_mean",
        "mfe_pct_median",
        "mfe_pct_mean_ci_lo",
        "mfe_pct_mean_ci_hi",
        "mae_pct_mean",
        "mae_pct_median",
        "mae_pct_mean_ci_lo",
        "mae_pct_mean_ci_hi",
        "mfe_atr_mean",
        "mfe_atr_median",
        "mfe_atr_mean_ci_lo",
        "mfe_atr_mean_ci_hi",
        "mae_atr_mean",
        "mae_atr_median",
        "mae_atr_mean_ci_lo",
        "mae_atr_mean_ci_hi",
    ]
    if not all(c in comp_df.columns for c in required):
        return "FAIL"
    # at least some non-null MFE atr on common scope h=5
    sub = comp_df[(comp_df["comparison_scope"] == SCOPE_COMMON) & (comp_df["horizon"] == 5)]
    if sub.empty or sub["mfe_pct_mean"].isna().all():
        return "FAIL"
    if sub["mfe_atr_mean"].isna().all():
        return "FAIL"
    return "PASS"


def mfe_mae_exact_horizon_check(events: list[dict[str, Any]]) -> str:
    if not events:
        return "FAIL"
    sample = events[0]
    for h in FORWARD_HORIZONS:
        for prefix in ("mfe_pct", "mae_pct", "mfe_atr", "mae_atr"):
            if f"{prefix}_{h}" not in sample:
                return "FAIL"
    # spot-check: for a row with both h=1 and h=10, values need not be equal when both present
    df = pd.DataFrame(events)
    both = df[df["mfe_pct_1"].notna() & df["mfe_pct_10"].notna()]
    if both.empty:
        return "FAIL"
    # not all equal (would indicate max-horizon reuse)
    if (both["mfe_pct_1"] == both["mfe_pct_10"]).all() and (both["mae_pct_1"] == both["mae_pct_10"]).all():
        # possible but unlikely for all; treat as fail if identical across entire sample
        return "FAIL"
    return "PASS"
