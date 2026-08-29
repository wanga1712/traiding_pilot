"""Build immutable WAVE_DATASET_V1 from WAVE_ENGINE_V1."""
from __future__ import annotations

import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median, pstdev
from typing import Any

from crypto_trading_bot.research_v2.resampling import TIMEFRAMES as TF_MINUTES
from crypto_trading_bot.research_v2.wave_engine.v1_config import (
    CONFIG_BY_TF,
    MARKET_SOURCE,
    QUALITY_FLAG_BY_TF,
    RESEARCH_DECISIONS,
    SYMBOL,
    TIMEFRAMES,
    WAVE_DATASET_VERSION,
    WAVE_ENGINE_VERSION,
)
from crypto_trading_bot.research_v2.zigzag.classic import (
    ZigZagPivot,
    classic_atr_zigzag,
    compute_atr_series,
)

DISCOVERY_FRAC = 0.70
LEGACY_FIB = (0.618, 1.0, 1.618)


def _parse_ts(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    text = str(value).replace("Z", "+00:00")
    if text.endswith("+00"):
        text += ":00"
    return datetime.fromisoformat(text)


def _percentile(sorted_vals: list[float], p: float) -> float | None:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    return sorted_vals[f] * (c - k) + sorted_vals[c] * (k - f)


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_pivots_rows(
    pivots: list[ZigZagPivot],
    candles: list[dict],
    *,
    tf: str,
) -> list[dict[str, Any]]:
    cfg = CONFIG_BY_TF[tf]
    quality = QUALITY_FLAG_BY_TF[tf]
    rows = []
    for i, p in enumerate(pivots):
        conf_delay = int(p.confirmation_index) - int(p.index)
        rows.append(
            {
                "wave_engine_version": WAVE_ENGINE_VERSION,
                "symbol": SYMBOL,
                "market_source": MARKET_SOURCE,
                "timeframe": tf,
                "pivot_index": i,
                "bar_index": int(p.index),
                "pivot_time": p.timestamp,
                "pivot_price": float(p.price),
                "pivot_type": p.kind,
                "confirmation_time": p.confirmation_timestamp,
                "confirmation_bar_index": int(p.confirmation_index),
                "confirmation_delay_bars": conf_delay,
                "is_confirmed": True,
                "quality_flag": quality,
                "atr_n": cfg["atr_n"],
                "atr_k": cfg["atr_k"],
                "depth": cfg["depth"],
                "backstep": cfg["backstep"],
                "config_group": cfg["group"],
            }
        )
    return rows


def build_legs_rows(
    pivots: list[ZigZagPivot],
    candles: list[dict],
    atr: list[float],
    *,
    tf: str,
) -> list[dict[str, Any]]:
    minutes = TF_MINUTES[tf]
    quality = QUALITY_FLAG_BY_TF[tf]
    rows = []
    for i in range(len(pivots) - 1):
        a, b = pivots[i], pivots[i + 1]
        start_i, end_i = int(a.index), int(b.index)
        move_abs = float(b.price) - float(a.price)
        start_px = float(a.price)
        move_pct = (move_abs / abs(start_px) * 100.0) if start_px else None
        dur_bars = end_i - start_i
        dur_seconds = dur_bars * minutes * 60
        atr_start = atr[start_i] if 0 <= start_i < len(atr) else None
        atr_end = atr[end_i] if 0 <= end_i < len(atr) else None
        move_atr_start = (abs(move_abs) / atr_start) if atr_start and atr_start > 0 else None
        # Causal mean ATR along the leg (bars from start..end inclusive at each bar).
        atr_window = [atr[j] for j in range(start_i, end_i + 1) if 0 <= j < len(atr) and atr[j] > 0]
        atr_mean = mean(atr_window) if atr_window else None
        move_atr_mean = (abs(move_abs) / atr_mean) if atr_mean and atr_mean > 0 else None
        rows.append(
            {
                "wave_engine_version": WAVE_ENGINE_VERSION,
                "symbol": SYMBOL,
                "timeframe": tf,
                "leg_index": i,
                "start_pivot_index": i,
                "end_pivot_index": i + 1,
                "start_time": a.timestamp,
                "end_time": b.timestamp,
                "start_price": float(a.price),
                "end_price": float(b.price),
                "direction": "UP" if move_abs > 0 else "DOWN",
                "move_abs": move_abs,
                "move_pct": move_pct,
                "duration_bars": dur_bars,
                "duration_seconds": dur_seconds,
                "duration_hours": dur_seconds / 3600.0,
                "ATR_at_start": atr_start,
                "ATR_at_end": atr_end,
                "move_atr_start": move_atr_start,
                "move_atr_mean": move_atr_mean,
                "quality_flag": quality,
            }
        )
    return rows


def build_rolling_geometry_rows(
    pivots: list[ZigZagPivot],
    *,
    tf: str,
) -> list[dict[str, Any]]:
    quality = QUALITY_FLAG_BY_TF[tf]
    rows = []
    for i in range(len(pivots) - 3):
        a, b, c, d = pivots[i], pivots[i + 1], pivots[i + 2], pivots[i + 3]
        ab = float(b.price) - float(a.price)
        cd = float(d.price) - float(c.price)
        if ab == 0:
            continue
        r = cd / ab
        # Legacy diagnostic only — not canonical targets.
        cop = float(c.price) + ab * LEGACY_FIB[0]
        op = float(c.price) + ab * LEGACY_FIB[1]
        xop = float(c.price) + ab * LEGACY_FIB[2]
        rows.append(
            {
                "wave_engine_version": WAVE_ENGINE_VERSION,
                "symbol": SYMBOL,
                "timeframe": tf,
                "window_index": i,
                "a_pivot_index": i,
                "b_pivot_index": i + 1,
                "c_pivot_index": i + 2,
                "d_pivot_index": i + 3,
                "a_time": a.timestamp,
                "b_time": b.timestamp,
                "c_time": c.timestamp,
                "d_time": d.timestamp,
                "a_price": float(a.price),
                "b_price": float(b.price),
                "c_price": float(c.price),
                "d_price": float(d.price),
                "AB_signed": ab,
                "CD_signed": cd,
                "R": r,
                "abs_R": abs(r),
                "R_BASELINE": 1.0,
                "LEG_PERSISTENCE_BASELINE": "LEG_PERSISTENCE_BASELINE_V1",
                "LEGACY_DIAGNOSTIC_ONLY": True,
                "COP_0618": cop,
                "OP_1000": op,
                "XOP_1618": xop,
                "quality_flag": quality,
                "split": "",  # filled later chronologically
            }
        )
    # Chronological discovery/validation labels (metadata only; R itself uses full set for distribution).
    n = len(rows)
    if n:
        cut = max(1, int(round(n * DISCOVERY_FRAC)))
        cut = min(cut, n - 1) if n > 1 else n
        for j, row in enumerate(rows):
            row["split"] = "DISCOVERY" if j < cut else "VALIDATION"
    return rows


def r_distribution(rs: list[float], *, tf: str, label: str) -> dict[str, Any]:
    if not rs:
        return {"timeframe": tf, "label": label, "count": 0}
    s = sorted(rs)
    med = median(rs)
    return {
        "timeframe": tf,
        "label": label,
        "count": len(rs),
        "mean": mean(rs),
        "median": med,
        "std": pstdev(rs) if len(rs) > 1 else 0.0,
        "P01": _percentile(s, 1),
        "P05": _percentile(s, 5),
        "P10": _percentile(s, 10),
        "P25": _percentile(s, 25),
        "P50": _percentile(s, 50),
        "P75": _percentile(s, 75),
        "P90": _percentile(s, 90),
        "P95": _percentile(s, 95),
        "P99": _percentile(s, 99),
        "MAD": median([abs(x - 1.0) for x in rs]),
        "MAE_R_EQ_1": mean([abs(x - 1.0) for x in rs]),
        "distribution_id": "EMPIRICAL_R_DISTRIBUTION_V1",
        "R_BASELINE": 1.0,
        "LEG_PERSISTENCE_BASELINE": "LEG_PERSISTENCE_BASELINE_V1",
    }


def validate_pivots(rows: list[dict]) -> dict[str, Any]:
    errors = []
    if not rows:
        return {"ok": False, "errors": ["NO_PIVOTS"], "pivot_count": 0}
    times = [_parse_ts(r["pivot_time"]) for r in rows]
    for i in range(1, len(times)):
        if times[i] < times[i - 1]:
            errors.append(f"NON_MONOTONIC_TIME@{i}")
            break
    idxs = [r["pivot_index"] for r in rows]
    if len(idxs) != len(set(idxs)):
        errors.append("DUPLICATE_PIVOT_INDEX")
    bar_idxs = [r["bar_index"] for r in rows]
    if len(bar_idxs) != len(set(bar_idxs)):
        errors.append("DUPLICATE_BAR_INDEX")
    for i in range(1, len(rows)):
        if rows[i]["pivot_type"] == rows[i - 1]["pivot_type"]:
            errors.append(f"ALTERNATION_FAIL@{i}")
            break
    for r in rows:
        if r["confirmation_delay_bars"] < 0:
            errors.append("NEGATIVE_CONFIRMATION_DELAY")
            break
        # Confirmation must not precede pivot bar (anti-lookahead in metadata).
        if r["confirmation_bar_index"] < r["bar_index"]:
            errors.append("CONFIRMATION_BEFORE_PIVOT")
            break
    return {"ok": len(errors) == 0, "errors": errors, "pivot_count": len(rows)}


def validate_legs(leg_rows: list[dict], pivot_rows: list[dict]) -> dict[str, Any]:
    errors = []
    if not leg_rows:
        return {"ok": False, "errors": ["NO_LEGS"], "leg_count": 0}
    by_idx = {r["pivot_index"]: r for r in pivot_rows}
    for leg in leg_rows:
        s = by_idx.get(leg["start_pivot_index"])
        e = by_idx.get(leg["end_pivot_index"])
        if not s or not e:
            errors.append(f"LEG_PIVOT_MISSING@{leg['leg_index']}")
            continue
        if s["pivot_time"] != leg["start_time"] or e["pivot_time"] != leg["end_time"]:
            errors.append(f"LEG_TIME_MISMATCH@{leg['leg_index']}")
        if float(s["pivot_price"]) != float(leg["start_price"]) or float(e["pivot_price"]) != float(leg["end_price"]):
            errors.append(f"LEG_PRICE_MISMATCH@{leg['leg_index']}")
        if leg["end_pivot_index"] != leg["start_pivot_index"] + 1:
            errors.append(f"LEG_NOT_ADJACENT@{leg['leg_index']}")
        expected_dir = "UP" if float(leg["end_price"]) > float(leg["start_price"]) else "DOWN"
        if leg["direction"] != expected_dir:
            errors.append(f"LEG_DIRECTION_MISMATCH@{leg['leg_index']}")
    # Connectivity: consecutive legs share pivots
    for i in range(1, len(leg_rows)):
        if leg_rows[i]["start_pivot_index"] != leg_rows[i - 1]["end_pivot_index"]:
            errors.append(f"LEG_DISCONNECT@{i}")
            break
    return {"ok": len(errors) == 0, "errors": errors[:20], "leg_count": len(leg_rows)}


def validate_r(geo_rows: list[dict]) -> dict[str, Any]:
    errors = []
    finite = 0
    for r in geo_rows:
        val = r.get("R")
        if val is None or not math.isfinite(float(val)):
            errors.append(f"NON_FINITE_R@{r.get('window_index')}")
        else:
            finite += 1
        if abs(float(r["AB_signed"])) < 1e-18:
            errors.append(f"ZERO_AB@{r.get('window_index')}")
    return {
        "ok": len(errors) == 0,
        "errors": errors[:20],
        "rolling_window_count": len(geo_rows),
        "finite_r_count": finite,
    }


def write_parquet_or_csv(path_parquet: Path, rows: list[dict]) -> Path:
    if not rows:
        path_csv = path_parquet.with_suffix(".csv")
        path_csv.write_text("", encoding="utf-8")
        return path_csv
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq

        table = pa.Table.from_pylist(rows)
        pq.write_table(table, path_parquet, compression="zstd")
        return path_parquet
    except Exception:
        path_csv = path_parquet.with_suffix(".csv")
        with path_csv.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        return path_csv


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def process_tf(candles: list[dict], tf: str) -> dict[str, Any]:
    cfg = CONFIG_BY_TF[tf]
    atr = compute_atr_series(candles, int(cfg["atr_n"]))
    pivots = classic_atr_zigzag(
        candles,
        atr_mult=float(cfg["atr_k"]),
        depth=int(cfg["depth"]),
        backstep=int(cfg["backstep"]),
        atr_period=int(cfg["atr_n"]),
        atr_series=atr,
    )
    pivot_rows = build_pivots_rows(pivots, candles, tf=tf)
    leg_rows = build_legs_rows(pivots, candles, atr, tf=tf)
    geo_rows = build_rolling_geometry_rows(pivots, tf=tf)
    rs_full = [float(r["R"]) for r in geo_rows]
    rs_val = [float(r["R"]) for r in geo_rows if r["split"] == "VALIDATION"]
    rs_disc = [float(r["R"]) for r in geo_rows if r["split"] == "DISCOVERY"]
    t0 = candles[0]["open_time_utc"] if candles else None
    t1 = candles[-1]["open_time_utc"] if candles else None
    return {
        "tf": tf,
        "candle_count": len(candles),
        "time_from": str(t0),
        "time_to": str(t1),
        "pivots": pivots,
        "pivot_rows": pivot_rows,
        "leg_rows": leg_rows,
        "geo_rows": geo_rows,
        "r_dist_full": r_distribution(rs_full, tf=tf, label="FULL"),
        "r_dist_discovery": r_distribution(rs_disc, tf=tf, label="DISCOVERY"),
        "r_dist_validation": r_distribution(rs_val, tf=tf, label="VALIDATION"),
        "pivot_validation": validate_pivots(pivot_rows),
        "leg_validation": validate_legs(leg_rows, pivot_rows),
        "r_validation": validate_r(geo_rows),
        "quality_flag": QUALITY_FLAG_BY_TF[tf],
        "config": cfg,
    }


def run_freeze(
    candles_by_tf: dict[str, list[dict]],
    *,
    out_dir: Path,
    git_commit: str | None = None,
    implementation_commit: str | None = None,
) -> dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Refuse overwrite of an existing frozen manifest.
    manifest_path = out_dir / "wave_dataset_manifest_v1.json"
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        raise RuntimeError(
            f"Refusing to overwrite frozen {WAVE_DATASET_VERSION} at {out_dir} "
            f"(created_at={existing.get('created_at')}). Create WAVE_DATASET_V2 instead."
        )

    created_at = datetime.now(timezone.utc).isoformat()
    all_pivots: list[dict] = []
    all_legs: list[dict] = []
    all_geo: list[dict] = []
    r_dists: list[dict] = []
    tf_summaries: list[dict] = []
    validations: dict[str, Any] = {}

    for tf in TIMEFRAMES:
        candles = candles_by_tf.get(tf) or []
        print(f"[freeze] {tf} candles={len(candles)} cfg={CONFIG_BY_TF[tf]}", flush=True)
        result = process_tf(candles, tf)
        all_pivots.extend(result["pivot_rows"])
        all_legs.extend(result["leg_rows"])
        all_geo.extend(result["geo_rows"])
        r_dists.extend([result["r_dist_full"], result["r_dist_discovery"], result["r_dist_validation"]])
        validations[tf] = {
            "pivot_validation": result["pivot_validation"],
            "leg_validation": result["leg_validation"],
            "r_validation": result["r_validation"],
            "quality_flag": result["quality_flag"],
        }
        tf_summaries.append(
            {
                "timeframe": tf,
                "config": result["config"],
                "quality_flag": result["quality_flag"],
                "candle_count": result["candle_count"],
                "time_from": result["time_from"],
                "time_to": result["time_to"],
                "pivot_count": len(result["pivot_rows"]),
                "leg_count": len(result["leg_rows"]),
                "rolling_window_count": len(result["geo_rows"]),
                "r_median_full": result["r_dist_full"].get("median"),
                "r_median_validation": result["r_dist_validation"].get("median"),
                "pivot_ok": result["pivot_validation"]["ok"],
                "leg_ok": result["leg_validation"]["ok"],
                "r_ok": result["r_validation"]["ok"],
            }
        )

    pivots_path = write_parquet_or_csv(out_dir / "wave_pivots_v1.parquet", all_pivots)
    legs_path = write_parquet_or_csv(out_dir / "wave_legs_v1.parquet", all_legs)
    geo_path = write_parquet_or_csv(out_dir / "rolling_geometry_v1.parquet", all_geo)
    write_csv(out_dir / "r_distribution_by_tf_v1.csv", r_dists)
    write_csv(out_dir / "tf_summary_v1.csv", tf_summaries)

    engine_manifest = {
        "wave_engine_version": WAVE_ENGINE_VERSION,
        "algorithm_family": "classic_atr_zigzag",
        "normalization_method": "ATR_directional_change_grouped_by_TF",
        "depth": 3,
        "backstep": 0,
        "config_by_tf": CONFIG_BY_TF,
        "quality_flag_by_tf": QUALITY_FLAG_BY_TF,
        "research_decisions": RESEARCH_DECISIONS,
        "implementation_module": "crypto_trading_bot.research_v2.zigzag.classic.classic_atr_zigzag",
        "implementation_commit": implementation_commit or git_commit,
        "created_at": created_at,
    }
    (out_dir / "wave_engine_manifest_v1.json").write_text(
        json.dumps(engine_manifest, indent=2, default=str), encoding="utf-8"
    )

    artifact_files = [
        pivots_path,
        legs_path,
        geo_path,
        out_dir / "r_distribution_by_tf_v1.csv",
        out_dir / "tf_summary_v1.csv",
        out_dir / "wave_engine_manifest_v1.json",
    ]
    checksums = {str(p.name): _file_sha256(p) for p in artifact_files if p.exists()}

    times_from = [s["time_from"] for s in tf_summaries if s["time_from"]]
    times_to = [s["time_to"] for s in tf_summaries if s["time_to"]]
    dataset_manifest = {
        "dataset_version": WAVE_DATASET_VERSION,
        "wave_engine_version": WAVE_ENGINE_VERSION,
        "created_at": created_at,
        "symbol": SYMBOL,
        "market_source": MARKET_SOURCE,
        "git_commit": git_commit,
        "implementation_commit": implementation_commit or git_commit,
        "timeframes": list(TIMEFRAMES),
        "config_by_tf": CONFIG_BY_TF,
        "quality_flag_by_tf": QUALITY_FLAG_BY_TF,
        "research_decisions": RESEARCH_DECISIONS,
        "row_counts": {
            "pivots": len(all_pivots),
            "legs": len(all_legs),
            "rolling_geometry": len(all_geo),
        },
        "pivots_by_tf": {s["timeframe"]: s["pivot_count"] for s in tf_summaries},
        "legs_by_tf": {s["timeframe"]: s["leg_count"] for s in tf_summaries},
        "rolling_windows_by_tf": {s["timeframe"]: s["rolling_window_count"] for s in tf_summaries},
        "r_median_by_tf": {s["timeframe"]: s["r_median_full"] for s in tf_summaries},
        "dataset_time_from": min(times_from) if times_from else None,
        "dataset_time_to": max(times_to) if times_to else None,
        "tf_summaries": tf_summaries,
        "validations": validations,
        "artifact_files": [p.name for p in artifact_files],
        "checksums_sha256": checksums,
        "immutable": True,
        "overwrite_policy": "FORBIDDEN — next revision must be WAVE_DATASET_V2",
        "LEGACY_FIB_FIELDS_STATUS": "LEGACY_DIAGNOSTIC_ONLY",
        "LEG_PERSISTENCE_BASELINE": "LEG_PERSISTENCE_BASELINE_V1",
        "EMPIRICAL_R_DISTRIBUTION": "EMPIRICAL_R_DISTRIBUTION_V1",
    }
    manifest_path.write_text(json.dumps(dataset_manifest, indent=2, default=str), encoding="utf-8")
    # Freeze marker
    (out_dir / "WAVE_DATASET_V1_IMMUTABLE.txt").write_text(
        f"{WAVE_DATASET_VERSION} frozen at {created_at}\nDo not overwrite.\n",
        encoding="utf-8",
    )

    overall_ok = all(
        validations[tf]["pivot_validation"]["ok"]
        and validations[tf]["leg_validation"]["ok"]
        and validations[tf]["r_validation"]["ok"]
        for tf in TIMEFRAMES
        if tf in validations
    )

    report = {
        "wip": "WAVE-DATASET-FREEZE-1",
        "wave_engine_version": WAVE_ENGINE_VERSION,
        "wave_dataset_version": WAVE_DATASET_VERSION,
        "out_dir": str(out_dir),
        "overall_validation_ok": overall_ok,
        "dataset_manifest": dataset_manifest,
        "engine_manifest": engine_manifest,
        "tf_summaries": tf_summaries,
    }
    (out_dir / "summary.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report
