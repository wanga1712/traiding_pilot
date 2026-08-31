"""Research-only visual audit chart for oscillator predictor."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "phase3_staging"))

from crypto_trading_bot.research_v2.indicator_engine.bars import bars_to_arrays
from crypto_trading_bot.research_v2.oscillator_predictor.dno import compute_dno_series
from crypto_trading_bot.research_v2.oscillator_predictor.dynamic_predictor import DEFAULT_PREDICTOR_CONFIG, compute_predictor_feature_series
from crypto_trading_bot.research_v2.oscillator_predictor.peaks import confirmed_extrema_at

ART = ROOT / "artifacts" / "OSCILLATOR-PREDICTOR-REFERENCE-1" / "visual_audit"


def _synthetic_bars(n: int = 200) -> list[dict]:
    base = datetime(2024, 6, 1, tzinfo=timezone.utc)
    bars = []
    for i in range(n):
        c = 3000 + np.sin(i / 12) * 80 + i * 0.3
        t = base + timedelta(hours=i)
        bars.append(
            {
                "open_time": t,
                "close_time": t,
                "open": c,
                "high": c + 5,
                "low": c - 5,
                "close": c,
                "volume": 1.0,
                "timeframe": "1H",
            }
        )
    return bars


def export_window(name: str, bars: list[dict], start: int, end: int) -> None:
    sub = bars[start:end]
    arrays = bars_to_arrays(sub, timeframe="1H")
    dno, _ = compute_dno_series(arrays, period=7)
    cfg = DEFAULT_PREDICTOR_CONFIG
    preds = compute_predictor_feature_series(arrays, config=cfg)
    peaks_all: list[dict] = []
    troughs_all: list[dict] = []
    for i in range(len(sub)):
        peaks, troughs = confirmed_extrema_at(
            dno, arrays.gap_flags, i, peak_strength=cfg.peak_strength, lookback=cfg.lookback
        )
        if peaks:
            peaks_all.append({"index": i, "peaks": [{"idx": p.index, "value": p.value} for p in peaks]})
        if troughs:
            troughs_all.append({"index": i, "troughs": [{"idx": t.index, "value": t.value} for t in troughs]})
    payload = {
        "window": name,
        "bars": [{"i": j, "close": float(b["close"])} for j, b in enumerate(sub)],
        "dno": [None if np.isnan(x) else float(x) for x in dno],
        "predictor": preds[-1] if preds else {},
        "final_peaks": peaks_all[-1] if peaks_all else {},
        "final_troughs": troughs_all[-1] if troughs_all else {},
    }
    ART.mkdir(parents=True, exist_ok=True)
    (ART / f"{name}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    bars = _synthetic_bars(200)
    export_window("sample_trend_up", bars, 50, 120)
    export_window("sample_oscillation", bars, 20, 100)
    export_window("sample_late_window", bars, 120, 200)
    print("visual audit exported to", ART)


if __name__ == "__main__":
    main()
