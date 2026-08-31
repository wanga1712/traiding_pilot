"""Full-history gap audit — complete canonical resampled dataset, no tail limit."""
from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq

from crypto_trading_bot.research_v2.indicator_engine.bars import BarArrays, bars_to_arrays, contiguous_ok
from crypto_trading_bot.research_v2.indicator_engine.dinapoli_macd import compute_dinapoli_macd_arrays
from crypto_trading_bot.research_v2.indicator_engine.dinapoli_stochastic import (
    compute_dinapoli_stoch_arrays,
    dinapoli_stoch_warmup_indices,
)
from crypto_trading_bot.research_v2.indicator_engine.macd import _signal_ema_segmented
from crypto_trading_bot.research_v2.indicator_engine.math_core import ema, rma, true_range
from crypto_trading_bot.research_v2.indicator_engine.segments import iter_segments, same_segment
from crypto_trading_bot.research_v2.multitf_feature_bank.warmup import (
    dinapoli_macd_warmup_bars,
    dinapoli_stoch_warmup_bars,
    dma_warmup_bars,
    standard_macd_warmup_bars,
)
from crypto_trading_bot.research_v2.resampling import UI_TIMEFRAMES

CACHE_ROOT = Path("/var/tmp/traiding_pilot_market_cache/resampled")
SYMBOL = "ETHUSDT"
WIP = "MULTITF-DISPLACED-INDICATOR-AND-GEOMETRY-BANK-1"
ATR_PERIOD = 14
EMA_PERIOD = 7
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9

FAMILY_WARMUP: dict[str, int] = {
    "EMA_DMA": dma_warmup_bars(period=EMA_PERIOD, display_shift=0),
    "STANDARD_MACD": standard_macd_warmup_bars(slow=MACD_SLOW, signal=MACD_SIGNAL, display_shift=0),
    "DINAPOLI_MACD": dinapoli_macd_warmup_bars(display_shift=0),
    "DINAPOLI_PREFERRED_STOCH": dinapoli_stoch_warmup_bars(
        k_period=8, slowing=3, d_period=3, display_shift=0
    ),
    "ATR": ATR_PERIOD,
}


@dataclass
class ValiditySeries:
    valid: np.ndarray
    invalid_reason: list[str]
    values: np.ndarray


@dataclass
class SegmentOutcome:
    invalid_due_to_gap: int = 0
    recovered: int = 0
    permanent_invalid: int = 0
    insufficient_history: int = 0


def _normalize_bar(row: dict) -> dict:
    open_time = row.get("open_time") or row.get("open_time_utc")
    close_time = row.get("close_time") or row.get("close_time_utc")
    if hasattr(open_time, "isoformat"):
        open_time = open_time.isoformat()
    if hasattr(close_time, "isoformat"):
        close_time = close_time.isoformat()
    ot = str(open_time).replace("+00:00", "Z")
    ct = str(close_time).replace("+00:00", "Z")
    if "Z" not in ot and "+" not in ot:
        ot += "Z"
    if "Z" not in ct and "+" not in ct:
        ct += "Z"
    return {
        "open_time": ot,
        "close_time": ct,
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": float(row.get("volume", 0.0)),
    }


def load_full_bars(tf: str) -> list[dict] | None:
    path = CACHE_ROOT / f"{SYMBOL}_{tf}.parquet"
    if not path.is_file():
        return None
    rows = pq.read_table(path).to_pylist()
    if not rows:
        return None
    return [_normalize_bar(r) for r in rows]


def _segment_starts_array(gap_flags: np.ndarray) -> np.ndarray:
    """O(n) segment start index for every bar — audit-only helper."""
    n = len(gap_flags)
    starts = np.zeros(n, dtype=int)
    cur = 0
    for i in range(n):
        if i > 0 and gap_flags[i]:
            cur = i
        starts[i] = cur
    return starts


def _validity_ema_dma(arrays: BarArrays) -> ValiditySeries:
    n = len(arrays.close)
    gf = arrays.gap_flags
    ma = ema(arrays.close, EMA_PERIOD, gap_flags=gf)
    valid = np.zeros(n, dtype=bool)
    reasons = ["warmup"] * n
    for i in range(n):
        if i < EMA_PERIOD - 1 or np.isnan(ma[i]):
            continue
        if contiguous_ok(gf, i - EMA_PERIOD + 1, i):
            valid[i] = True
            reasons[i] = ""
        else:
            reasons[i] = "insufficient_contiguous_history"
    return ValiditySeries(valid, reasons, ma)


def _validity_standard_macd(arrays: BarArrays) -> ValiditySeries:
    n = len(arrays.close)
    gf = arrays.gap_flags
    seg_starts = _segment_starts_array(gf)
    fast_e = ema(arrays.close, MACD_FAST, gap_flags=gf)
    slow_e = ema(arrays.close, MACD_SLOW, gap_flags=gf)
    macd_line = fast_e - slow_e
    signal_line = _signal_ema_segmented(macd_line, MACD_SIGNAL, gf)
    warmup = MACD_SLOW + MACD_SIGNAL - 1
    valid = np.zeros(n, dtype=bool)
    reasons = ["warmup"] * n
    for i in range(n):
        seg_start = int(seg_starts[i])
        if i - seg_start + 1 < warmup or np.isnan(macd_line[i]) or np.isnan(signal_line[i]):
            continue
        if not same_segment(gf, i - 1, i) or not contiguous_ok(gf, seg_start, i):
            reasons[i] = "insufficient_contiguous_history"
            continue
        valid[i] = True
        reasons[i] = ""
    return ValiditySeries(valid, reasons, macd_line)


def _validity_dinapoli_macd(arrays: BarArrays) -> ValiditySeries:
    n = len(arrays.close)
    gf = arrays.gap_flags
    seg_starts = _segment_starts_array(gf)
    macd_line, signal_line, _ = compute_dinapoli_macd_arrays(arrays.close, gap_flags=gf)
    valid = np.zeros(n, dtype=bool)
    reasons = ["warmup"] * n
    for i in range(n):
        seg_start = int(seg_starts[i])
        if i - seg_start < 1 or np.isnan(macd_line[i]) or np.isnan(signal_line[i]):
            continue
        if not same_segment(gf, i - 1, i) or not contiguous_ok(gf, seg_start, i):
            reasons[i] = "insufficient_contiguous_history"
            continue
        valid[i] = True
        reasons[i] = ""
    return ValiditySeries(valid, reasons, macd_line)


def _validity_dinapoli_stoch(arrays: BarArrays) -> ValiditySeries:
    n = len(arrays.close)
    gf = arrays.gap_flags
    seg_starts = _segment_starts_array(gf)
    _, k, d = compute_dinapoli_stoch_arrays(
        arrays.high, arrays.low, arrays.close, gap_flags=gf
    )
    first_full = dinapoli_stoch_warmup_indices()["first_full_feature_index"]
    valid = np.zeros(n, dtype=bool)
    reasons = ["warmup"] * n
    for i in range(n):
        if i < first_full or np.isnan(k[i]) or np.isnan(d[i]):
            continue
        if i > 0 and not same_segment(gf, i - 1, i):
            reasons[i] = "insufficient_contiguous_history"
            continue
        if not contiguous_ok(gf, int(seg_starts[i]), i):
            reasons[i] = "insufficient_contiguous_history"
            continue
        valid[i] = True
        reasons[i] = ""
    return ValiditySeries(valid, reasons, k)


def _validity_atr(arrays: BarArrays) -> ValiditySeries:
    n = len(arrays.close)
    gf = arrays.gap_flags
    seg_starts = _segment_starts_array(gf)
    tr = true_range(arrays.high, arrays.low, arrays.close, gap_flags=gf)
    atr = rma(tr, ATR_PERIOD, gap_flags=gf)
    valid = np.zeros(n, dtype=bool)
    reasons = ["warmup"] * n
    for i in range(n):
        seg_start = int(seg_starts[i])
        if i - seg_start + 1 < ATR_PERIOD or np.isnan(atr[i]):
            continue
        if not contiguous_ok(gf, seg_start, i):
            reasons[i] = "insufficient_contiguous_history"
            continue
        valid[i] = True
        reasons[i] = ""
    return ValiditySeries(valid, reasons, atr)


def _compute_validity(arrays: BarArrays) -> dict[str, ValiditySeries]:
    return {
        "EMA_DMA": _validity_ema_dma(arrays),
        "STANDARD_MACD": _validity_standard_macd(arrays),
        "DINAPOLI_MACD": _validity_dinapoli_macd(arrays),
        "DINAPOLI_PREFERRED_STOCH": _validity_dinapoli_stoch(arrays),
        "ATR": _validity_atr(arrays),
    }


def _classify_post_gap_segments(
    gap_flags: np.ndarray,
    n: int,
    vs: ValiditySeries,
    warmup_bars: int,
) -> SegmentOutcome:
    out = SegmentOutcome()
    for start, end in iter_segments(gap_flags, n):
        if start == 0:
            continue
        seg_len = end - start + 1
        first_mature = start + warmup_bars - 1
        for i in range(start, end + 1):
            if not vs.valid[i] and vs.invalid_reason[i] != "warmup":
                out.invalid_due_to_gap += 1
        if first_mature > end:
            out.insufficient_history += 1
            continue
        if np.any(vs.valid[first_mature : end + 1]):
            out.recovered += 1
        elif seg_len >= warmup_bars:
            out.permanent_invalid += 1
        else:
            out.insufficient_history += 1
    return out


def _mutate_segment_a(bars: list[dict], seg_a_end: int) -> list[dict]:
    out = [dict(b) for b in bars]
    for i in range(seg_a_end + 1):
        out[i]["open"] *= 1000.0
        out[i]["high"] *= 1000.0
        out[i]["low"] *= 1000.0
        out[i]["close"] *= 1000.0
    return out


def _check_real_gap_segment_independence(tf: str, bars: list[dict], gap_flags: np.ndarray) -> tuple[bool, list[dict]]:
    from crypto_trading_bot.research_v2.indicator_engine.segments import segment_starts

    starts = segment_starts(gap_flags)
    candidates: list[tuple[int, int, int]] = []
    n = len(bars)
    for si, start in enumerate(starts):
        if start == 0:
            continue
        end = (starts[si + 1] - 1) if si + 1 < len(starts) else (n - 1)
        seg_len = end - start + 1
        if seg_len >= max(FAMILY_WARMUP.values()) + 5:
            candidates.append((start, end, seg_len))
    if not candidates:
        return True, []

    candidates.sort(key=lambda x: x[2])
    picks = [candidates[0]]
    if len(candidates) > 2:
        picks.append(candidates[len(candidates) // 2])
    if len(candidates) > 1:
        picks.append(candidates[-1])
    seen: set[int] = set()
    picks = [p for p in picks if p[0] not in seen and not seen.add(p[0])]

    checks: list[dict] = []
    ok = True
    warmup_max = max(FAMILY_WARMUP.values())
    for start, end, seg_len in picks[:5]:
        check_i = min(end, start + warmup_max + 10)
        win_start = max(0, start - warmup_max - 5)
        slice_bars = bars[win_start : end + 1]
        rel_check = check_i - win_start
        base = _compute_validity(bars_to_arrays(slice_bars, timeframe=tf))
        mut = _compute_validity(bars_to_arrays(_mutate_segment_a(slice_bars, start - win_start - 1), timeframe=tf))
        row: dict[str, Any] = {"timeframe": tf, "gap_index": start, "segment_b_length": seg_len, "check_index": check_i}
        for fam in FAMILY_WARMUP:
            bv = float(base[fam].values[rel_check]) if base[fam].valid[rel_check] else None
            mv = float(mut[fam].values[rel_check]) if mut[fam].valid[rel_check] else None
            match = bv is not None and mv is not None and abs(bv - mv) < 1e-6
            row[fam] = "PASS" if match else f"FAIL base={bv} mut={mv}"
            if not match:
                ok = False
        checks.append(row)
    return ok, checks


def _check_real_gap_atr_boundary(arrays: BarArrays) -> tuple[bool, int, int]:
    tr = true_range(arrays.high, arrays.low, arrays.close, gap_flags=arrays.gap_flags)
    gap_indices = [i for i in range(1, len(arrays.close)) if arrays.gap_flags[i]]
    if not gap_indices:
        return True, 0, 0
    passed = sum(
        1
        for i in gap_indices
        if abs(float(tr[i]) - float(arrays.high[i] - arrays.low[i])) < 1e-9
    )
    return passed == len(gap_indices), passed, len(gap_indices)


def audit_timeframe(tf: str) -> dict[str, Any]:
    print(f"AUDIT_TF {tf} load...", file=sys.stderr, flush=True)
    bars = load_full_bars(tf)
    if not bars:
        return {"timeframe": tf, "status": "NO_DATA"}
    arrays = bars_to_arrays(bars, timeframe=tf)
    n = len(bars)
    from crypto_trading_bot.research_v2.indicator_engine.segments import segment_starts

    gap_count = int(arrays.gap_flags.sum())
    segment_count = len(segment_starts(arrays.gap_flags))
    print(f"AUDIT_TF {tf} compute validity n={n} gaps={gap_count}...", file=sys.stderr, flush=True)
    validity = _compute_validity(arrays)
    fam_stats: dict[str, dict] = {}
    for fam, vs in validity.items():
        outcome = _classify_post_gap_segments(arrays.gap_flags, n, vs, FAMILY_WARMUP[fam])
        fam_stats[fam] = {
            "invalid_due_to_gap_count": outcome.invalid_due_to_gap,
            "recovered_after_gap_count": outcome.recovered,
            "permanent_invalid_after_recoverable_gap_count": outcome.permanent_invalid,
            "insufficient_post_gap_history_count": outcome.insufficient_history,
        }
    print(f"AUDIT_TF {tf} done", file=sys.stderr, flush=True)
    return {
        "timeframe": tf,
        "first_bar_time": bars[0]["open_time"],
        "last_bar_time": bars[-1]["open_time"],
        "bar_count": n,
        "gap_count": gap_count,
        "segment_count": segment_count,
        "families": fam_stats,
        "arrays": arrays,
        "bars": bars,
    }


def run_full_history_audit() -> dict[str, Any]:
    tf_results: list[dict] = []
    independence_checks: list[dict] = []
    atr_boundary_ok = True
    atr_boundary_detail: list[dict] = []
    totals = {
        "bar_count": 0,
        "gap_count": 0,
        "segment_count": 0,
        "insufficient_post_gap_history_count": 0,
        "permanent_invalid_after_recoverable_gap_count": 0,
    }
    family_totals = {fam: {"recoverable_gaps": 0, "recovered": 0, "permanent_invalid": 0} for fam in FAMILY_WARMUP}
    first_times: list[str] = []
    last_times: list[str] = []

    for tf in UI_TIMEFRAMES:
        entry = audit_timeframe(tf)
        if entry.get("status") == "NO_DATA":
            tf_results.append({"timeframe": tf, "status": "NO_DATA"})
            continue
        first_times.append(entry["first_bar_time"])
        last_times.append(entry["last_bar_time"])
        totals["bar_count"] += entry["bar_count"]
        totals["gap_count"] += entry["gap_count"]
        totals["segment_count"] += entry["segment_count"]

        if entry["gap_count"] > 0:
            _, seg_checks = _check_real_gap_segment_independence(tf, entry["bars"], entry["arrays"].gap_flags)
            independence_checks.extend(seg_checks)

        atr_ok, atr_pass, atr_total = _check_real_gap_atr_boundary(entry["arrays"])
        atr_boundary_detail.append({"timeframe": tf, "passed": atr_pass, "total": atr_total})
        if not atr_ok and atr_total > 0:
            atr_boundary_ok = False

        tf_results.append({k: v for k, v in entry.items() if k not in ("arrays", "bars")})

        for fam, stats in entry["families"].items():
            totals["insufficient_post_gap_history_count"] += stats["insufficient_post_gap_history_count"]
            totals["permanent_invalid_after_recoverable_gap_count"] += stats[
                "permanent_invalid_after_recoverable_gap_count"
            ]
            family_totals[fam]["recovered"] += stats["recovered_after_gap_count"]
            family_totals[fam]["permanent_invalid"] += stats["permanent_invalid_after_recoverable_gap_count"]
            family_totals[fam]["recoverable_gaps"] += (
                stats["recovered_after_gap_count"] + stats["permanent_invalid_after_recoverable_gap_count"]
            )

    segment_independence_ok = all(
        all(v == "PASS" for k, v in row.items() if k in FAMILY_WARMUP) for row in independence_checks
    ) if independence_checks else True

    return {
        "audit_source": str(CACHE_ROOT),
        "audit_scope": "full_history_no_tail_limit",
        "timeframes": tf_results,
        "totals": totals,
        "family_totals": family_totals,
        "real_gap_segment_independence": "PASS" if segment_independence_ok else "FAIL",
        "real_gap_segment_independence_checks": independence_checks,
        "real_gap_atr_boundary": "PASS" if atr_boundary_ok else "FAIL",
        "real_gap_atr_boundary_detail": atr_boundary_detail,
        "full_history_first_time": min(first_times) if first_times else None,
        "full_history_last_time": max(last_times) if last_times else None,
    }


def write_artifacts(report: dict[str, Any], root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    csv_path = root / "full_history_gap_audit_v1.csv"
    json_path = root / "full_history_gap_audit_summary_v1.json"

    fieldnames = [
        "timeframe",
        "family",
        "first_bar_time",
        "last_bar_time",
        "bar_count",
        "gap_count",
        "segment_count",
        "invalid_due_to_gap_count",
        "recovered_after_gap_count",
        "permanent_invalid_after_recoverable_gap_count",
        "insufficient_post_gap_history_count",
    ]
    rows: list[dict] = []
    for tf_entry in report["timeframes"]:
        if tf_entry.get("status") == "NO_DATA":
            rows.append(
                {
                    "timeframe": tf_entry["timeframe"],
                    "family": "ALL",
                    "first_bar_time": "",
                    "last_bar_time": "",
                    "bar_count": 0,
                    "gap_count": 0,
                    "segment_count": 0,
                    "invalid_due_to_gap_count": 0,
                    "recovered_after_gap_count": 0,
                    "permanent_invalid_after_recoverable_gap_count": 0,
                    "insufficient_post_gap_history_count": 0,
                }
            )
            continue
        for fam, stats in tf_entry.get("families", {}).items():
            rows.append(
                {
                    "timeframe": tf_entry["timeframe"],
                    "family": fam,
                    "first_bar_time": tf_entry["first_bar_time"],
                    "last_bar_time": tf_entry["last_bar_time"],
                    "bar_count": tf_entry["bar_count"],
                    "gap_count": tf_entry["gap_count"],
                    "segment_count": tf_entry["segment_count"],
                    **stats,
                }
            )

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def _artifact_root() -> Path:
    here = Path(__file__).resolve()
    staging = here
    while staging.name != "phase3_staging" and staging.parent != staging:
        staging = staging.parent
    repo_root = staging.parent if staging.name == "phase3_staging" else here.parents[4]
    return repo_root / "artifacts" / WIP


def main() -> int:
    report = run_full_history_audit()
    root = _artifact_root()
    write_artifacts(report, root)
    print(json.dumps({k: v for k, v in report.items() if k not in ("timeframes",)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
