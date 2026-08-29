#!/usr/bin/env python3
"""Visual/sanity: regenerate WAVE_ENGINE_V1 pivots for sample TFs and dump overlay JSON."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from crypto_trading_bot.research_v2.market_data import TimeframeBarService
from crypto_trading_bot.research_v2.resampling import TIMEFRAMES
from crypto_trading_bot.research_v2.wave_engine.v1_config import CONFIG_BY_TF, QUALITY_FLAG_BY_TF
from crypto_trading_bot.research_v2.zigzag.classic import classic_atr_zigzag, compute_atr_series

SAMPLE_TFS = ("5m", "1H", "2H", "4H", "6H", "1D")


def main() -> int:
    out = Path("/var/tmp/traiding_pilot_ui_workspace/wave_dataset_v1/sanity_overlays")
    out.mkdir(parents=True, exist_ok=True)
    end = datetime.fromisoformat("2024-06-30").replace(tzinfo=timezone.utc)
    service = TimeframeBarService(
        symbol="ETHUSDT",
        canonical_root=Path("/srv/traiding_pilot/market/binance/spot/ETHUSDT/1m"),
        cache_root=Path("/var/tmp/traiding_pilot_market_cache"),
        ssh_host="wanga@10.8.0.7",
        ssh_key=Path("/home/sergey/.ssh/id_to_nyx"),
    )
    report = {}
    for tf in SAMPLE_TFS:
        cfg = CONFIG_BY_TF[tf]
        minutes = TIMEFRAMES[tf]
        # ~120 days window for overlay density
        limit = min(8000, int(120 * 24 * 60 / minutes) + 50)
        candles = service.get_bars(tf, before=end, limit=max(limit, 400))
        atr = compute_atr_series(candles, int(cfg["atr_n"]))
        pivots = classic_atr_zigzag(
            candles,
            atr_mult=float(cfg["atr_k"]),
            depth=int(cfg["depth"]),
            backstep=int(cfg["backstep"]),
            atr_period=int(cfg["atr_n"]),
            atr_series=atr,
        )
        payload = {
            "tf": tf,
            "config": cfg,
            "quality_flag": QUALITY_FLAG_BY_TF[tf],
            "candle_count": len(candles),
            "pivot_count": len(pivots),
            "sample_from": candles[0]["open_time_utc"] if candles else None,
            "sample_to": candles[-1]["open_time_utc"] if candles else None,
            "pivots": [
                {
                    "index": p.index,
                    "time": p.timestamp,
                    "price": float(p.price),
                    "kind": p.kind,
                    "confirmation_time": p.confirmation_timestamp,
                }
                for p in pivots
            ],
        }
        path = out / f"overlay_{tf}.json"
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        report[tf] = {
            "pivots": len(pivots),
            "candles": len(candles),
            "quality_flag": QUALITY_FLAG_BY_TF[tf],
            "path": str(path),
        }
        print(f"[sanity] {tf} pivots={len(pivots)} candles={len(candles)}", flush=True)
    (out / "sanity_summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
