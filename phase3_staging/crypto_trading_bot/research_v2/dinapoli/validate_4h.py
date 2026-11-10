"""DiNapoli COP/OP/XOP validation on classic ZigZag ABC→D windows (4H)."""
from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean, median, pstdev
from typing import Any, Iterable

from crypto_trading_bot.research_v2.zigzag.classic import ZigZagPivot, classic_percent_zigzag

FIB_COP = 0.618
FIB_OP = 1.000
FIB_XOP = 1.618
ZIGZAG_DEFAULT = {"deviation": 1.5, "depth": 3, "backstep": 0}


def _parse_ts(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    text = str(value).replace("Z", "+00:00")
    if text.endswith("+00"):
        text += ":00"
    return datetime.fromisoformat(text)


def _pct(numer: float, denom: float) -> float:
    if denom == 0:
        return float("inf")
    return abs(numer / denom) * 100.0


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


@dataclass
class AbcWindow:
    window_index: int
    tf: str
    a_index: int
    a_time: str
    a_price: float
    a_kind: str
    b_index: int
    b_time: str
    b_price: float
    b_kind: str
    c_index: int
    c_time: str
    c_price: float
    c_kind: str
    d_index: int
    d_time: str
    d_price: float
    d_kind: str
    ab: float
    r: float
    cop: float
    op: float
    xop: float
    cop_error_pct: float
    op_error_pct: float
    xop_error_pct: float
    cop_error_ab: float
    op_error_ab: float
    xop_error_ab: float
    nearest_target: str
    nearest_error_pct: float
    nearest_error_ab: float
    direction_ab: str
    direction_cd: str
    direction_sanity: bool
    cop_reached: bool
    op_reached: bool
    xop_reached: bool
    cop_reached_at: str | None
    op_reached_at: str | None
    xop_reached_at: str | None
    cop_overshoot_ab: float | None
    op_overshoot_ab: float | None
    xop_overshoot_ab: float | None
    baseline_r1_error_ab: float
    baseline_median_error_ab: float | None
    baseline_prev_same_dir_error_ab: float | None
    split: str = ""


def build_abc_windows(
    pivots: list[ZigZagPivot],
    candles: list[dict],
    *,
    tf: str = "4H",
    discovery_median_r: float | None = None,
) -> list[AbcWindow]:
    """Build rolling A/B/C → D windows. Targets use only A/B/C (anti-leakage)."""
    if len(pivots) < 4:
        return []
    by_index = {i: c for i, c in enumerate(candles)}
    windows: list[AbcWindow] = []
    for i in range(len(pivots) - 3):
        a, b, c, d = pivots[i], pivots[i + 1], pivots[i + 2], pivots[i + 3]
        ab = float(b.price) - float(a.price)
        if ab == 0:
            continue
        cop = float(c.price) + ab * FIB_COP
        op = float(c.price) + ab * FIB_OP
        xop = float(c.price) + ab * FIB_XOP
        r = (float(d.price) - float(c.price)) / ab
        dir_ab = "UP" if ab > 0 else "DOWN"
        dir_cd = "UP" if (float(d.price) - float(c.price)) > 0 else "DOWN"
        sanity = dir_ab == dir_cd

        errs = {
            "COP": (abs(float(d.price) - cop), _pct(float(d.price) - cop, float(d.price)), abs(r - FIB_COP)),
            "OP": (abs(float(d.price) - op), _pct(float(d.price) - op, float(d.price)), abs(r - FIB_OP)),
            "XOP": (abs(float(d.price) - xop), _pct(float(d.price) - xop, float(d.price)), abs(r - FIB_XOP)),
        }
        nearest = min(errs, key=lambda k: errs[k][0])
        # Prefer nearest by AB-normalized distance to classic ratios when price % ties oddly.
        nearest_ab = min(("COP", "OP", "XOP"), key=lambda k: errs[k][2])
        nearest = nearest_ab

        reach = _path_reach(
            candles,
            c_index=c.index,
            d_index=d.index,
            direction=dir_ab,
            cop=cop,
            op=op,
            xop=xop,
            ab=ab,
        )

        # Baselines (errors in AB units vs actual D).
        pred_r1 = float(c.price) + ab * 1.0
        baseline_r1_err = abs(float(d.price) - pred_r1) / abs(ab)
        baseline_med_err = None
        if discovery_median_r is not None:
            pred_med = float(c.price) + ab * discovery_median_r
            baseline_med_err = abs(float(d.price) - pred_med) / abs(ab)
        baseline_prev = None
        if i >= 2:
            # Previous same-direction leg: A_{-2}→A_{-1} wait — same-direction as AB is A→B,
            # previous same-direction pivot leg is pivots[i-2]→pivots[i-1] which has same orientation as A→B.
            p0, p1 = pivots[i - 2], pivots[i - 1]
            prev_leg = float(p1.price) - float(p0.price)
            if (prev_leg > 0) == (ab > 0) and prev_leg != 0:
                pred_prev = float(c.price) + prev_leg
                baseline_prev = abs(float(d.price) - pred_prev) / abs(ab)

        windows.append(
            AbcWindow(
                window_index=i,
                tf=tf,
                a_index=a.index,
                a_time=a.timestamp,
                a_price=float(a.price),
                a_kind=a.kind,
                b_index=b.index,
                b_time=b.timestamp,
                b_price=float(b.price),
                b_kind=b.kind,
                c_index=c.index,
                c_time=c.timestamp,
                c_price=float(c.price),
                c_kind=c.kind,
                d_index=d.index,
                d_time=d.timestamp,
                d_price=float(d.price),
                d_kind=d.kind,
                ab=ab,
                r=r,
                cop=cop,
                op=op,
                xop=xop,
                cop_error_pct=errs["COP"][1],
                op_error_pct=errs["OP"][1],
                xop_error_pct=errs["XOP"][1],
                cop_error_ab=errs["COP"][2],
                op_error_ab=errs["OP"][2],
                xop_error_ab=errs["XOP"][2],
                nearest_target=nearest,
                nearest_error_pct=errs[nearest][1],
                nearest_error_ab=errs[nearest][2],
                direction_ab=dir_ab,
                direction_cd=dir_cd,
                direction_sanity=sanity,
                cop_reached=reach["COP"]["reached"],
                op_reached=reach["OP"]["reached"],
                xop_reached=reach["XOP"]["reached"],
                cop_reached_at=reach["COP"]["at"],
                op_reached_at=reach["OP"]["at"],
                xop_reached_at=reach["XOP"]["at"],
                cop_overshoot_ab=reach["COP"]["overshoot_ab"],
                op_overshoot_ab=reach["OP"]["overshoot_ab"],
                xop_overshoot_ab=reach["XOP"]["overshoot_ab"],
                baseline_r1_error_ab=baseline_r1_err,
                baseline_median_error_ab=baseline_med_err,
                baseline_prev_same_dir_error_ab=baseline_prev,
            )
        )
    return windows


def _path_reach(
    candles: list[dict],
    *,
    c_index: int,
    d_index: int,
    direction: str,
    cop: float,
    op: float,
    xop: float,
    ab: float,
) -> dict[str, dict[str, Any]]:
    """Scan bars after C through D for first touch of each objective in expansion direction."""
    start = min(c_index + 1, len(candles) - 1)
    end = min(max(d_index, start), len(candles) - 1)
    levels = {"COP": cop, "OP": op, "XOP": xop}
    out = {
        name: {"reached": False, "at": None, "overshoot_ab": None, "first_touch_price": None}
        for name in levels
    }
    abs_ab = abs(ab) if ab != 0 else 1.0
    extreme_after: dict[str, float] = {}

    for i in range(start, end + 1):
        bar = candles[i]
        hi = float(bar["high"])
        lo = float(bar["low"])
        ts = str(bar["open_time_utc"])
        for name, level in levels.items():
            if out[name]["reached"]:
                # Track favorable extension beyond level until D.
                if direction == "UP":
                    extreme_after[name] = max(extreme_after.get(name, level), hi)
                else:
                    extreme_after[name] = min(extreme_after.get(name, level), lo)
                continue
            hit = (hi >= level) if direction == "UP" else (lo <= level)
            if hit:
                out[name]["reached"] = True
                out[name]["at"] = ts
                out[name]["first_touch_price"] = level
                extreme_after[name] = hi if direction == "UP" else lo

    for name, level in levels.items():
        if out[name]["reached"] and name in extreme_after:
            if direction == "UP":
                out[name]["overshoot_ab"] = (extreme_after[name] - level) / abs_ab
            else:
                out[name]["overshoot_ab"] = (level - extreme_after[name]) / abs_ab
    return out


def summarize_windows(windows: list[AbcWindow], *, label: str) -> dict[str, Any]:
    if not windows:
        return {"label": label, "count": 0}
    rs = [w.r for w in windows]
    rs_sorted = sorted(rs)
    sanity_pass = sum(1 for w in windows if w.direction_sanity)
    sanity_fail = len(windows) - sanity_pass

    def within_pct(target: str, tol: float) -> float:
        key = {"COP": "cop_error_pct", "OP": "op_error_pct", "XOP": "xop_error_pct"}[target]
        hits = sum(1 for w in windows if getattr(w, key) <= tol)
        return hits / len(windows)

    def within_r(target_r: float, tol: float) -> float:
        hits = sum(1 for w in windows if abs(w.r - target_r) <= tol)
        return hits / len(windows)

    nearest_counts = {"COP": 0, "OP": 0, "XOP": 0}
    for w in windows:
        nearest_counts[w.nearest_target] = nearest_counts.get(w.nearest_target, 0) + 1

    cop_r = sum(1 for w in windows if w.cop_reached) / len(windows)
    op_r = sum(1 for w in windows if w.op_reached) / len(windows)
    xop_r = sum(1 for w in windows if w.xop_reached) / len(windows)
    cop_hit = [w for w in windows if w.cop_reached]
    op_hit = [w for w in windows if w.op_reached]
    p_op_given_cop = (sum(1 for w in cop_hit if w.op_reached) / len(cop_hit)) if cop_hit else None
    p_xop_given_op = (sum(1 for w in op_hit if w.xop_reached) / len(op_hit)) if op_hit else None
    p_xop_given_cop = (sum(1 for w in cop_hit if w.xop_reached) / len(cop_hit)) if cop_hit else None

    # Best fixed fib by median AB error
    med_errs = {
        "COP": median([w.cop_error_ab for w in windows]),
        "OP": median([w.op_error_ab for w in windows]),
        "XOP": median([w.xop_error_ab for w in windows]),
    }
    best_fixed = min(med_errs, key=med_errs.get)

    baseline_r1 = median([w.baseline_r1_error_ab for w in windows])
    baseline_med_vals = [w.baseline_median_error_ab for w in windows if w.baseline_median_error_ab is not None]
    baseline_prev_vals = [
        w.baseline_prev_same_dir_error_ab for w in windows if w.baseline_prev_same_dir_error_ab is not None
    ]
    dinapoli_best_med = med_errs[best_fixed]

    modes = _find_modes(rs_sorted)

    return {
        "label": label,
        "count": len(windows),
        "direction_sanity_pass": sanity_pass,
        "direction_sanity_fail": sanity_fail,
        "r_mean": mean(rs),
        "r_median": median(rs),
        "r_std": pstdev(rs) if len(rs) > 1 else 0.0,
        "r_p10": _percentile(rs_sorted, 10),
        "r_p25": _percentile(rs_sorted, 25),
        "r_p50": _percentile(rs_sorted, 50),
        "r_p75": _percentile(rs_sorted, 75),
        "r_p90": _percentile(rs_sorted, 90),
        "empirical_r_modes": modes,
        "nearest_counts": nearest_counts,
        "endpoint_within_2pct": {
            "COP": within_pct("COP", 2),
            "OP": within_pct("OP", 2),
            "XOP": within_pct("XOP", 2),
        },
        "endpoint_within_5pct": {
            "COP": within_pct("COP", 5),
            "OP": within_pct("OP", 5),
            "XOP": within_pct("XOP", 5),
        },
        "endpoint_within_10pct": {
            "COP": within_pct("COP", 10),
            "OP": within_pct("OP", 10),
            "XOP": within_pct("XOP", 10),
        },
        "ratio_within_0_10": {
            "COP": within_r(FIB_COP, 0.10),
            "OP": within_r(FIB_OP, 0.10),
            "XOP": within_r(FIB_XOP, 0.10),
        },
        "ratio_within_0_20": {
            "COP": within_r(FIB_COP, 0.20),
            "OP": within_r(FIB_OP, 0.20),
            "XOP": within_r(FIB_XOP, 0.20),
        },
        "cop_reach_rate": cop_r,
        "op_reach_rate": op_r,
        "xop_reach_rate": xop_r,
        "p_op_given_cop": p_op_given_cop,
        "p_xop_given_op": p_xop_given_op,
        "p_xop_given_cop": p_xop_given_cop,
        "median_error_ab": med_errs,
        "best_fixed_target": best_fixed,
        "baseline_r1_median_error_ab": baseline_r1,
        "baseline_median_r_median_error_ab": median(baseline_med_vals) if baseline_med_vals else None,
        "baseline_prev_same_dir_median_error_ab": median(baseline_prev_vals) if baseline_prev_vals else None,
        "dinapoli_best_median_error_ab": dinapoli_best_med,
        "mean_overshoot_ab": {
            "COP": _mean_or_none([w.cop_overshoot_ab for w in windows if w.cop_overshoot_ab is not None]),
            "OP": _mean_or_none([w.op_overshoot_ab for w in windows if w.op_overshoot_ab is not None]),
            "XOP": _mean_or_none([w.xop_overshoot_ab for w in windows if w.xop_overshoot_ab is not None]),
        },
    }


def _mean_or_none(vals: list[float]) -> float | None:
    return mean(vals) if vals else None


def _find_modes(sorted_rs: list[float], bin_width: float = 0.05) -> list[dict[str, Any]]:
    if not sorted_rs:
        return []
    lo = math.floor(sorted_rs[0] / bin_width) * bin_width
    hi = math.ceil(sorted_rs[-1] / bin_width) * bin_width
    bins: dict[float, int] = {}
    x = lo
    while x <= hi + 1e-12:
        bins[round(x, 10)] = 0
        x += bin_width
    for r in sorted_rs:
        key = round(math.floor(r / bin_width) * bin_width, 10)
        bins[key] = bins.get(key, 0) + 1
    ranked = sorted(bins.items(), key=lambda kv: (-kv[1], kv[0]))
    top = []
    for center, count in ranked[:8]:
        if count <= 0:
            continue
        mid = center + bin_width / 2
        label = "OTHER"
        for name, target in (("COP", FIB_COP), ("OP", FIB_OP), ("XOP", FIB_XOP)):
            if abs(mid - target) <= bin_width:
                label = name
                break
        top.append({"bin_start": center, "bin_mid": mid, "count": count, "near": label})
    return top


def ratio_histogram(windows: list[AbcWindow], bin_width: float = 0.05) -> list[dict[str, Any]]:
    rs = sorted(w.r for w in windows)
    if not rs:
        return []
    lo = math.floor(min(rs) / bin_width) * bin_width
    hi = math.ceil(max(rs) / bin_width) * bin_width
    rows = []
    x = lo
    while x <= hi + 1e-12:
        c0, c1 = x, x + bin_width
        count = sum(1 for r in rs if c0 <= r < c1 or (r == c1 and abs(r - hi) < 1e-12))
        rows.append({"bin_start": c0, "bin_end": c1, "count": count})
        x += bin_width
    return rows


def chronological_split(windows: list[AbcWindow], discovery_frac: float = 0.70) -> tuple[list[AbcWindow], list[AbcWindow]]:
    n = len(windows)
    if n == 0:
        return [], []
    cut = max(1, int(round(n * discovery_frac)))
    cut = min(cut, n - 1) if n > 1 else n
    disc = windows[:cut]
    hold = windows[cut:]
    for w in disc:
        w.split = "DISCOVERY"
    for w in hold:
        w.split = "VALIDATION"
    return disc, hold


def write_windows_csv(path: Path, windows: Iterable[AbcWindow]) -> None:
    rows = [asdict(w) for w in windows]
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_histogram_csv(path: Path, hist: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["bin_start", "bin_end", "count"])
        writer.writeheader()
        writer.writerows(hist)


def classify_signal(discovery: dict, validation: dict) -> str:
    """Heuristic signal strength for DiNapoli on this TF."""
    if not validation or validation.get("count", 0) < 20:
        return "INCONCLUSIVE"
    r_med = validation.get("r_median")
    near5 = validation.get("endpoint_within_5pct", {})
    ratio10 = validation.get("ratio_within_0_10", {})
    best = validation.get("best_fixed_target")
    din = validation.get("dinapoli_best_median_error_ab")
    base = validation.get("baseline_r1_median_error_ab")
    modes = validation.get("empirical_r_modes") or []
    fib_mode_hits = sum(1 for m in modes[:5] if m.get("near") in ("COP", "OP", "XOP"))

    # Strong: median R near a fib, decent endpoint rate, beats R=1 baseline
    near_fib = any(abs((r_med or 0) - t) < 0.15 for t in (FIB_COP, FIB_OP, FIB_XOP))
    endpoint_ok = max(near5.values()) if near5 else 0
    ratio_ok = max(ratio10.values()) if ratio10 else 0
    beats_baseline = din is not None and base is not None and din < base * 0.95

    if near_fib and endpoint_ok >= 0.25 and ratio_ok >= 0.20 and beats_baseline and fib_mode_hits >= 1:
        return "STRONG"
    if (near_fib or fib_mode_hits >= 1) and (endpoint_ok >= 0.15 or ratio_ok >= 0.15):
        return "MODERATE"
    if endpoint_ok >= 0.10 or ratio_ok >= 0.10:
        return "WEAK"
    if fib_mode_hits == 0 and endpoint_ok < 0.08:
        return "NONE"
    return "INCONCLUSIVE"


def run_4h_validation(
    candles: list[dict],
    *,
    out_dir: Path,
    zigzag_cfg: dict | None = None,
) -> dict[str, Any]:
    cfg = {**ZIGZAG_DEFAULT, **(zigzag_cfg or {})}
    pivots = classic_percent_zigzag(
        candles,
        deviation_percent=float(cfg["deviation"]),
        depth=int(cfg["depth"]),
        backstep=int(cfg["backstep"]),
    )
    # First pass windows without median baseline.
    raw = build_abc_windows(pivots, candles, tf="4H", discovery_median_r=None)
    discovery, validation = chronological_split(raw, 0.70)
    disc_median_r = median([w.r for w in discovery]) if discovery else 1.0

    # Rebuild with discovery median baseline attached.
    windows = build_abc_windows(pivots, candles, tf="4H", discovery_median_r=disc_median_r)
    discovery, validation = chronological_split(windows, 0.70)
    # Recompute median baseline errors for validation using frozen discovery median.
    for w in validation:
        pred = w.c_price + w.ab * disc_median_r
        w.baseline_median_error_ab = abs(w.d_price - pred) / abs(w.ab)

    disc_summary = summarize_windows(discovery, label="DISCOVERY")
    val_summary = summarize_windows(validation, label="VALIDATION")
    full_summary = summarize_windows(windows, label="FULL")
    hist = ratio_histogram(windows)
    hist_disc = ratio_histogram(discovery)
    hist_val = ratio_histogram(validation)

    din_vs_base = {
        "discovery_median_r": disc_median_r,
        "validation_dinapoli_best": val_summary.get("best_fixed_target"),
        "validation_dinapoli_median_error_ab": val_summary.get("dinapoli_best_median_error_ab"),
        "validation_baseline_r1_median_error_ab": val_summary.get("baseline_r1_median_error_ab"),
        "validation_baseline_empirical_median_error_ab": val_summary.get("baseline_median_r_median_error_ab"),
        "validation_baseline_prev_same_dir_median_error_ab": val_summary.get(
            "baseline_prev_same_dir_median_error_ab"
        ),
    }
    if (
        din_vs_base["validation_dinapoli_median_error_ab"] is not None
        and din_vs_base["validation_baseline_r1_median_error_ab"] is not None
    ):
        din = din_vs_base["validation_dinapoli_median_error_ab"]
        base = din_vs_base["validation_baseline_r1_median_error_ab"]
        din_vs_base["beats_r1_baseline"] = din < base
        din_vs_base["error_ratio_vs_r1"] = din / base if base else None
    if din_vs_base.get("validation_baseline_empirical_median_error_ab") is not None:
        din = din_vs_base["validation_dinapoli_median_error_ab"]
        base_m = din_vs_base["validation_baseline_empirical_median_error_ab"]
        din_vs_base["beats_empirical_median_baseline"] = din < base_m if din is not None else None

    signal = classify_signal(disc_summary, val_summary)

    out_dir.mkdir(parents=True, exist_ok=True)
    write_windows_csv(out_dir / "dinapoli_4h_windows.csv", windows)
    write_windows_csv(out_dir / "dinapoli_4h_validation.csv", validation)
    write_histogram_csv(out_dir / "dinapoli_4h_ratio_distribution.csv", hist)

    report = {
        "wip": "DINAPOLI-COP-OP-XOP-4H-VALIDATION-1",
        "tf": "4H",
        "zigzag_config": cfg,
        "total_pivots": len(pivots),
        "total_abc_windows": len(windows),
        "discovery_windows": len(discovery),
        "validation_windows": len(validation),
        "discovery": disc_summary,
        "validation": val_summary,
        "full": full_summary,
        "dinapoli_vs_baseline": din_vs_base,
        "ratio_histogram_full": hist,
        "ratio_histogram_discovery": hist_disc,
        "ratio_histogram_validation": hist_val,
        "dinapoli_4h_signal": signal,
        "ready_for_multitimeframe_test": signal in ("STRONG", "MODERATE", "WEAK"),
    }
    (out_dir / "dinapoli_4h_summary.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    # Simple text plot artifact for R distribution
    _write_ascii_hist(out_dir / "dinapoli_4h_r_distribution.txt", hist, title="R distribution (full)")
    return report


def _write_ascii_hist(path: Path, hist: list[dict[str, Any]], title: str) -> None:
    if not hist:
        path.write_text(title + "\n(empty)\n", encoding="utf-8")
        return
    max_c = max(h["count"] for h in hist) or 1
    lines = [title, ""]
    for h in hist:
        if h["count"] == 0 and (h["bin_start"] < -0.5 or h["bin_start"] > 3.0):
            continue
        bar = "#" * int(40 * h["count"] / max_c)
        mark = ""
        mid = (h["bin_start"] + h["bin_end"]) / 2
        for name, t in (("COP", FIB_COP), ("OP", FIB_OP), ("XOP", FIB_XOP)):
            if abs(mid - t) < 0.05:
                mark = f"  ← {name}"
                break
        lines.append(f"{h['bin_start']:6.2f}-{h['bin_end']:5.2f} | {h['count']:4d} {bar}{mark}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
