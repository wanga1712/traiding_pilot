"""ZigZag normalization (geometry-only) + DiNapoli/R retest across timeframes.

FIXED_ZZ_BASELINE_V1 artifacts must never be overwritten by this module.
"""
from __future__ import annotations

import csv
import json
import math
import random
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median, pstdev
from typing import Any

from crypto_trading_bot.research_v2.dinapoli.multitf_sweep import (
    ALL_PROBE_RATIOS,
    BOOTSTRAP_N,
    BOOTSTRAP_SEED,
    CONTROL_RATIOS,
    NEIGHBORHOOD,
    analyze_tf_windows,
    bootstrap_conditional,
    bootstrap_metric,
    bootstrap_rate,
    mode_density,
    write_csv,
)
from crypto_trading_bot.research_v2.dinapoli.validate_4h import (
    FIB_COP,
    FIB_OP,
    FIB_XOP,
    AbcWindow,
    build_abc_windows,
    chronological_split,
)
from crypto_trading_bot.research_v2.resampling import TIMEFRAMES, UI_TIMEFRAMES
from crypto_trading_bot.research_v2.zigzag.classic import (
    ZigZagPivot,
    classic_atr_zigzag,
    classic_percent_zigzag,
    classic_vol_percent_zigzag,
    compute_atr_series,
)

ATR_NS = (7, 10, 14, 20, 30, 50)
ATR_KS = (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 3.5, 4.0)
ATR_KS_LOW_TF = ATR_KS + (5.0, 6.0, 8.0, 10.0, 12.0, 15.0, 20.0, 25.0, 30.0)
VOL_NS = (10, 14, 20, 30)
VOL_KS = (1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 8.0, 12.0)
DEPTH = 3
BACKSTEP = 0
DISCOVERY_FRAC = 0.70

# Geometry accept bands (NOT DiNapoli / R criteria).
# Prefer clock-time swing significance over bar-ATR multiples:
# fine TF bar-ATR is small, so comparable multi-hour swings need large K*ATR.
PPY_LO, PPY_HI = 30.0, 600.0
MED_BARS_LO = 3.0
MED_HOURS_LO, MED_HOURS_HI = 2.0, 120.0
MOVE_ATR_LO, MOVE_ATR_HI = 1.0, 25.0
MOVE_PCT_LO, MOVE_PCT_HI = 0.8, 25.0
MIN_PIVOTS = 40
STABILITY_MAX_REL_JUMP = 0.45


def _parse_ts(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    text = str(value).replace("Z", "+00:00")
    if text.endswith("+00"):
        text += ":00"
    return datetime.fromisoformat(text)


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return float("nan")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    return sorted_vals[f] * (c - k) + sorted_vals[c] * (k - f)


def candle_discovery_slice(candles: list[dict], frac: float = DISCOVERY_FRAC) -> list[dict]:
    if not candles:
        return []
    cut = max(1, int(round(len(candles) * frac)))
    cut = min(cut, len(candles) - 1) if len(candles) > 1 else len(candles)
    return candles[:cut]


def wave_geometry_stats(
    pivots: list[ZigZagPivot],
    candles: list[dict],
    tf: str,
    *,
    atr_series: list[float] | None = None,
) -> dict[str, Any]:
    minutes = TIMEFRAMES[tf]
    if len(pivots) < 2 or not candles:
        return {
            "pivots": len(pivots),
            "pivots_per_year": None,
            "median_bars_per_leg": None,
            "p25_bars_per_leg": None,
            "p75_bars_per_leg": None,
            "median_hours_per_leg": None,
            "median_move_pct": None,
            "p25_move_pct": None,
            "p75_move_pct": None,
            "median_move_atr": None,
            "span_years": None,
            "acceptable": False,
            "pathology_flags": ["TOO_FEW_PIVOTS"],
        }

    if atr_series is None:
        atr_series = compute_atr_series(candles, 14)

    t0 = _parse_ts(candles[0]["open_time_utc"])
    t1 = _parse_ts(candles[-1]["open_time_utc"])
    span_years = max((t1 - t0).total_seconds() / (365.25 * 86400.0), 1e-9)
    ppy = len(pivots) / span_years
    bars = [pivots[i + 1].index - pivots[i].index for i in range(len(pivots) - 1)]
    hours = [b * minutes / 60.0 for b in bars]
    moves_pct: list[float] = []
    moves_atr: list[float] = []
    for i in range(len(pivots) - 1):
        a, b = float(pivots[i].price), float(pivots[i + 1].price)
        if a != 0:
            moves_pct.append(abs(b - a) / abs(a) * 100.0)
        j = min(max(pivots[i + 1].index, 0), len(atr_series) - 1)
        atr_v = atr_series[j]
        if atr_v and atr_v > 0:
            moves_atr.append(abs(b - a) / atr_v)

    bars_s = sorted(bars)
    moves_s = sorted(moves_pct)
    atr_s = sorted(moves_atr)
    med_bars = median(bars) if bars else None
    med_hours = median(hours) if hours else None
    med_move = median(moves_pct) if moves_pct else None
    med_atr = median(moves_atr) if moves_atr else None

    flags: list[str] = []
    if len(pivots) < MIN_PIVOTS:
        flags.append("LOW_PIVOT_COUNT")
    if ppy > PPY_HI:
        flags.append("TOO_DENSE")
    if ppy < PPY_LO:
        flags.append("TOO_SPARSE")
    if med_bars is not None and med_bars < MED_BARS_LO:
        flags.append("MEDIAN_LEG_TOO_SHORT")
    if med_hours is not None and med_hours < MED_HOURS_LO:
        flags.append("MEDIAN_HOURS_TOO_SHORT")
    if med_hours is not None and med_hours > MED_HOURS_HI:
        flags.append("MEDIAN_HOURS_TOO_LONG")
    if med_move is not None and med_move < MOVE_PCT_LO:
        flags.append("MEDIAN_MOVE_TOO_SMALL")
    if med_move is not None and med_move > MOVE_PCT_HI:
        flags.append("MEDIAN_MOVE_TOO_LARGE")
    if med_atr is not None and med_atr < MOVE_ATR_LO:
        flags.append("MEDIAN_MOVE_ATR_TOO_SMALL")
    if med_atr is not None and med_atr > MOVE_ATR_HI:
        flags.append("MEDIAN_MOVE_ATR_TOO_LARGE")

    return {
        "pivots": len(pivots),
        "pivots_per_year": ppy,
        "median_bars_per_leg": med_bars,
        "p25_bars_per_leg": _percentile(bars_s, 25) if bars_s else None,
        "p75_bars_per_leg": _percentile(bars_s, 75) if bars_s else None,
        "median_hours_per_leg": med_hours,
        "median_move_pct": med_move,
        "p25_move_pct": _percentile(moves_s, 25) if moves_s else None,
        "p75_move_pct": _percentile(moves_s, 75) if moves_s else None,
        "median_move_atr": med_atr,
        "p25_move_atr": _percentile(atr_s, 25) if atr_s else None,
        "p75_move_atr": _percentile(atr_s, 75) if atr_s else None,
        "span_years": span_years,
        "acceptable": len(flags) == 0,
        "pathology_flags": flags,
    }


def geometry_soft_score(stats: dict[str, Any]) -> float:
    """Lower is better. Pure geometry — no R / fib metrics."""
    if stats.get("pivots_per_year") is None:
        return 1e9
    ppy = float(stats["pivots_per_year"])
    # Prefer mid-band ~180 pivots/year
    target_ppy = 180.0
    ppy_pen = abs(math.log(max(ppy, 1e-6)) - math.log(target_ppy))
    bars = float(stats.get("median_bars_per_leg") or 0)
    bars_pen = 0.0 if bars >= MED_BARS_LO else (MED_BARS_LO - bars) * 2.0
    hours = float(stats.get("median_hours_per_leg") or 0)
    # Prefer ~12–24h legs for cross-TF swing significance
    target_hours = 18.0
    hours_pen = abs(math.log(max(hours, 1e-6)) - math.log(target_hours))
    move = float(stats.get("median_move_pct") or 0)
    move_pen = abs(move - 4.0) / 4.0
    hard = 0.0 if stats.get("acceptable") else 25.0
    return hard + ppy_pen * 3.0 + bars_pen + hours_pen * 2.0 + move_pen


def evaluate_atr_config(
    candles: list[dict],
    tf: str,
    *,
    atr_n: int,
    atr_k: float,
    atr_series: list[float] | None = None,
) -> dict[str, Any]:
    series = atr_series if atr_series is not None else compute_atr_series(candles, atr_n)
    pivots = classic_atr_zigzag(
        candles,
        atr_mult=atr_k,
        depth=DEPTH,
        backstep=BACKSTEP,
        atr_period=atr_n,
        atr_series=series,
    )
    stats = wave_geometry_stats(pivots, candles, tf, atr_series=series)
    return {
        "family": "ATR",
        "atr_n": atr_n,
        "atr_k": atr_k,
        "vol_n": None,
        "vol_k": None,
        "depth": DEPTH,
        "backstep": BACKSTEP,
        "label": f"ATR({atr_n})*K={atr_k:g}",
        **stats,
        "soft_score": geometry_soft_score(stats),
    }


def evaluate_vol_config(
    candles: list[dict],
    tf: str,
    *,
    vol_n: int,
    vol_k: float,
) -> dict[str, Any]:
    pivots = classic_vol_percent_zigzag(
        candles,
        vol_mult=vol_k,
        depth=DEPTH,
        backstep=BACKSTEP,
        vol_period=vol_n,
    )
    atr14 = compute_atr_series(candles, 14)
    stats = wave_geometry_stats(pivots, candles, tf, atr_series=atr14)
    return {
        "family": "VOL_PERCENT",
        "atr_n": None,
        "atr_k": None,
        "vol_n": vol_n,
        "vol_k": vol_k,
        "depth": DEPTH,
        "backstep": BACKSTEP,
        "label": f"VOL({vol_n})*K={vol_k:g}",
        **stats,
        "soft_score": geometry_soft_score(stats),
    }


def calibrate_global_atr(
    discovery_by_tf: dict[str, list[dict]],
    timeframes: tuple[str, ...] = UI_TIMEFRAMES,
) -> dict[str, Any]:
    """Select ONE global ATR(N)*K using discovery geometry only."""
    cell: dict[tuple[str, int, float], dict] = {}
    atr_cache: dict[tuple[str, int], list[float]] = {}

    for tf in timeframes:
        candles = discovery_by_tf[tf]
        for n in ATR_NS:
            atr_cache[(tf, n)] = compute_atr_series(candles, n)
            for k in ATR_KS:
                row = evaluate_atr_config(
                    candles,
                    tf,
                    atr_n=n,
                    atr_k=k,
                    atr_series=atr_cache[(tf, n)],
                )
                row["tf"] = tf
                cell[(tf, n, k)] = row
                print(f"[calib] {tf} ATR({n})*K={k:g} ppy={row['pivots_per_year']} ok={row['acceptable']}", flush=True)

    grid_rows = [dict(v) for v in cell.values()]
    global_summaries = []
    k_list = list(ATR_KS)
    for n in ATR_NS:
        for k in ATR_KS:
            per_tf = [cell[(tf, n, k)] for tf in timeframes]
            n_ok = sum(1 for r in per_tf if r["acceptable"])
            mean_score = mean(r["soft_score"] for r in per_tf)
            ppys = [r["pivots_per_year"] for r in per_tf if r["pivots_per_year"]]
            log_disp = pstdev([math.log(max(p, 1e-6)) for p in ppys]) if len(ppys) > 1 else 0.0
            stab_vals = []
            ki = k_list.index(k)
            neighbor_ks = []
            if ki > 0:
                neighbor_ks.append(k_list[ki - 1])
            if ki + 1 < len(k_list):
                neighbor_ks.append(k_list[ki + 1])
            for tf in timeframes:
                base = cell[(tf, n, k)]
                if not base["pivots_per_year"]:
                    continue
                for kk in neighbor_ks:
                    neigh = cell[(tf, n, kk)]
                    if neigh["pivots_per_year"]:
                        stab_vals.append(
                            abs(neigh["pivots_per_year"] - base["pivots_per_year"])
                            / max(base["pivots_per_year"], 1e-9)
                        )
            stab_pen = mean(stab_vals) if stab_vals else 1.0
            unstable = stab_pen > STABILITY_MAX_REL_JUMP
            summary = {
                "family": "ATR",
                "atr_n": n,
                "atr_k": k,
                "label": f"ATR({n})*K={k:g}",
                "n_tf_acceptable": n_ok,
                "n_tf_total": len(timeframes),
                "mean_soft_score": mean_score,
                "log_ppy_dispersion": log_disp,
                "stability_penalty": stab_pen,
                "unstable": unstable,
                "rank_score": (
                    -n_ok * 100.0
                    + mean_score
                    + log_disp * 3.0
                    + (stab_pen * 10.0)
                    + (50.0 if unstable else 0.0)
                ),
                "row_type": "GLOBAL_SUMMARY",
                "tf": "__GLOBAL__",
            }
            global_summaries.append(summary)
            grid_rows.append(summary)

    global_summaries.sort(key=lambda r: (r["rank_score"], r["atr_n"], r["atr_k"]))
    best = global_summaries[0] if global_summaries else None
    # Prefer full coverage; else accept best with >=80% TFs if stable
    global_found = bool(
        best
        and best["n_tf_acceptable"] >= len(timeframes)
        and not best["unstable"]
    )
    if not global_found:
        for cand in global_summaries:
            if cand["n_tf_acceptable"] >= max(8, int(0.8 * len(timeframes))) and not cand["unstable"]:
                best = cand
                global_found = True
                break

    group_configs: dict[str, dict] = {}
    if not global_found:
        groups = {
            "5m-30m": ("5m", "15m", "30m"),
            "1H-4H": ("1H", "2H", "4H"),
            "6H-1D": ("6H", "8H", "12H", "1D"),
        }
        for gname, tfs in groups.items():
            k_space = ATR_KS_LOW_TF if gname == "5m-30m" else ATR_KS
            # Ensure low-TF extended cells exist
            if gname == "5m-30m":
                for tf in tfs:
                    for n in ATR_NS:
                        for k in k_space:
                            if (tf, n, k) not in cell:
                                row = evaluate_atr_config(
                                    discovery_by_tf[tf],
                                    tf,
                                    atr_n=n,
                                    atr_k=k,
                                    atr_series=atr_cache[(tf, n)],
                                )
                                row["tf"] = tf
                                cell[(tf, n, k)] = row
                                print(
                                    f"[calib-low] {tf} ATR({n})*K={k:g} ppy={row['pivots_per_year']} ok={row['acceptable']}",
                                    flush=True,
                                )
            best_g = None
            best_rank = 1e18
            for n in ATR_NS:
                for k in k_space:
                    scores = []
                    ok = 0
                    for tf in tfs:
                        row = cell[(tf, n, k)]
                        scores.append(row["soft_score"])
                        ok += int(row["acceptable"])
                    rank = -ok * 100 + mean(scores)
                    if rank < best_rank:
                        best_rank = rank
                        best_g = {
                            "group": gname,
                            "atr_n": n,
                            "atr_k": k,
                            "label": f"ATR({n})*K={k:g}",
                            "n_tf_acceptable": ok,
                            "n_tf_total": len(tfs),
                        }
            if best_g:
                group_configs[gname] = best_g

    # Family B reference (smaller grid, discovery only)
    vol_summaries = []
    for n in VOL_NS:
        for k in VOL_KS:
            per = [evaluate_vol_config(discovery_by_tf[tf], tf, vol_n=n, vol_k=k) for tf in timeframes]
            n_ok = sum(1 for r in per if r["acceptable"])
            mean_score = mean(r["soft_score"] for r in per)
            vol_summaries.append(
                {
                    "family": "VOL_PERCENT",
                    "vol_n": n,
                    "vol_k": k,
                    "label": f"VOL({n})*K={k:g}",
                    "n_tf_acceptable": n_ok,
                    "mean_soft_score": mean_score,
                    "rank_score": -n_ok * 100 + mean_score,
                }
            )
            print(f"[calib-vol] VOL({n})*K={k:g} ok={n_ok}/{len(timeframes)}", flush=True)
    vol_summaries.sort(key=lambda r: r["rank_score"])
    best_vol = vol_summaries[0] if vol_summaries else None

    return {
        "grid_rows": grid_rows,
        "global_candidate_ranked": global_summaries[:15],
        "best_global": best,
        "global_normalized_zz_found": global_found,
        "group_configs": group_configs,
        "best_vol_global": best_vol,
        "vol_ranked": vol_summaries[:10],
    }


def resolve_tf_config(
    tf: str,
    calib: dict[str, Any],
) -> dict[str, Any]:
    if calib.get("global_normalized_zz_found") and calib.get("best_global"):
        b = calib["best_global"]
        return {
            "family": "ATR",
            "atr_n": b["atr_n"],
            "atr_k": b["atr_k"],
            "label": b["label"],
            "scope": "GLOBAL",
        }
    groups = {
        "5m": "5m-30m",
        "15m": "5m-30m",
        "30m": "5m-30m",
        "1H": "1H-4H",
        "2H": "1H-4H",
        "4H": "1H-4H",
        "6H": "6H-1D",
        "8H": "6H-1D",
        "12H": "6H-1D",
        "1D": "6H-1D",
    }
    g = groups[tf]
    cfg = calib["group_configs"][g]
    return {
        "family": "ATR",
        "atr_n": cfg["atr_n"],
        "atr_k": cfg["atr_k"],
        "label": cfg["label"],
        "scope": g,
    }


def mae(vals: list[float], target: float = 1.0) -> float:
    return mean(abs(v - target) for v in vals) if vals else float("nan")


def mad(vals: list[float], center: float = 1.0) -> float:
    return median(abs(v - center) for v in vals) if vals else float("nan")


def continuous_distribution_verdict(rs: list[float]) -> dict[str, Any]:
    if len(rs) < 30:
        return {"verdict": "INCONCLUSIVE", "reason": "too_few_samples"}
    dens = {f"{c:g}": mode_density(rs, c) for c in ALL_PROBE_RATIOS}
    fib = [dens["0.618"], dens["1"], dens["1.618"]]
    ctrl = [dens[f"{c:g}"] for c in CONTROL_RATIOS]
    fib_edge = mean(fib) - mean(ctrl)
    # Peakiness: max density / mean density
    peakiness = max(dens.values()) / max(mean(dens.values()), 1e-9)
    # Unimodal preference around 1: density at 1 vs neighbors
    d1 = dens["1"]
    near = mean([dens["0.75"], dens["1.25"]])
    # Simple BIC-style proxy: SSE to R=1 vs SSE to nearest fib
    sse_r1 = sum((r - 1.0) ** 2 for r in rs)
    sse_fib = sum(min((r - FIB_COP) ** 2, (r - FIB_OP) ** 2, (r - FIB_XOP) ** 2) for r in rs)
    prefer_continuous = sse_r1 <= sse_fib * 1.05 and fib_edge < 0.02 and peakiness < 2.2
    multimodal = fib_edge >= 0.03 and peakiness >= 2.0
    if multimodal:
        verdict = "MULTIMODAL_TARGETS"
    elif prefer_continuous:
        verdict = "CONTINUOUS_AROUND_1"
    else:
        verdict = "BROAD_MIXTURE"
    return {
        "verdict": verdict,
        "fib_density_edge_vs_controls": fib_edge,
        "peakiness": peakiness,
        "sse_r1": sse_r1,
        "sse_nearest_fib": sse_fib,
        "sse_r1_over_fib": sse_r1 / max(sse_fib, 1e-12),
        "densities": dens,
        "d1_vs_near_controls": d1 - near,
    }


def density_edge(rs: list[float], center: float, controls: tuple[float, ...]) -> float:
    d = mode_density(rs, center)
    cmax = max(mode_density(rs, c) for c in controls)
    return d - cmax


def bootstrap_extra(windows: list[AbcWindow]) -> dict[str, Any]:
    rs = [w.r for w in windows]
    mae_vals = [abs(r - 1.0) for r in rs]
    dens_edge_samples = []
    rng = random.Random(BOOTSTRAP_SEED + 9)
    m = len(rs)
    for _ in range(BOOTSTRAP_N):
        draw = [rs[rng.randrange(m)] for _ in range(m)] if m else []
        if not draw:
            continue
        avg_fib = mean(mode_density(draw, c) for c in (FIB_COP, FIB_OP, FIB_XOP))
        avg_ctrl = mean(mode_density(draw, c) for c in CONTROL_RATIOS)
        dens_edge_samples.append(avg_fib - avg_ctrl)
    dens_edge_samples.sort()
    dens_ci = None
    if dens_edge_samples:
        dens_ci = {
            "point": mean(mode_density(rs, c) for c in (FIB_COP, FIB_OP, FIB_XOP))
            - mean(mode_density(rs, c) for c in CONTROL_RATIOS),
            "lo": dens_edge_samples[int(0.025 * (len(dens_edge_samples) - 1))],
            "hi": dens_edge_samples[int(0.975 * (len(dens_edge_samples) - 1))],
            "n": m,
        }
    return {
        "r_median": bootstrap_metric(rs, fn=median, seed=BOOTSTRAP_SEED),
        "mae_r_eq_1": bootstrap_metric(mae_vals, fn=mean, seed=BOOTSTRAP_SEED + 1),
        "cop_reach": bootstrap_rate([w.cop_reached for w in windows], seed=BOOTSTRAP_SEED + 2),
        "op_reach": bootstrap_rate([w.op_reached for w in windows], seed=BOOTSTRAP_SEED + 3),
        "xop_reach": bootstrap_rate([w.xop_reached for w in windows], seed=BOOTSTRAP_SEED + 4),
        "p_op_given_cop": bootstrap_conditional(
            [w.cop_reached for w in windows],
            [w.op_reached for w in windows],
            seed=BOOTSTRAP_SEED + 5,
        ),
        "p_xop_given_op": bootstrap_conditional(
            [w.op_reached for w in windows],
            [w.xop_reached for w in windows],
            seed=BOOTSTRAP_SEED + 6,
        ),
        "fib_vs_control_density_edge": dens_ci,
    }


def retest_tf(
    candles: list[dict],
    tf: str,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    atr_n = int(cfg["atr_n"])
    atr_k = float(cfg["atr_k"])
    atr = compute_atr_series(candles, atr_n)
    pivots = classic_atr_zigzag(
        candles,
        atr_mult=atr_k,
        depth=DEPTH,
        backstep=BACKSTEP,
        atr_period=atr_n,
        atr_series=atr,
    )
    geom_full = wave_geometry_stats(pivots, candles, tf, atr_series=atr)
    raw = build_abc_windows(pivots, candles, tf=tf, discovery_median_r=None)
    discovery, validation = chronological_split(raw, DISCOVERY_FRAC)
    disc_med = median([w.r for w in discovery]) if discovery else 1.0
    windows = build_abc_windows(pivots, candles, tf=tf, discovery_median_r=disc_med)
    discovery, validation = chronological_split(windows, DISCOVERY_FRAC)
    for w in validation:
        pred = w.c_price + w.ab * disc_med
        w.baseline_median_error_ab = abs(w.d_price - pred) / abs(w.ab) if w.ab else None

    val = analyze_tf_windows(validation, label="VALIDATION")
    disc = analyze_tf_windows(discovery, label="DISCOVERY")
    rs = [w.r for w in validation]
    cont = continuous_distribution_verdict(rs)
    boot = bootstrap_extra(validation)

    # baselines on validation
    mae_r1 = mae(rs, 1.0)
    mad_r1 = mad(rs, 1.0)
    # previous same-direction leg baseline already in summarize as baseline_prev
    prev_errs = [w.baseline_prev_same_dir_error_ab for w in validation if w.baseline_prev_same_dir_error_ab is not None]
    r1_errs = [w.baseline_r1_error_ab for w in validation]
    med_errs = [w.baseline_median_error_ab for w in validation if w.baseline_median_error_ab is not None]
    nearest_fib_err = [w.nearest_error_ab for w in validation]

    return {
        "tf": tf,
        "config": cfg,
        "geometry_full": geom_full,
        "total_pivots": len(pivots),
        "total_windows": len(windows),
        "discovery_windows": len(discovery),
        "validation_windows": len(validation),
        "discovery": disc,
        "validation": val,
        "continuous": cont,
        "bootstrap": boot,
        "r_median": val.get("r_median"),
        "r_iqr": val.get("r_iqr"),
        "r_mean": val.get("r_mean"),
        "r_std": val.get("r_std"),
        "mae_r_eq_1": mae_r1,
        "mad_r_eq_1": mad_r1,
        "median_baseline_r1_error_ab": median(r1_errs) if r1_errs else None,
        "median_baseline_prev_same_dir_error_ab": median(prev_errs) if prev_errs else None,
        "median_baseline_disc_median_r_error_ab": median(med_errs) if med_errs else None,
        "median_nearest_fib_error_ab": median(nearest_fib_err) if nearest_fib_err else None,
        "cop_reach": val.get("cop_reach_rate"),
        "op_reach": val.get("op_reach_rate"),
        "xop_reach": val.get("xop_reach_rate"),
        "p_op_given_cop": val.get("p_op_given_cop"),
        "p_xop_given_op": val.get("p_xop_given_op"),
        "cop_density_edge_vs_controls": density_edge(rs, FIB_COP, (0.50, 0.75)),
        "op_density_edge_vs_controls": density_edge(rs, FIB_OP, (0.75, 1.25)),
        "xop_density_edge_vs_controls": density_edge(rs, FIB_XOP, (1.50, 2.00)),
        "windows_validation": validation,
        "rs_validation": rs,
    }


def classify_evidence(tf_results: list[dict]) -> dict[str, str]:
    eligible = [r for r in tf_results if (r.get("validation_windows") or 0) >= 40]
    if len(eligible) < 3:
        return {
            "cop_ratio_special": "INCONCLUSIVE",
            "op_ratio_special": "INCONCLUSIVE",
            "xop_ratio_special": "INCONCLUSIVE",
            "leg_persistence_supported": "INCONCLUSIVE",
            "continuous_wave_distribution_supported": "INCONCLUSIVE",
            "dinapoli_specific_ratios_supported": "INCONCLUSIVE",
        }

    def special(key: str) -> str:
        vals = [r[key] for r in eligible]
        pos = sum(1 for v in vals if v > 0.02)
        neg = sum(1 for v in vals if v <= 0.01)
        if pos >= max(3, int(0.6 * len(vals))):
            return "YES"
        if neg >= max(3, int(0.7 * len(vals))):
            return "NO"
        return "INCONCLUSIVE"

    r_meds = [r["r_median"] for r in eligible if r.get("r_median") is not None]
    near1 = sum(1 for m in r_meds if abs(m - 1.0) <= 0.10)
    # R=1 baseline competitive with nearest fib endpoint error
    r1_beats_fib = 0
    for r in eligible:
        a = r.get("median_baseline_r1_error_ab")
        b = r.get("median_nearest_fib_error_ab")
        if a is not None and b is not None and a <= b * 1.15:
            # note: nearest-fib error is min distance in R-space to {0.618,1,1.618},
            # so R=1 cannot beat it when R is near 0.618/1.618; compare MAE of R vs 1
            pass
        # Prefer median |R-1| as persistence signal
    mad_ok = sum(1 for r in eligible if (r.get("mad_r_eq_1") or 9) <= 0.65)
    leg = (
        "YES"
        if near1 >= max(3, int(0.8 * len(r_meds))) and mad_ok >= max(2, int(0.5 * len(eligible)))
        else ("NO" if near1 <= 1 else "INCONCLUSIVE")
    )
    # If medians hug 1 across nearly all TFs, upgrade to YES even if MAD is wide.
    if near1 >= max(4, int(0.9 * len(r_meds))):
        leg = "YES"

    cont_votes = [r["continuous"]["verdict"] for r in eligible]
    multi = sum(1 for v in cont_votes if v == "MULTIMODAL_TARGETS")
    contish = sum(1 for v in cont_votes if v in ("CONTINUOUS_AROUND_1", "BROAD_MIXTURE"))
    if multi >= max(3, int(0.6 * len(cont_votes))):
        continuous = "NO"
    elif contish >= max(3, int(0.7 * len(cont_votes))):
        continuous = "YES"
    else:
        continuous = "INCONCLUSIVE"

    cop_s = special("cop_density_edge_vs_controls")
    op_s = special("op_density_edge_vs_controls")
    xop_s = special("xop_density_edge_vs_controls")
    avg_edges = [
        mean(
            [
                r["cop_density_edge_vs_controls"],
                r["op_density_edge_vs_controls"],
                r["xop_density_edge_vs_controls"],
            ]
        )
        for r in eligible
    ]
    weak_fib = sum(1 for e in avg_edges if e <= 0.015)
    dina = "YES" if sum(x == "YES" for x in (cop_s, op_s, xop_s)) >= 2 else (
        "NO"
        if weak_fib >= max(3, int(0.7 * len(avg_edges))) or sum(x == "NO" for x in (cop_s, op_s, xop_s)) >= 2
        else "INCONCLUSIVE"
    )
    # User decision rule: R≈1 + fibs not special → dina unsupported
    if leg == "YES" and dina != "YES" and continuous in ("YES", "INCONCLUSIVE"):
        if weak_fib >= max(3, int(0.6 * len(avg_edges))):
            dina = "NO"
            if continuous == "INCONCLUSIVE":
                continuous = "YES"

    return {
        "cop_ratio_special": cop_s,
        "op_ratio_special": op_s,
        "xop_ratio_special": xop_s,
        "leg_persistence_supported": leg,
        "continuous_wave_distribution_supported": continuous,
        "dinapoli_specific_ratios_supported": dina,
        "r1_near_count": f"{near1}/{len(r_meds)}",
        "weak_fib_edge_count": f"{weak_fib}/{len(avg_edges)}",
    }


def load_fixed_baseline_summary(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def run_normalize_and_retest(
    candles_by_tf: dict[str, list[dict]],
    *,
    out_dir: Path,
    fixed_baseline_summary: Path | None = None,
    timeframes: tuple[str, ...] = UI_TIMEFRAMES,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    discovery_by_tf = {tf: candle_discovery_slice(candles_by_tf[tf]) for tf in timeframes}

    print("[calib] ATR global geometry search on discovery only...", flush=True)
    calib = calibrate_global_atr(discovery_by_tf, timeframes=timeframes)
    print(
        f"[calib] global_found={calib['global_normalized_zz_found']} best={calib.get('best_global')}",
        flush=True,
    )

    tf_results = []
    config_rows = []
    wave_rows = []
    dina_rows = []
    density_rows = []
    val_window_rows = []
    boot_rows = []

    for tf in timeframes:
        cfg = resolve_tf_config(tf, calib)
        print(f"[retest] {tf} cfg={cfg}", flush=True)
        result = retest_tf(candles_by_tf[tf], tf, cfg)
        # discovery geometry of chosen config
        disc = evaluate_atr_config(
            discovery_by_tf[tf],
            tf,
            atr_n=int(cfg["atr_n"]),
            atr_k=float(cfg["atr_k"]),
        )
        config_rows.append(
            {
                "tf": tf,
                "scope": cfg["scope"],
                "family": cfg["family"],
                "atr_n": cfg["atr_n"],
                "atr_k": cfg["atr_k"],
                "label": cfg["label"],
                "depth": DEPTH,
                "backstep": BACKSTEP,
                "discovery_acceptable": disc["acceptable"],
                "discovery_pathology": ";".join(disc["pathology_flags"]),
                "discovery_ppy": disc["pivots_per_year"],
                "discovery_med_bars": disc["median_bars_per_leg"],
                "discovery_med_move_atr": disc["median_move_atr"],
            }
        )
        g = result["geometry_full"]
        wave_rows.append({"tf": tf, "config": cfg["label"], **{k: g[k] for k in g}})
        v = result["validation"]
        dina_rows.append(
            {
                "tf": tf,
                "normalized_zz_config": cfg["label"],
                "scope": cfg["scope"],
                "pivots": result["total_pivots"],
                "val_windows": result["validation_windows"],
                "pivots_per_year": g.get("pivots_per_year"),
                "median_move_atr": g.get("median_move_atr"),
                "median_bars_per_leg": g.get("median_bars_per_leg"),
                "r_median": result["r_median"],
                "r_iqr": result["r_iqr"],
                "r_mean": result["r_mean"],
                "r_std": result["r_std"],
                "mae_r_eq_1": result["mae_r_eq_1"],
                "mad_r_eq_1": result["mad_r_eq_1"],
                "cop_reach": result["cop_reach"],
                "op_reach": result["op_reach"],
                "xop_reach": result["xop_reach"],
                "p_op_given_cop": result["p_op_given_cop"],
                "p_xop_given_op": result["p_xop_given_op"],
                "cop_density_edge_vs_controls": result["cop_density_edge_vs_controls"],
                "op_density_edge_vs_controls": result["op_density_edge_vs_controls"],
                "xop_density_edge_vs_controls": result["xop_density_edge_vs_controls"],
                "median_baseline_r1_error_ab": result["median_baseline_r1_error_ab"],
                "median_baseline_prev_same_dir_error_ab": result["median_baseline_prev_same_dir_error_ab"],
                "median_nearest_fib_error_ab": result["median_nearest_fib_error_ab"],
                "continuous_verdict": result["continuous"]["verdict"],
                "geometry_acceptable": g.get("acceptable"),
                "pathology_flags": ";".join(g.get("pathology_flags") or []),
            }
        )
        dens = (v.get("mode_density") or {})
        for ratio, d in dens.items():
            density_rows.append(
                {
                    "tf": tf,
                    "ratio": ratio,
                    "density_pm_0_10": d,
                    "n": result["validation_windows"],
                    "config": cfg["label"],
                }
            )
        for w in result["windows_validation"]:
            val_window_rows.append(asdict(w))
        for metric, payload in result["bootstrap"].items():
            if not isinstance(payload, dict):
                continue
            boot_rows.append(
                {
                    "tf": tf,
                    "metric": metric,
                    "point": payload.get("point"),
                    "ci_lo": payload.get("lo"),
                    "ci_hi": payload.get("hi"),
                    "n": payload.get("n"),
                }
            )
        slim = {k: v for k, v in result.items() if k not in ("windows_validation", "rs_validation")}
        tf_results.append(slim)

    evidence = classify_evidence(tf_results)
    comparable = all(
        (r["geometry_full"].get("acceptable") or (r.get("validation_windows") or 0) >= 40)
        and "TOO_DENSE" not in (r["geometry_full"].get("pathology_flags") or [])
        and "TOO_SPARSE" not in (r["geometry_full"].get("pathology_flags") or [])
        for r in tf_results
    )

    # Best geometry TF: lowest soft score among acceptable full geometry
    scored = []
    for r in tf_results:
        g = r["geometry_full"]
        scored.append((geometry_soft_score(g), r["tf"], g.get("acceptable")))
    scored.sort()
    best_geom = next((tf for _, tf, ok in scored if ok), scored[0][1] if scored else None)

    # Fixed vs normalized comparison
    fixed_rows = load_fixed_baseline_summary(fixed_baseline_summary) if fixed_baseline_summary else []
    fixed_by_tf = {r["tf"]: r for r in fixed_rows}
    cmp_rows = []
    for r in dina_rows:
        tf = r["tf"]
        f = fixed_by_tf.get(tf, {})
        cmp_rows.append(
            {
                "tf": tf,
                "fixed_r_median": f.get("r_median"),
                "norm_r_median": r["r_median"],
                "fixed_mae_proxy_nearest": f.get("median_nearest_error_ab"),
                "norm_mae_r_eq_1": r["mae_r_eq_1"],
                "fixed_cop_reach": f.get("cop_reach"),
                "norm_cop_reach": r["cop_reach"],
                "fixed_op_reach": f.get("op_reach"),
                "norm_op_reach": r["op_reach"],
                "fixed_xop_reach": f.get("xop_reach"),
                "norm_xop_reach": r["xop_reach"],
                "fixed_edge": f.get("dinapoli_mode_edge_vs_controls"),
                "norm_cop_edge": r["cop_density_edge_vs_controls"],
                "norm_op_edge": r["op_density_edge_vs_controls"],
                "norm_xop_edge": r["xop_density_edge_vs_controls"],
                "fixed_zz_flag": f.get("pathology_flags"),
                "norm_zz_flag": r["pathology_flags"],
                "norm_config": r["normalized_zz_config"],
            }
        )

    write_csv(out_dir / "normalized_zigzag_config.csv", config_rows)
    write_csv(out_dir / "normalized_wave_stats.csv", wave_rows)
    write_csv(out_dir / "normalized_dinapoli_multitf.csv", dina_rows)
    write_csv(out_dir / "normalized_ratio_density.csv", density_rows)
    write_csv(out_dir / "normalized_validation.csv", val_window_rows)
    write_csv(out_dir / "normalized_bootstrap_ci.csv", boot_rows)
    write_csv(out_dir / "fixed_vs_normalized_comparison.csv", cmp_rows)
    # Persist calibration grid summaries (compact)
    write_csv(
        out_dir / "normalized_calibration_global_ranked.csv",
        calib.get("global_candidate_ranked") or [],
    )

    freeze_note = None
    if evidence["dinapoli_specific_ratios_supported"] == "NO" and evidence["leg_persistence_supported"] == "YES":
        freeze_note = "DINAPOLI_SPECIFIC_RATIOS_NOT_SUPPORTED; WAVE_GEOMETRY_SUPPORTED; retain R≈1 / empirical R distribution"

    ready_close = evidence["dinapoli_specific_ratios_supported"] in ("YES", "NO") and evidence[
        "leg_persistence_supported"
    ] in ("YES", "NO")
    ready_context = (
        evidence["dinapoli_specific_ratios_supported"] == "NO"
        and evidence["leg_persistence_supported"] == "YES"
        and evidence["continuous_wave_distribution_supported"] in ("YES", "INCONCLUSIVE")
    )

    report = {
        "wip": "ZIGZAG-NORMALIZATION-AND-DINAPOLI-RETEST-1",
        "fixed_baseline_label": "FIXED_ZZ_BASELINE_V1",
        "fixed_baseline_path": str(fixed_baseline_summary) if fixed_baseline_summary else None,
        "global_normalized_zz_found": calib["global_normalized_zz_found"],
        "normalized_zz_config": (
            calib["best_global"]["label"]
            if calib.get("best_global") and calib["global_normalized_zz_found"]
            else calib.get("group_configs")
        ),
        "normalized_zz_config_detail": calib.get("best_global") if calib["global_normalized_zz_found"] else calib.get("group_configs"),
        "best_vol_global_reference": calib.get("best_vol_global"),
        "timeframes_tested": list(timeframes),
        "geometry_comparable_across_tf": comparable,
        "decision_matrix": dina_rows,
        "results_by_tf": tf_results,
        "calibration": {
            "global_found": calib["global_normalized_zz_found"],
            "best_global": calib.get("best_global"),
            "top_global": calib.get("global_candidate_ranked"),
            "groups": calib.get("group_configs"),
            "best_vol": calib.get("best_vol_global"),
        },
        "r_median_by_tf": {r["tf"]: r["r_median"] for r in dina_rows},
        "r1_mae_by_tf": {r["tf"]: r["mae_r_eq_1"] for r in dina_rows},
        "cop_reach_by_tf": {r["tf"]: r["cop_reach"] for r in dina_rows},
        "op_reach_by_tf": {r["tf"]: r["op_reach"] for r in dina_rows},
        "xop_reach_by_tf": {r["tf"]: r["xop_reach"] for r in dina_rows},
        "p_op_given_cop_by_tf": {r["tf"]: r["p_op_given_cop"] for r in dina_rows},
        "p_xop_given_op_by_tf": {r["tf"]: r["p_xop_given_op"] for r in dina_rows},
        **evidence,
        "best_geometry_tf": best_geom,
        "freeze_note": freeze_note,
        "ready_to_close_geometry_phase": "YES" if ready_close else "NO",
        "ready_for_market_context_phase": "YES" if ready_context else "NO",
        "depth": DEPTH,
        "backstep": BACKSTEP,
    }
    (out_dir / "summary.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report
