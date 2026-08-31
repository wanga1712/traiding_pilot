"""Real-data gap audit for canonical historical bars on S13 or local store."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq

from crypto_trading_bot.research_v2.indicator_engine.bars import bars_to_arrays
from crypto_trading_bot.research_v2.indicator_engine.segments import iter_segments
from crypto_trading_bot.research_v2.indicator_engine.volatility import compute_atr_series
from crypto_trading_bot.research_v2.indicator_engine.macd import compute_macd_series
from crypto_trading_bot.research_v2.indicator_engine.dinapoli_macd import compute_dinapoli_macd_series
from crypto_trading_bot.research_v2.multitf_feature_bank.ma_features import compute_dma_feature_series
from crypto_trading_bot.research_v2.multitf_feature_bank.stoch_features import compute_dinapoli_stoch_feature_series
from crypto_trading_bot.research_v2.resampling import UI_TIMEFRAMES

CACHE_ROOT = Path("/var/tmp/traiding_pilot_market_cache/resampled")
SYMBOL = "ETHUSDT"
MAX_BARS_PER_TF = 5000


def _normalize_bar(row: dict) -> dict:
    open_time = row.get("open_time") or row.get("open_time_utc")
    close_time = row.get("close_time") or row.get("close_time_utc")
    if hasattr(open_time, "isoformat"):
        open_time = open_time.isoformat()
    if hasattr(close_time, "isoformat"):
        close_time = close_time.isoformat()
    return {
        "open_time": str(open_time).replace("+00:00", "Z") if "Z" not in str(open_time) else str(open_time),
        "close_time": str(close_time).replace("+00:00", "Z") if "Z" not in str(close_time) else str(close_time),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": float(row.get("volume", 0.0)),
    }


def _load_bars_from_cache(tf: str) -> list[dict] | None:
    path = CACHE_ROOT / f"{SYMBOL}_{tf}.parquet"
    if not path.is_file():
        return None
    table = pq.read_table(path)
    rows = table.to_pylist()
    if not rows:
        return None
    if len(rows) > MAX_BARS_PER_TF:
        rows = rows[-MAX_BARS_PER_TF:]
    return [_normalize_bar(r) for r in rows]


def _load_bars(tf: str) -> list[dict] | None:
    cached = _load_bars_from_cache(tf)
    if cached:
        return cached
    try:
        from crypto_trading_bot.research_v2.market_data.bars_service import TimeframeBarService

        svc = TimeframeBarService()
        end = datetime.now(timezone.utc)
        start = end.replace(year=end.year - 1)
        raw = svc.get_bars(tf, after=start, before=end, limit=20_000)
        if not raw:
            return None
        return [_normalize_bar(r) for r in raw]
    except Exception:
        return None


def _audit_tf(tf: str, bars: list[dict]) -> dict:
    arrays = bars_to_arrays(bars, timeframe=tf)
    gap_count = int(arrays.gap_flags.sum())
    families = {
        "EMA_DMA": compute_dma_feature_series(arrays, ma_type="EMA", period=7, display_shift=0),
        "STANDARD_MACD": compute_macd_series(arrays, fast=12, slow=26, signal=9),
        "DINAPOLI_MACD": compute_dinapoli_macd_series(arrays),
        "DINAPOLI_STOCH": compute_dinapoli_stoch_feature_series(arrays),
        "ATR": compute_atr_series(arrays, period=14),
    }
    out: dict = {"timeframe": tf, "bar_count": len(bars), "gap_count": gap_count, "families": {}}
    for name, series in families.items():
        invalid_gap = 0
        recovered = 0
        permanent = 0
        for start, end in iter_segments(arrays.gap_flags, len(bars)):
            if start == 0:
                continue
            seg_invalid = [
                i
                for i in range(start, end + 1)
                if not series[i].valid and series[i].invalid_reason != "warmup"
            ]
            invalid_gap += len(seg_invalid)
            tail_valid = any(series[i].valid for i in range(max(start, end - 5), end + 1))
            if tail_valid and (end - start + 1) > 20:
                recovered += 1
            elif (end - start + 1) > 20:
                permanent += 1
        out["families"][name] = {
            "invalid_due_to_gap_count": invalid_gap,
            "recovered_after_gap_count": recovered,
            "permanent_invalid_after_gap_count": permanent,
        }
    return out


def run_gap_audit() -> dict:
    report: dict = {"timeframes": [], "permanent_invalid_after_recoverable_gap_count": 0}
    for tf in UI_TIMEFRAMES:
        bars = _load_bars(tf)
        if not bars:
            report["timeframes"].append({"timeframe": tf, "bar_count": 0, "gap_count": 0, "status": "NO_DATA"})
            continue
        entry = _audit_tf(tf, bars)
        report["timeframes"].append(entry)
        for fam in entry.get("families", {}).values():
            report["permanent_invalid_after_recoverable_gap_count"] += fam.get("permanent_invalid_after_gap_count", 0)
    return report


def main() -> int:
    report = run_gap_audit()
    root = Path(__file__).resolve().parents[4] / "artifacts" / "MULTITF-DISPLACED-INDICATOR-AND-GEOMETRY-BANK-1"
    root.mkdir(parents=True, exist_ok=True)
    (root / "real_data_gap_audit_v1.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
