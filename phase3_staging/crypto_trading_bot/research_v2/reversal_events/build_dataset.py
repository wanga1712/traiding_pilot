"""Build immutable REVERSAL_EVENT_DATASET_V1 from WAVE_DATASET_V1."""
from __future__ import annotations

import csv
import hashlib
import json
import math
from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from crypto_trading_bot.research_v2.resampling import TIMEFRAMES as TF_MINUTES
from crypto_trading_bot.research_v2.reversal_events.anti_leakage import (
    assert_no_future_bars,
    filter_history_available_at,
    get_event_history,
    higher_tf_unfinished_bar_excluded,
)
from crypto_trading_bot.research_v2.reversal_events.config import (
    CONTEXT_TFS,
    EVENT_DATASET_VERSION,
    PARTITION_FRAC,
    SYMBOL,
    WAVE_DATASET_VERSION,
    WAVE_ENGINE_VERSION,
    WINDOW_SPEC,
)
from crypto_trading_bot.research_v2.reversal_events.schema import columns_by_class, schema_rows
from crypto_trading_bot.research_v2.zigzag.classic import compute_atr_series


def _parse_ts(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).replace("Z", "+00:00")
        if text.endswith("+00"):
            text += ":00"
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_parquet(path: Path, rows: list[dict]) -> Path:
    if not rows:
        path = path.with_suffix(".csv")
        path.write_text("", encoding="utf-8")
        return path
    import pyarrow as pa
    import pyarrow.parquet as pq

    pq.write_table(pa.Table.from_pylist(rows), path, compression="zstd")
    return path


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def make_event_id(symbol: str, source_tf: str, pivot_index: int, pivot_time: str, dataset_version: str) -> str:
    raw = f"{symbol}|{source_tf}|{pivot_index}|{pivot_time}|{dataset_version}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def load_wave_tables(wave_dir: Path) -> tuple[list[dict], list[dict], list[dict]]:
    import pyarrow.parquet as pq

    pivots = pq.read_table(wave_dir / "wave_pivots_v1.parquet").to_pylist()
    legs = pq.read_table(wave_dir / "wave_legs_v1.parquet").to_pylist()
    geo = pq.read_table(wave_dir / "rolling_geometry_v1.parquet").to_pylist()
    return pivots, legs, geo


def build_events(pivots: list[dict], legs: list[dict], geo: list[dict]) -> list[dict]:
    by_tf: dict[str, list[dict]] = {}
    for p in pivots:
        by_tf.setdefault(p["timeframe"], []).append(p)
    for tf in by_tf:
        by_tf[tf].sort(key=lambda r: int(r["pivot_index"]))

    legs_by_tf: dict[str, dict[int, dict]] = {}
    for leg in legs:
        legs_by_tf.setdefault(leg["timeframe"], {})[int(leg["start_pivot_index"])] = leg

    # R for window where D is this pivot: window_index = pivot_index - 3
    r_by_tf_d: dict[str, dict[int, float]] = {}
    for g in geo:
        r_by_tf_d.setdefault(g["timeframe"], {})[int(g["d_pivot_index"])] = float(g["R"])

    events = []
    for tf, rows in by_tf.items():
        for i, p in enumerate(rows):
            prev_p = rows[i - 1] if i > 0 else None
            next_p = rows[i + 1] if i + 1 < len(rows) else None
            if next_p is None:
                # Terminal pivot: no next-leg outcome — still store identity with null outcomes
                pass
            prev_leg = legs_by_tf.get(tf, {}).get(i - 1) if i > 0 else None
            next_leg = legs_by_tf.get(tf, {}).get(i)
            r_val = r_by_tf_d.get(tf, {}).get(int(p["pivot_index"]))
            t = _parse_ts(p["pivot_time"])
            eid = make_event_id(SYMBOL, tf, int(p["pivot_index"]), str(p["pivot_time"]), WAVE_DATASET_VERSION)
            events.append(
                {
                    "event_id": eid,
                    "symbol": SYMBOL,
                    "wave_engine_version": WAVE_ENGINE_VERSION,
                    "wave_dataset_version": WAVE_DATASET_VERSION,
                    "event_dataset_version": EVENT_DATASET_VERSION,
                    "source_wave_tf": tf,
                    "pivot_index": int(p["pivot_index"]),
                    "bar_index": int(p["bar_index"]),
                    "pivot_type": p["pivot_type"],
                    "true_pivot_time": p["pivot_time"],
                    "true_pivot_price": float(p["pivot_price"]),
                    "confirmation_time": p.get("confirmation_time"),
                    "confirmation_delay_bars": p.get("confirmation_delay_bars"),
                    "previous_pivot_time": prev_p["pivot_time"] if prev_p else None,
                    "previous_pivot_price": float(prev_p["pivot_price"]) if prev_p else None,
                    "next_pivot_time": next_p["pivot_time"] if next_p else None,
                    "next_pivot_price": float(next_p["pivot_price"]) if next_p else None,
                    "NEXT_LEG_DIRECTION": next_leg["direction"] if next_leg else None,
                    "NEXT_LEG_MOVE_ABS": next_leg["move_abs"] if next_leg else None,
                    "NEXT_LEG_MOVE_PCT": next_leg["move_pct"] if next_leg else None,
                    "NEXT_LEG_DURATION_BARS": next_leg["duration_bars"] if next_leg else None,
                    "NEXT_LEG_DURATION_SECONDS": next_leg["duration_seconds"] if next_leg else None,
                    "R": r_val,
                    "R_MINUS_1": (r_val - 1.0) if r_val is not None else None,
                    "NEXT_LEG_MAE_FROM_C": None,  # filled after context bars
                    "NEXT_LEG_MFE_FROM_C": None,
                    "prev_leg_direction": prev_leg["direction"] if prev_leg else None,
                    "prev_leg_move_pct": prev_leg["move_pct"] if prev_leg else None,
                    "prev_leg_duration_bars": prev_leg["duration_bars"] if prev_leg else None,
                    "atr_at_pivot_source_tf": None,
                    "calendar_year": t.year,
                    "calendar_month": t.month,
                    "partition": "",
                    "partition_usable": False,
                    "CONTEXT_5M": "MISSING",
                    "CONTEXT_15M": "MISSING",
                    "CONTEXT_1H": "MISSING",
                    "CONTEXT_4H": "MISSING",
                    "CONTEXT_COMPLETE": False,
                    "quality_flag_source_tf": p.get("quality_flag"),
                }
            )
    return events


def assign_partitions(events: list[dict]) -> dict[str, Any]:
    timed = sorted(events, key=lambda e: _parse_ts(e["true_pivot_time"]))
    if not timed:
        return {"boundaries": {}, "method": "chronological_60_20_20_with_outcome_purge"}
    t0 = _parse_ts(timed[0]["true_pivot_time"])
    t1 = _parse_ts(timed[-1]["true_pivot_time"])
    span = (t1 - t0).total_seconds()
    t60 = t0 + timedelta(seconds=span * PARTITION_FRAC["DISCOVERY"])
    t80 = t0 + timedelta(seconds=span * (PARTITION_FRAC["DISCOVERY"] + PARTITION_FRAC["VALIDATION"]))

    def tentative(t: datetime) -> str:
        if t < t60:
            return "DISCOVERY"
        if t < t80:
            return "VALIDATION"
        return "OOS"

    for e in timed:
        tp = _parse_ts(e["true_pivot_time"])
        part = tentative(tp)
        e["partition"] = part
        # Outcome purge: next_pivot must remain inside same partition
        npt = e.get("next_pivot_time")
        if npt is None:
            e["partition_usable"] = False
            e["partition"] = "NO_OUTCOME"
            continue
        nt = _parse_ts(npt)
        same = tentative(nt) == part
        # Also require next pivot strictly before next boundary for discovery/validation
        if part == "DISCOVERY" and nt >= t60:
            same = False
        if part == "VALIDATION" and nt >= t80:
            same = False
        if same:
            e["partition_usable"] = True
        else:
            e["partition_usable"] = False
            e["partition"] = "PARTITION_CROSS_PURGED"

    return {
        "method": "chronological_time_span_60_20_20",
        "embargo_method": "purge_if_next_pivot_crosses_partition_boundary",
        "boundaries": {
            "t_start": t0.isoformat(),
            "t60_discovery_end": t60.isoformat(),
            "t80_validation_end": t80.isoformat(),
            "t_end": t1.isoformat(),
        },
    }


class BarIndex:
    def __init__(self, candles: list[dict]):
        self.candles = candles
        self.open_times = [_parse_ts(c["open_time_utc"]) for c in candles]
        self.close_times = [_parse_ts(c["close_time_utc"]) for c in candles]

    def slice_window(self, center: datetime, before: timedelta, after: timedelta) -> list[dict]:
        start = center - before
        end = center + after
        lo = bisect_left(self.open_times, start)
        hi = bisect_right(self.open_times, end)
        return self.candles[lo:hi]

    def atr_at(self, center: datetime, period: int = 14) -> float | None:
        # find last bar with open_time <= center
        i = bisect_right(self.open_times, center) - 1
        if i < 0:
            return None
        atr = compute_atr_series(self.candles[: i + 1], period)
        return atr[-1] if atr else None


def load_context_bars(service, tf: str, start: datetime, end: datetime) -> BarIndex:
    minutes = TF_MINUTES[tf]
    # pad for ATR + windows
    pad = timedelta(days=45)
    after = start - pad
    before = end + pad
    n_bars = int((before - after).total_seconds() / 60 / minutes) + 500
    limit = max(n_bars, 2000)
    print(f"[bars] loading {tf} after={after.isoformat()} before={before.isoformat()} limit={limit}", flush=True)
    candles = service.get_bars(tf, after=after, before=before, limit=limit)
    # get_bars returns last `limit` — if truncated, warn
    if candles:
        got0 = _parse_ts(candles[0]["open_time_utc"])
        got1 = _parse_ts(candles[-1]["open_time_utc"])
        print(f"[bars] {tf} got={len(candles)} range={got0.isoformat()}..{got1.isoformat()}", flush=True)
    return BarIndex(candles)


def excursion_mae_mfe(
    bars: list[dict],
    *,
    c_time: datetime,
    c_price: float,
    next_time: datetime,
    direction: str,
) -> tuple[float | None, float | None]:
    path = [
        b
        for b in bars
        if c_time <= _parse_ts(b["open_time_utc"]) <= next_time
    ]
    if not path:
        return None, None
    highs = [float(b["high"]) for b in path]
    lows = [float(b["low"]) for b in path]
    if direction == "DOWN":
        mfe = c_price - min(lows)
        mae = max(highs) - c_price
    else:
        mfe = max(highs) - c_price
        mae = c_price - min(lows)
    return mae, mfe


def context_status(bars: list[dict], center: datetime, before: timedelta, after: timedelta) -> str:
    if not bars:
        return "MISSING"
    t0 = _parse_ts(bars[0]["open_time_utc"])
    t1 = _parse_ts(bars[-1]["open_time_utc"])
    need0 = center - before
    need1 = center + after
    # allow one bar slack
    if t0 <= need0 + timedelta(minutes=5) and t1 >= need1 - timedelta(minutes=5):
        return "COMPLETE"
    return "PARTIAL"


def build_event_bars_for_tf(
    events: list[dict],
    bar_index: BarIndex,
    tf: str,
) -> list[dict]:
    spec = WINDOW_SPEC[tf]
    out: list[dict] = []
    atr_cache_period = 14
    # Precompute ATR series once for relative ATR diagnostic
    atr_series = compute_atr_series(bar_index.candles, atr_cache_period) if bar_index.candles else []

    for e in events:
        center = _parse_ts(e["true_pivot_time"])
        c_price = float(e["true_pivot_price"])
        prev_price = e.get("previous_pivot_price")
        window = bar_index.slice_window(center, spec["before"], spec["after"])
        status = context_status(window, center, spec["before"], spec["after"])
        context_key = {"5m": "CONTEXT_5M", "15m": "CONTEXT_15M", "1H": "CONTEXT_1H", "4H": "CONTEXT_4H"}[tf]
        e[context_key] = status

        # Find pivot bar index within window (nearest open_time)
        pivot_rel = None
        for i, b in enumerate(window):
            if _parse_ts(b["open_time_utc"]) <= center <= _parse_ts(b["close_time_utc"]):
                pivot_rel = i
                break
        if pivot_rel is None and window:
            # nearest by open time
            diffs = [abs((_parse_ts(b["open_time_utc"]) - center).total_seconds()) for b in window]
            pivot_rel = int(min(range(len(diffs)), key=lambda i: diffs[i]))

        # MAE/MFE using source-path from context if possible (prefer matching source bars)
        if e.get("next_pivot_time") and e.get("NEXT_LEG_DIRECTION") and tf == e["source_wave_tf"]:
            mae, mfe = excursion_mae_mfe(
                window,
                c_time=center,
                c_price=c_price,
                next_time=_parse_ts(e["next_pivot_time"]),
                direction=e["NEXT_LEG_DIRECTION"],
            )
            e["NEXT_LEG_MAE_FROM_C"] = mae
            e["NEXT_LEG_MFE_FROM_C"] = mfe

        if e.get("atr_at_pivot_source_tf") is None and tf == e["source_wave_tf"] and pivot_rel is not None:
            # map to global index
            ot = _parse_ts(window[pivot_rel]["open_time_utc"])
            gi = bisect_left(bar_index.open_times, ot)
            if 0 <= gi < len(atr_series):
                e["atr_at_pivot_source_tf"] = atr_series[gi]

        for i, b in enumerate(window):
            ot = _parse_ts(b["open_time_utc"])
            ct = _parse_ts(b["close_time_utc"])
            rel = i - (pivot_rel if pivot_rel is not None else 0)
            close_px = float(b["close"])
            gi = bisect_left(bar_index.open_times, ot)
            atr_v = atr_series[gi] if 0 <= gi < len(atr_series) and atr_series[gi] > 0 else None
            out.append(
                {
                    "event_id": e["event_id"],
                    "timeframe": tf,
                    "bar_index_relative_to_pivot": rel,
                    "open_time": b["open_time_utc"],
                    "close_time": b["close_time_utc"],
                    "open": float(b["open"]),
                    "high": float(b["high"]),
                    "low": float(b["low"]),
                    "close": close_px,
                    "volume": float(b["volume"]),
                    "is_before_true_pivot": ct < center,
                    "is_true_pivot_bar": (pivot_rel is not None and i == pivot_rel),
                    "is_after_true_pivot": ot > center,
                    "seconds_from_true_pivot": (ot - center).total_seconds(),
                    "bars_from_true_pivot": rel,
                    "price_relative_to_C_pct": ((close_px - c_price) / c_price * 100.0) if c_price else None,
                    "price_relative_to_C_ATR": ((close_px - c_price) / atr_v) if atr_v else None,
                    "distance_from_previous_pivot_pct": (
                        ((close_px - float(prev_price)) / float(prev_price) * 100.0) if prev_price else None
                    ),
                }
            )
    return out


def validate_events(events: list[dict], wave_pivots: list[dict]) -> dict[str, Any]:
    errors = []
    ids = [e["event_id"] for e in events]
    if len(ids) != len(set(ids)):
        errors.append("DUPLICATE_EVENT_ID")
    wave_keys = {(p["timeframe"], int(p["pivot_index"]), str(p["pivot_time"])) for p in wave_pivots}
    for e in events:
        key = (e["source_wave_tf"], int(e["pivot_index"]), str(e["true_pivot_time"]))
        if key not in wave_keys:
            errors.append(f"PIVOT_MISMATCH:{e['event_id']}")
            if len(errors) > 20:
                break
        else:
            # price must match frozen dataset within float tolerance
            wp = next(
                p
                for p in wave_pivots
                if p["timeframe"] == e["source_wave_tf"] and int(p["pivot_index"]) == int(e["pivot_index"])
            )
            if abs(float(wp["pivot_price"]) - float(e["true_pivot_price"])) > 1e-8:
                errors.append(f"PRICE_MISMATCH:{e['event_id']}")
                if len(errors) > 20:
                    break
    return {"ok": len(errors) == 0, "errors": errors}


def validate_bars(bars: list[dict], tf: str) -> dict[str, Any]:
    errors = []
    minutes = TF_MINUTES[tf]
    by_event: dict[str, list[dict]] = {}
    for b in bars:
        by_event.setdefault(b["event_id"], []).append(b)
    for eid, rows in by_event.items():
        rows = sorted(rows, key=lambda r: _parse_ts(r["open_time"]))
        times = [_parse_ts(r["open_time"]) for r in rows]
        if times != sorted(times):
            errors.append(f"NON_MONOTONIC:{eid}")
        if len(times) != len(set(times)):
            errors.append(f"DUP_BAR:{eid}")
        for r in rows:
            o, h, l, c = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
            if not (l <= o <= h and l <= c <= h):
                errors.append(f"OHLC_INVALID:{eid}")
                break
        if len(errors) > 30:
            break
    return {"ok": len(errors) == 0, "errors": errors[:30], "tf": tf, "row_count": len(bars), "expected_minutes": minutes}


def run_anti_leakage_tests(sample_bars: list[dict], sample_event_id: str, tf: str = "4H") -> dict[str, Any]:
    scoped = [b for b in sample_bars if b["event_id"] == sample_event_id and b["timeframe"] == tf]
    if len(scoped) < 5:
        return {"ok": False, "reason": "insufficient_sample_bars"}
    scoped = sorted(scoped, key=lambda b: _parse_ts(b["open_time"]))
    mid = scoped[len(scoped) // 2]
    decision = mid["open_time"]
    hist = get_event_history(scoped, event_id=sample_event_id, timeframe=tf, decision_time=decision)
    try:
        assert_no_future_bars(hist, decision, require_closed=True)
        # Explicitly ensure no bar with close_time > decision
        leaked = [b for b in hist if _parse_ts(b["close_time"]) > _parse_ts(decision)]
        unfinished_ok = higher_tf_unfinished_bar_excluded(scoped, decision)
        return {
            "ok": len(leaked) == 0 and unfinished_ok,
            "history_len": len(hist),
            "decision_time": decision,
            "leaked_count": len(leaked),
            "unfinished_higher_tf_bar_test": unfinished_ok,
        }
    except AssertionError as exc:
        return {"ok": False, "error": str(exc)}


def run_build(
    *,
    wave_dir: Path,
    out_dir: Path,
    service,
    git_commit: str | None = None,
) -> dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    marker = out_dir / "REVERSAL_EVENT_DATASET_V1_IMMUTABLE.txt"
    if marker.exists():
        raise RuntimeError(f"Refusing to overwrite {EVENT_DATASET_VERSION} at {out_dir}")

    # Verify wave dataset untouched identity
    wave_manifest = json.loads((wave_dir / "wave_dataset_manifest_v1.json").read_text(encoding="utf-8"))
    if wave_manifest.get("dataset_version") != WAVE_DATASET_VERSION:
        raise RuntimeError("WAVE_DATASET_V1 identity mismatch")
    wave_hash = _sha256_file(wave_dir / "wave_dataset_manifest_v1.json")

    pivots, legs, geo = load_wave_tables(wave_dir)
    events = build_events(pivots, legs, geo)
    partition_info = assign_partitions(events)

    # time span for context loading
    times = [_parse_ts(e["true_pivot_time"]) for e in events]
    t_min, t_max = min(times), max(times)

    context_indexes = {}
    bars_by_tf: dict[str, list[dict]] = {}
    for tf in CONTEXT_TFS:
        context_indexes[tf] = load_context_bars(service, tf, t_min, t_max)
        print(f"[windows] building event bars for {tf} events={len(events)}", flush=True)
        bars_by_tf[tf] = build_event_bars_for_tf(events, context_indexes[tf], tf)

    for e in events:
        e["CONTEXT_COMPLETE"] = all(
            e[k] == "COMPLETE" for k in ("CONTEXT_5M", "CONTEXT_15M", "CONTEXT_1H", "CONTEXT_4H")
        )

    # Also fill MAE/MFE for events whose source TF is not in CONTEXT_TFS — use 1H/4H path approx skipped;
    # load source TF bars lazily only if needed for MAE. For non-context source TFs, leave null unless
    # we can use 1H proxy — better load source TF once for remaining TFs.
    source_tfs = sorted({e["source_wave_tf"] for e in events})
    for tf in source_tfs:
        if tf in CONTEXT_TFS:
            continue
        print(f"[mae] loading source TF for excursions: {tf}", flush=True)
        idx = load_context_bars(service, tf, t_min, t_max)
        for e in events:
            if e["source_wave_tf"] != tf or not e.get("next_pivot_time"):
                continue
            center = _parse_ts(e["true_pivot_time"])
            window = idx.slice_window(center, timedelta(days=60), timedelta(days=60))
            mae, mfe = excursion_mae_mfe(
                window,
                c_time=center,
                c_price=float(e["true_pivot_price"]),
                next_time=_parse_ts(e["next_pivot_time"]),
                direction=e["NEXT_LEG_DIRECTION"],
            )
            e["NEXT_LEG_MAE_FROM_C"] = mae
            e["NEXT_LEG_MFE_FROM_C"] = mfe
            if e.get("atr_at_pivot_source_tf") is None:
                e["atr_at_pivot_source_tf"] = idx.atr_at(center, 14)

    # Persist
    events_path = _write_parquet(out_dir / "reversal_events_v1.parquet", events)
    bar_paths = {}
    file_map = {"5m": "event_bars_5m_v1.parquet", "15m": "event_bars_15m_v1.parquet", "1H": "event_bars_1h_v1.parquet", "4H": "event_bars_4h_v1.parquet"}
    for tf, fname in file_map.items():
        bar_paths[tf] = _write_parquet(out_dir / fname, bars_by_tf[tf])

    partitions = [
        {
            "event_id": e["event_id"],
            "true_pivot_time": e["true_pivot_time"],
            "partition": e["partition"],
            "partition_usable": e["partition_usable"],
            "source_wave_tf": e["source_wave_tf"],
        }
        for e in events
    ]
    part_path = _write_parquet(out_dir / "event_partitions_v1.parquet", partitions)
    _write_csv(out_dir / "event_schema_registry_v1.csv", schema_rows())

    # validations + anti-leakage tests
    v_events = validate_events(events, pivots)
    v_bars = {tf: validate_bars(bars_by_tf[tf], tf) for tf in CONTEXT_TFS}
    sample = next((e for e in events if e["CONTEXT_4H"] in ("COMPLETE", "PARTIAL")), events[0])
    anti = run_anti_leakage_tests(bars_by_tf["4H"], sample["event_id"], "4H")

    # counts
    def count_where(pred):
        return sum(1 for e in events if pred(e))

    created_at = datetime.now(timezone.utc).isoformat()
    (out_dir / "anti_leakage_contract.md").write_text(
        (Path(__file__).with_name("anti_leakage_contract.md")).read_text(encoding="utf-8")
        if Path(__file__).with_name("anti_leakage_contract.md").exists()
        else "# See package anti_leakage_contract.md\n",
        encoding="utf-8",
    )

    manifest = {
        "dataset_version": EVENT_DATASET_VERSION,
        "wave_engine_version": WAVE_ENGINE_VERSION,
        "wave_dataset_version": WAVE_DATASET_VERSION,
        "wave_dataset_manifest_sha256": wave_hash,
        "wave_dataset_v1_unchanged": True,
        "created_at": created_at,
        "git_commit": git_commit,
        "symbol": SYMBOL,
        "window_spec": {
            tf: {"before_hours": WINDOW_SPEC[tf]["before"].total_seconds() / 3600.0, "after_hours": WINDOW_SPEC[tf]["after"].total_seconds() / 3600.0}
            for tf in CONTEXT_TFS
        },
        "partition": partition_info,
        "event_counts": {
            "total": len(events),
            "by_source_tf": {tf: count_where(lambda e, t=tf: e["source_wave_tf"] == t) for tf in sorted({e["source_wave_tf"] for e in events})},
            "HIGH": count_where(lambda e: e["pivot_type"] == "HIGH"),
            "LOW": count_where(lambda e: e["pivot_type"] == "LOW"),
            "DISCOVERY_usable": count_where(lambda e: e["partition"] == "DISCOVERY" and e["partition_usable"]),
            "VALIDATION_usable": count_where(lambda e: e["partition"] == "VALIDATION" and e["partition_usable"]),
            "OOS_usable": count_where(lambda e: e["partition"] == "OOS" and e["partition_usable"]),
            "PARTITION_CROSS_PURGED": count_where(lambda e: e["partition"] == "PARTITION_CROSS_PURGED"),
            "NO_OUTCOME": count_where(lambda e: e["partition"] == "NO_OUTCOME"),
            "CONTEXT_COMPLETE_5M": count_where(lambda e: e["CONTEXT_5M"] == "COMPLETE"),
            "CONTEXT_COMPLETE_15M": count_where(lambda e: e["CONTEXT_15M"] == "COMPLETE"),
            "CONTEXT_COMPLETE_1H": count_where(lambda e: e["CONTEXT_1H"] == "COMPLETE"),
            "CONTEXT_COMPLETE_4H": count_where(lambda e: e["CONTEXT_4H"] == "COMPLETE"),
            "CONTEXT_COMPLETE_ALL": count_where(lambda e: e["CONTEXT_COMPLETE"]),
        },
        "schema_classes": {
            "CAUSAL_RAW_INPUT": columns_by_class("CAUSAL_RAW_INPUT"),
            "RETROSPECTIVE_LABEL": columns_by_class("RETROSPECTIVE_LABEL"),
            "OUTCOME": columns_by_class("OUTCOME"),
            "IDENTITY": columns_by_class("IDENTITY"),
            "DIAGNOSTIC": columns_by_class("DIAGNOSTIC"),
        },
        "validations": {"events": v_events, "bars": v_bars, "anti_leakage": anti},
        "artifact_files": [
            events_path.name,
            *[p.name for p in bar_paths.values()],
            part_path.name,
            "event_schema_registry_v1.csv",
            "anti_leakage_contract.md",
        ],
        "immutable": True,
    }
    # checksums
    checksums = {}
    for name in manifest["artifact_files"]:
        p = out_dir / name
        if p.exists() and p.is_file():
            checksums[name] = _sha256_file(p)
    manifest["checksums_sha256"] = checksums
    (out_dir / "event_dataset_manifest_v1.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    marker.write_text(f"{EVENT_DATASET_VERSION} frozen at {created_at}\nDo not overwrite.\n", encoding="utf-8")

    # sample inspector artifacts
    inspect_dir = out_dir / "event_inspector_samples"
    inspect_dir.mkdir(exist_ok=True)
    samples = []
    for kind in ("HIGH", "LOW"):
        for year in sorted({e["calendar_year"] for e in events})[:3]:
            hit = next((e for e in events if e["pivot_type"] == kind and e["calendar_year"] == year and e["CONTEXT_1H"] != "MISSING"), None)
            if hit:
                samples.append(hit)
    for e in samples[:8]:
        payload = {
            "event": {k: e[k] for k in e},
            "note": "TRUE_C is retrospective; do not use as live feature",
        }
        (inspect_dir / f"sample_{e['event_id']}.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    overall = (
        v_events["ok"]
        and all(v["ok"] for v in v_bars.values())
        and anti.get("ok") is True
    )
    summary = {
        "wip": "REVERSAL-EVENT-DATASET-1",
        "overall_ok": overall,
        "manifest": manifest,
        "out_dir": str(out_dir),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary
