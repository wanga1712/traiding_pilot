"""Multi-timeframe DiNapoli COP/OP/XOP sweep with fixed ZigZag params."""
from __future__ import annotations

import csv
import json
import math
import random
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median, pstdev
from typing import Any

from crypto_trading_bot.research_v2.dinapoli.validate_4h import (
    FIB_COP,
    FIB_OP,
    FIB_XOP,
    ZIGZAG_DEFAULT,
    AbcWindow,
    build_abc_windows,
    chronological_split,
    summarize_windows,
    write_windows_csv,
)
from crypto_trading_bot.research_v2.resampling import TIMEFRAMES, UI_TIMEFRAMES
from crypto_trading_bot.research_v2.zigzag.classic import classic_percent_zigzag

CONTROL_RATIOS = (0.50, 0.75, 1.25, 1.50, 2.00)
ALL_PROBE_RATIOS = (0.50, 0.618, 0.75, 1.00, 1.25, 1.50, 1.618, 2.00)
FIB_RATIOS = (0.618, 1.000, 1.618)
BOOTSTRAP_N = 1000
BOOTSTRAP_SEED = 1712
NEIGHBORHOOD = 0.10  # equal-width ±0.10 around each probe ratio


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


def mode_density(rs: list[float], center: float, half_width: float = NEIGHBORHOOD) -> float:
    if not rs:
        return 0.0
    hits = sum(1 for r in rs if abs(r - center) <= half_width)
    return hits / len(rs)


def ratio_within(rs: list[float], center: float, tol: float) -> float:
    if not rs:
        return 0.0
    return sum(1 for r in rs if abs(r - center) <= tol) / len(rs)


def bootstrap_metric(
    values: list[float],
    *,
    fn,
    n: int = BOOTSTRAP_N,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, float | None]:
    if not values:
        return {"point": None, "lo": None, "hi": None, "n": 0}
    rng = random.Random(seed)
    point = fn(values)
    samples = []
    m = len(values)
    for _ in range(n):
        draw = [values[rng.randrange(m)] for _ in range(m)]
        samples.append(fn(draw))
    samples.sort()
    lo = samples[int(0.025 * (n - 1))]
    hi = samples[int(0.975 * (n - 1))]
    return {"point": point, "lo": lo, "hi": hi, "n": m}


def bootstrap_rate(flags: list[bool], *, seed: int = BOOTSTRAP_SEED) -> dict[str, float | None]:
    vals = [1.0 if f else 0.0 for f in flags]
    return bootstrap_metric(vals, fn=mean, seed=seed)


def bootstrap_conditional(flags_a: list[bool], flags_b: list[bool], *, seed: int = BOOTSTRAP_SEED) -> dict[str, float | None]:
    """P(B|A) with bootstrap over windows where A is true in each resample via paired indices."""
    if not flags_a:
        return {"point": None, "lo": None, "hi": None, "n": 0}
    paired = list(zip(flags_a, flags_b))
    a_true = [b for a, b in paired if a]
    point = (sum(1 for b in a_true if b) / len(a_true)) if a_true else None
    rng = random.Random(seed)
    samples = []
    m = len(paired)
    for _ in range(BOOTSTRAP_N):
        draw = [paired[rng.randrange(m)] for _ in range(m)]
        subset = [b for a, b in draw if a]
        if not subset:
            continue
        samples.append(sum(1 for b in subset if b) / len(subset))
    if not samples:
        return {"point": point, "lo": None, "hi": None, "n": len(a_true)}
    samples.sort()
    lo = samples[int(0.025 * (len(samples) - 1))]
    hi = samples[int(0.975 * (len(samples) - 1))]
    return {"point": point, "lo": lo, "hi": hi, "n": len(a_true)}


def zigzag_diagnostics(pivots, candles: list[dict], tf: str) -> dict[str, Any]:
    minutes = TIMEFRAMES[tf]
    if len(pivots) < 2 or not candles:
        return {
            "pivots": len(pivots),
            "pivots_per_year": None,
            "median_bars_per_leg": None,
            "median_hours_per_leg": None,
            "median_move_pct": None,
            "span_years": None,
            "zigzag_not_comparable": True,
            "pathology_flags": ["TOO_FEW_PIVOTS"],
        }
    t0 = _parse_ts(candles[0]["open_time_utc"])
    t1 = _parse_ts(candles[-1]["open_time_utc"])
    span_years = max((t1 - t0).total_seconds() / (365.25 * 86400.0), 1e-9)
    pivots_per_year = len(pivots) / span_years
    bars = [pivots[i + 1].index - pivots[i].index for i in range(len(pivots) - 1)]
    hours = [b * minutes / 60.0 for b in bars]
    moves = []
    for i in range(len(pivots) - 1):
        a, b = float(pivots[i].price), float(pivots[i + 1].price)
        if a != 0:
            moves.append(abs(b - a) / abs(a) * 100.0)
    med_bars = median(bars) if bars else None
    med_hours = median(hours) if hours else None
    med_move = median(moves) if moves else None

    flags = []
    # Pathologies relative to 4H reference behavior (~1.5% legs, multi-bar legs).
    if pivots_per_year > 800:
        flags.append("TOO_DENSE")
    if pivots_per_year < 20:
        flags.append("TOO_SPARSE")
    if med_bars is not None and med_bars < 2:
        flags.append("MEDIAN_LEG_LT_2_BARS")
    if med_move is not None and med_move < 0.4:
        flags.append("MEDIAN_MOVE_TOO_SMALL")
    if med_move is not None and med_move > 12:
        flags.append("MEDIAN_MOVE_TOO_LARGE")
    if len(pivots) < 40:
        flags.append("LOW_PIVOT_COUNT")

    return {
        "pivots": len(pivots),
        "pivots_per_year": pivots_per_year,
        "median_bars_per_leg": med_bars,
        "median_hours_per_leg": med_hours,
        "median_move_pct": med_move,
        "span_years": span_years,
        "zigzag_not_comparable": bool(flags),
        "pathology_flags": flags,
    }


def analyze_tf_windows(windows: list[AbcWindow], *, label: str) -> dict[str, Any]:
    base = summarize_windows(windows, label=label)
    rs = [w.r for w in windows]
    densities = {f"{c:g}": mode_density(rs, c) for c in ALL_PROBE_RATIOS}
    fib_d = {name: mode_density(rs, c) for name, c in (("COP", FIB_COP), ("OP", FIB_OP), ("XOP", FIB_XOP))}
    control_d = {f"{c:g}": mode_density(rs, c) for c in CONTROL_RATIOS}
    best_control = max(control_d, key=control_d.get) if control_d else None
    best_control_d = control_d.get(best_control, 0.0) if best_control else 0.0
    avg_fib = mean(fib_d.values()) if fib_d else 0.0
    avg_ctrl = mean(control_d.values()) if control_d else 0.0
    edge = avg_fib - avg_ctrl

    base.update(
        {
            "r_iqr": (base.get("r_p75") or 0) - (base.get("r_p25") or 0),
            "mode_density": densities,
            "fib_mode_density": fib_d,
            "control_mode_density": control_d,
            "best_control_ratio": best_control,
            "best_control_density": best_control_d,
            "avg_fib_density": avg_fib,
            "avg_control_density": avg_ctrl,
            "dinapoli_mode_edge_vs_controls": edge,
            "ratio_within_0_05": {
                "COP": ratio_within(rs, FIB_COP, 0.05),
                "OP": ratio_within(rs, FIB_OP, 0.05),
                "XOP": ratio_within(rs, FIB_XOP, 0.05),
            },
            "ratio_target_counts": {
                "pm_0_05": {
                    "COP": sum(1 for r in rs if abs(r - FIB_COP) <= 0.05),
                    "OP": sum(1 for r in rs if abs(r - FIB_OP) <= 0.05),
                    "XOP": sum(1 for r in rs if abs(r - FIB_XOP) <= 0.05),
                },
                "pm_0_10": {
                    "COP": sum(1 for r in rs if abs(r - FIB_COP) <= 0.10),
                    "OP": sum(1 for r in rs if abs(r - FIB_OP) <= 0.10),
                    "XOP": sum(1 for r in rs if abs(r - FIB_XOP) <= 0.10),
                },
                "pm_0_20": {
                    "COP": sum(1 for r in rs if abs(r - FIB_COP) <= 0.20),
                    "OP": sum(1 for r in rs if abs(r - FIB_OP) <= 0.20),
                    "XOP": sum(1 for r in rs if abs(r - FIB_XOP) <= 0.20),
                },
            },
            "median_nearest_error_ab": median([w.nearest_error_ab for w in windows]) if windows else None,
            "endpoint_proximity": {
                "COP": base.get("endpoint_within_5pct", {}).get("COP"),
                "OP": base.get("endpoint_within_5pct", {}).get("OP"),
                "XOP": base.get("endpoint_within_5pct", {}).get("XOP"),
            },
        }
    )
    return base


def bootstrap_validation(windows: list[AbcWindow]) -> dict[str, Any]:
    rs = [w.r for w in windows]
    return {
        "n": len(windows),
        "r_median": bootstrap_metric(rs, fn=median, seed=BOOTSTRAP_SEED),
        "cop_reach": bootstrap_rate([w.cop_reached for w in windows], seed=BOOTSTRAP_SEED + 1),
        "op_reach": bootstrap_rate([w.op_reached for w in windows], seed=BOOTSTRAP_SEED + 2),
        "xop_reach": bootstrap_rate([w.xop_reached for w in windows], seed=BOOTSTRAP_SEED + 3),
        "p_op_given_cop": bootstrap_conditional(
            [w.cop_reached for w in windows],
            [w.op_reached for w in windows],
            seed=BOOTSTRAP_SEED + 4,
        ),
        "p_xop_given_op": bootstrap_conditional(
            [w.op_reached for w in windows],
            [w.xop_reached for w in windows],
            seed=BOOTSTRAP_SEED + 5,
        ),
    }


def evaluate_timeframe(
    candles: list[dict],
    tf: str,
    *,
    zigzag_cfg: dict | None = None,
) -> dict[str, Any]:
    cfg = {**ZIGZAG_DEFAULT, **(zigzag_cfg or {})}
    pivots = classic_percent_zigzag(
        candles,
        deviation_percent=float(cfg["deviation"]),
        depth=int(cfg["depth"]),
        backstep=int(cfg["backstep"]),
    )
    zz_diag = zigzag_diagnostics(pivots, candles, tf)
    raw = build_abc_windows(pivots, candles, tf=tf, discovery_median_r=None)
    discovery, validation = chronological_split(raw, 0.70)
    disc_median_r = median([w.r for w in discovery]) if discovery else 1.0
    windows = build_abc_windows(pivots, candles, tf=tf, discovery_median_r=disc_median_r)
    discovery, validation = chronological_split(windows, 0.70)
    for w in validation:
        pred = w.c_price + w.ab * disc_median_r
        w.baseline_median_error_ab = abs(w.d_price - pred) / abs(w.ab) if w.ab else None

    disc = analyze_tf_windows(discovery, label="DISCOVERY")
    val = analyze_tf_windows(validation, label="VALIDATION")
    full = analyze_tf_windows(windows, label="FULL")
    boot = bootstrap_validation(validation)

    # Stability: discovery vs validation consistency on key metrics
    stability = {
        "r_median_abs_delta": abs((disc.get("r_median") or 0) - (val.get("r_median") or 0)),
        "cop_reach_abs_delta": abs((disc.get("cop_reach_rate") or 0) - (val.get("cop_reach_rate") or 0)),
        "op_reach_abs_delta": abs((disc.get("op_reach_rate") or 0) - (val.get("op_reach_rate") or 0)),
        "edge_abs_delta": abs(
            (disc.get("dinapoli_mode_edge_vs_controls") or 0) - (val.get("dinapoli_mode_edge_vs_controls") or 0)
        ),
    }

    return {
        "tf": tf,
        "zigzag_config": cfg,
        "candle_count": len(candles),
        "zigzag_diagnostics": zz_diag,
        "total_pivots": len(pivots),
        "total_windows": len(windows),
        "discovery_windows": len(discovery),
        "validation_windows": len(validation),
        "discovery_median_r": disc_median_r,
        "discovery": disc,
        "validation": val,
        "full": full,
        "bootstrap_validation": boot,
        "stability": stability,
        "windows": windows,
        "discovery_set": discovery,
        "validation_set": validation,
    }


def _rank(rows: list[dict], key_fn, *, higher_better: bool = True, min_n: int = 30) -> list[str]:
    eligible = [r for r in rows if (r.get("validation_windows") or 0) >= min_n and not r["zigzag_diagnostics"]["zigzag_not_comparable"]]
    if not eligible:
        eligible = [r for r in rows if (r.get("validation_windows") or 0) >= 10]
    scored = []
    for r in eligible:
        try:
            scored.append((key_fn(r), r["tf"]))
        except Exception:
            continue
    scored.sort(key=lambda x: x[0], reverse=higher_better)
    return [tf for _, tf in scored]


def build_rankings(tf_results: list[dict]) -> dict[str, Any]:
    clustering = _rank(
        tf_results,
        lambda r: r["validation"].get("dinapoli_mode_edge_vs_controls") or -999,
        higher_better=True,
    )
    progression = _rank(
        tf_results,
        lambda r: (
            (r["validation"].get("p_op_given_cop") or 0)
            + (r["validation"].get("p_xop_given_op") or 0)
            + (r["validation"].get("cop_reach_rate") or 0)
        )
        / 3.0,
        higher_better=True,
    )
    target_error = _rank(
        tf_results,
        lambda r: -(r["validation"].get("median_nearest_error_ab") or 999),
        higher_better=True,
    )
    stability = _rank(
        tf_results,
        lambda r: -(
            (r["stability"].get("r_median_abs_delta") or 0)
            + (r["stability"].get("cop_reach_abs_delta") or 0)
            + (r["stability"].get("op_reach_abs_delta") or 0)
        ),
        higher_better=True,
    )
    reliability = _rank(
        tf_results,
        lambda r: r.get("validation_windows") or 0,
        higher_better=True,
        min_n=1,
    )
    return {
        "target_clustering": clustering,
        "path_progression": progression,
        "target_error": target_error,
        "stability": stability,
        "statistical_reliability": reliability,
    }


def fib_special_verdict(tf_results: list[dict]) -> dict[str, str]:
    """Across TFs, are COP/OP/XOP denser than nearby controls?"""
    edges = {"COP": [], "OP": [], "XOP": []}
    for r in tf_results:
        if r["zigzag_diagnostics"]["zigzag_not_comparable"]:
            continue
        val = r["validation"]
        if (r.get("validation_windows") or 0) < 30:
            continue
        fib = val.get("fib_mode_density") or {}
        ctrl = val.get("control_mode_density") or {}
        # compare each fib to nearest controls
        edges["COP"].append(fib.get("COP", 0) - max(ctrl.get("0.5", 0), ctrl.get("0.75", 0)))
        edges["OP"].append(fib.get("OP", 0) - max(ctrl.get("0.75", 0), ctrl.get("1.25", 0)))
        edges["XOP"].append(fib.get("XOP", 0) - max(ctrl.get("1.5", 0), ctrl.get("2", 0)))

    def verdict(vals: list[float]) -> str:
        if len(vals) < 3:
            return "INCONCLUSIVE"
        pos = sum(1 for v in vals if v > 0.01)
        neg = sum(1 for v in vals if v < -0.01)
        if pos >= max(3, int(0.6 * len(vals))):
            return "YES"
        if neg >= max(3, int(0.6 * len(vals))):
            return "NO"
        if pos > neg:
            return "INCONCLUSIVE"
        return "NO"

    return {k: verdict(v) for k, v in edges.items()}


def control_ratio_verdict(tf_results: list[dict]) -> str:
    wins = 0
    losses = 0
    ties = 0
    for r in tf_results:
        if r["zigzag_diagnostics"]["zigzag_not_comparable"] or (r.get("validation_windows") or 0) < 30:
            continue
        edge = r["validation"].get("dinapoli_mode_edge_vs_controls")
        if edge is None:
            continue
        if edge > 0.01:
            wins += 1
        elif edge < -0.01:
            losses += 1
        else:
            ties += 1
    total = wins + losses + ties
    if total < 3:
        return "INCONCLUSIVE"
    if wins >= max(3, int(0.6 * total)):
        return "YES"
    if losses >= max(3, int(0.6 * total)):
        return "NO"
    if wins and losses:
        return "MIXED"
    return "INCONCLUSIVE"


def write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = fieldnames or list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _ascii_bar(value: float, max_v: float, width: int = 30) -> str:
    if max_v <= 0:
        return ""
    n = int(width * value / max_v)
    return "#" * max(0, n)


def write_plots(out_dir: Path, tf_results: list[dict]) -> None:
    # Reach by TF
    lines = ["COP/OP/XOP reach by TF (validation)", ""]
    for r in tf_results:
        v = r["validation"]
        lines.append(
            f"{r['tf']:4s}  COP={v.get('cop_reach_rate', 0):.3f}  OP={v.get('op_reach_rate', 0):.3f}  "
            f"XOP={v.get('xop_reach_rate', 0):.3f}  N={r['validation_windows']}"
        )
    (out_dir / "plot_reach_by_tf.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    lines = ["Conditional progression by TF (validation)", ""]
    for r in tf_results:
        v = r["validation"]
        lines.append(
            f"{r['tf']:4s}  P(OP|COP)={v.get('p_op_given_cop')}  P(XOP|OP)={v.get('p_xop_given_op')}  "
            f"P(XOP|COP)={v.get('p_xop_given_cop')}"
        )
    (out_dir / "plot_conditional_by_tf.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    lines = ["Dinapoli vs control mode density (validation, ±0.10)", ""]
    for r in tf_results:
        v = r["validation"]
        fib = v.get("fib_mode_density") or {}
        dens = v.get("mode_density") or {}
        edge = v.get("dinapoli_mode_edge_vs_controls")
        lines.append(
            f"{r['tf']:4s}  COP={fib.get('COP', 0):.3f} OP={fib.get('OP', 0):.3f} XOP={fib.get('XOP', 0):.3f}  "
            f"edge_vs_ctrl={edge}  best_ctrl={v.get('best_control_ratio')}@{v.get('best_control_density')}"
        )
        # density overlay line for all probe ratios
        overlay = " ".join(f"{k}={dens.get(k, 0):.3f}" for k in ("0.5", "0.618", "0.75", "1", "1.25", "1.5", "1.618", "2"))
        lines.append(f"       density: {overlay}")
    (out_dir / "plot_density_vs_controls.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Compact R median bars
    meds = [(r["tf"], r["validation"].get("r_median") or 0) for r in tf_results]
    max_abs = max((abs(m) for _, m in meds), default=1) or 1
    lines = ["R_MEDIAN by TF (validation)", ""]
    for tf, m in meds:
        lines.append(f"{tf:4s} {m:7.3f} {_ascii_bar(abs(m), max_abs)}")
    (out_dir / "plot_r_median_by_tf.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # R distribution percentiles by TF
    lines = ["R distribution by TF (validation percentiles)", ""]
    lines.append(f"{'TF':4s} {'N':>6} {'P10':>7} {'P25':>7} {'P50':>7} {'P75':>7} {'P90':>7} {'MEAN':>7} {'STD':>7}")
    for r in tf_results:
        v = r["validation"]
        lines.append(
            f"{r['tf']:4s} {r['validation_windows']:6d} "
            f"{(v.get('r_p10') or 0):7.3f} {(v.get('r_p25') or 0):7.3f} {(v.get('r_p50') or 0):7.3f} "
            f"{(v.get('r_p75') or 0):7.3f} {(v.get('r_p90') or 0):7.3f} "
            f"{(v.get('r_mean') or 0):7.3f} {(v.get('r_std') or 0):7.3f}"
        )
    (out_dir / "plot_r_distribution_by_tf.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Try matplotlib PNGs if available
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        tfs = [r["tf"] for r in tf_results]
        cop = [r["validation"].get("cop_reach_rate") or 0 for r in tf_results]
        op = [r["validation"].get("op_reach_rate") or 0 for r in tf_results]
        xop = [r["validation"].get("xop_reach_rate") or 0 for r in tf_results]
        x = range(len(tfs))
        fig, ax = plt.subplots(figsize=(12, 5))
        ax.plot(list(x), cop, "o-", label="COP")
        ax.plot(list(x), op, "s-", label="OP")
        ax.plot(list(x), xop, "^-", label="XOP")
        ax.set_xticks(list(x))
        ax.set_xticklabels(tfs)
        ax.set_ylim(0, 1)
        ax.set_ylabel("reach rate")
        ax.set_title("COP/OP/XOP reach by TF (validation)")
        ax.legend()
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(out_dir / "plot_reach_by_tf.png", dpi=120)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(12, 5))
        for r in tf_results:
            dens = r["validation"].get("mode_density") or {}
            xs = [0.50, 0.618, 0.75, 1.00, 1.25, 1.50, 1.618, 2.00]
            ys = [dens.get(f"{c:g}", 0) for c in xs]
            ax.plot(xs, ys, marker="o", label=r["tf"])
        ax.axvline(0.618, color="gray", ls="--", alpha=0.5)
        ax.axvline(1.0, color="gray", ls="--", alpha=0.5)
        ax.axvline(1.618, color="gray", ls="--", alpha=0.5)
        ax.set_xlabel("R probe")
        ax.set_ylabel("density ±0.10")
        ax.set_title("R density overlay by TF (validation)")
        ax.legend(ncol=2, fontsize=8)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(out_dir / "plot_r_density_overlay_by_tf.png", dpi=120)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(12, 5))
        p_op = [r["validation"].get("p_op_given_cop") or 0 for r in tf_results]
        p_xop = [r["validation"].get("p_xop_given_op") or 0 for r in tf_results]
        ax.plot(list(x), p_op, "o-", label="P(OP|COP)")
        ax.plot(list(x), p_xop, "s-", label="P(XOP|OP)")
        ax.set_xticks(list(x))
        ax.set_xticklabels(tfs)
        ax.set_ylim(0, 1)
        ax.set_title("Conditional progression by TF (validation)")
        ax.legend()
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(out_dir / "plot_conditional_by_tf.png", dpi=120)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(12, 5))
        edge = [r["validation"].get("dinapoli_mode_edge_vs_controls") or 0 for r in tf_results]
        colors = ["#2ecc71" if e > 0 else "#e74c3c" for e in edge]
        ax.bar(list(x), edge, color=colors)
        ax.axhline(0, color="black", lw=0.8)
        ax.set_xticks(list(x))
        ax.set_xticklabels(tfs)
        ax.set_title("Dinapoli mode edge vs control ratios by TF")
        ax.set_ylabel("avg fib density − avg control density")
        ax.grid(True, axis="y", alpha=0.3)
        fig.tight_layout()
        fig.savefig(out_dir / "plot_dinapoli_vs_controls_by_tf.png", dpi=120)
        plt.close(fig)
    except Exception as exc:
        (out_dir / "plot_matplotlib_error.txt").write_text(str(exc), encoding="utf-8")


def run_multitf_sweep(
    candles_by_tf: dict[str, list[dict]],
    *,
    out_dir: Path,
    zigzag_cfg: dict | None = None,
    timeframes: tuple[str, ...] = UI_TIMEFRAMES,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = {**ZIGZAG_DEFAULT, **(zigzag_cfg or {})}
    tf_results: list[dict] = []
    all_windows: list[dict] = []
    density_rows: list[dict] = []
    control_rows: list[dict] = []
    bootstrap_rows: list[dict] = []
    summary_rows: list[dict] = []

    for tf in timeframes:
        candles = candles_by_tf.get(tf) or []
        print(f"[multitf] evaluating {tf} candles={len(candles)}", flush=True)
        result = evaluate_timeframe(candles, tf, zigzag_cfg=cfg)
        # Strip heavy objects for JSON summary storage
        slim = {k: v for k, v in result.items() if k not in ("windows", "discovery_set", "validation_set")}
        tf_results.append(slim)

        for w in result["windows"]:
            row = asdict(w)
            all_windows.append(row)
        for w in result["validation_set"]:
            pass  # validation csv built later from windows split

        val = result["validation"]
        dens = val.get("mode_density") or {}
        for ratio, d in dens.items():
            density_rows.append({"tf": tf, "ratio": ratio, "density_pm_0_10": d, "n": result["validation_windows"]})
        for ratio, d in (val.get("control_mode_density") or {}).items():
            control_rows.append(
                {
                    "tf": tf,
                    "ratio_type": "CONTROL",
                    "ratio": ratio,
                    "density": d,
                    "n": result["validation_windows"],
                }
            )
        for name, d in (val.get("fib_mode_density") or {}).items():
            control_rows.append(
                {
                    "tf": tf,
                    "ratio_type": "DINAPOLI",
                    "ratio": {"COP": "0.618", "OP": "1.0", "XOP": "1.618"}[name],
                    "density": d,
                    "n": result["validation_windows"],
                    "name": name,
                }
            )

        boot = result["bootstrap_validation"]
        for metric, payload in boot.items():
            if metric == "n":
                continue
            bootstrap_rows.append(
                {
                    "tf": tf,
                    "metric": metric,
                    "point": payload.get("point"),
                    "ci_lo": payload.get("lo"),
                    "ci_hi": payload.get("hi"),
                    "n": payload.get("n"),
                }
            )

        zz = result["zigzag_diagnostics"]
        summary_rows.append(
            {
                "tf": tf,
                "pivots": result["total_pivots"],
                "windows": result["total_windows"],
                "validation_windows": result["validation_windows"],
                "r_median": val.get("r_median"),
                "r_iqr": val.get("r_iqr"),
                "r_mean": val.get("r_mean"),
                "r_std": val.get("r_std"),
                "cop_reach": val.get("cop_reach_rate"),
                "op_reach": val.get("op_reach_rate"),
                "xop_reach": val.get("xop_reach_rate"),
                "p_op_given_cop": val.get("p_op_given_cop"),
                "p_xop_given_op": val.get("p_xop_given_op"),
                "p_xop_given_cop": val.get("p_xop_given_cop"),
                "cop_mode_density": (val.get("fib_mode_density") or {}).get("COP"),
                "op_mode_density": (val.get("fib_mode_density") or {}).get("OP"),
                "xop_mode_density": (val.get("fib_mode_density") or {}).get("XOP"),
                "best_control_ratio": val.get("best_control_ratio"),
                "best_control_density": val.get("best_control_density"),
                "dinapoli_mode_edge_vs_controls": val.get("dinapoli_mode_edge_vs_controls"),
                "median_nearest_error_ab": val.get("median_nearest_error_ab"),
                "median_target_error_cop_ab": (val.get("median_error_ab") or {}).get("COP"),
                "median_target_error_op_ab": (val.get("median_error_ab") or {}).get("OP"),
                "median_target_error_xop_ab": (val.get("median_error_ab") or {}).get("XOP"),
                "pivots_per_year": zz.get("pivots_per_year"),
                "median_bars_per_leg": zz.get("median_bars_per_leg"),
                "median_hours_per_leg": zz.get("median_hours_per_leg"),
                "median_move_pct": zz.get("median_move_pct"),
                "zigzag_not_comparable": zz.get("zigzag_not_comparable"),
                "pathology_flags": ";".join(zz.get("pathology_flags") or []),
            }
        )

    rankings = build_rankings(tf_results)
    special = fib_special_verdict(tf_results)
    beat_controls = control_ratio_verdict(tf_results)
    needing_norm = [
        r["tf"]
        for r in tf_results
        if r["zigzag_diagnostics"].get("zigzag_not_comparable")
    ]

    # Best overall research TF: prefer clustering+reliability among non-pathological
    overall = None
    for tf in rankings["target_clustering"]:
        if tf not in needing_norm:
            overall = tf
            break
    if overall is None and rankings["statistical_reliability"]:
        overall = rankings["statistical_reliability"][0]

    # Persist artifacts
    write_csv(out_dir / "dinapoli_multitf_windows.csv", all_windows)
    write_csv(out_dir / "dinapoli_multitf_summary.csv", summary_rows)
    val_windows = [w for w in all_windows if w.get("split") == "VALIDATION"]
    write_csv(out_dir / "dinapoli_multitf_validation.csv", val_windows)
    write_csv(out_dir / "dinapoli_ratio_density_by_tf.csv", density_rows)
    write_csv(out_dir / "dinapoli_control_ratio_comparison.csv", control_rows)
    write_csv(out_dir / "dinapoli_bootstrap_ci.csv", bootstrap_rows)
    write_plots(out_dir, tf_results)

    report = {
        "wip": "DINAPOLI-COP-OP-XOP-MULTITIMEFRAME-SWEEP-1",
        "timeframes_tested": list(timeframes),
        "zigzag_config_fixed": cfg,
        "neighborhood_half_width": NEIGHBORHOOD,
        "control_ratios": list(CONTROL_RATIOS),
        "bootstrap_n": BOOTSTRAP_N,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "results_by_tf": tf_results,
        "summary_table": summary_rows,
        "rankings": rankings,
        "best_tf_target_clustering": rankings["target_clustering"][:1] or [None],
        "best_tf_path_progression": rankings["path_progression"][:1] or [None],
        "best_tf_target_error": rankings["target_error"][:1] or [None],
        "most_stable_tf": rankings["stability"][:1] or [None],
        "most_reliable_tf": rankings["statistical_reliability"][:1] or [None],
        "cop_mode_special": special["COP"],
        "op_mode_special": special["OP"],
        "xop_mode_special": special["XOP"],
        "dinapoli_ratios_beat_control_ratios": beat_controls,
        "tf_requiring_normalized_zigzag": needing_norm,
        "best_overall_research_tf": overall,
        "ready_for_zigzag_normalization_study": "YES" if needing_norm else "NO",
        "ready_for_volume_accumulation_study": (
            "YES"
            if (
                overall is not None
                and beat_controls == "YES"
                and any(v == "YES" for v in special.values())
            )
            else "NO"
        ),
    }
    (out_dir / "summary.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report
