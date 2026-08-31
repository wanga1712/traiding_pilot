"""Research-only visual audit using S7 canonical ETHUSDT history via S13 cache."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

from crypto_trading_bot.research_v2.indicator_engine.bars import bars_to_arrays, parse_ts
from crypto_trading_bot.research_v2.indicator_engine.volatility import compute_atr_series
from crypto_trading_bot.research_v2.market_data.research_access import (
    CANONICAL_HOST,
    CANONICAL_SOURCE_PATH,
    make_research_bar_service,
)
from crypto_trading_bot.research_v2.reversal_signal_study.bar_io import normalize_bar

from .dno import compute_masked_dno_series
from .config import DEFAULT_PREDICTOR_CONFIG
from .dynamic_predictor import compute_predictor_feature_series
from .peaks import confirmed_extrema_at
from .version import WIP_ID

REPO_ROOT = Path(__file__).resolve().parents[4]
ART = REPO_ROOT / "artifacts" / WIP_ID / "visual_audit"

WINDOWS = (
    ("eth_2023_spring", 1_678_800_000_000),
    ("eth_2024_volatility", 1_710_000_000_000),
    ("eth_2025_recent", 1_735_000_000_000),
)


def fetch_ethusdt_1h_from_canonical(start_ms: int, limit: int = 240) -> list[dict[str, Any]]:
    """Load 1H bars from S7 canonical store — no direct exchange HTTP."""
    start = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
    end = start + timedelta(hours=limit + 2)
    service = make_research_bar_service()
    raw = service.get_bars("1H", after=start - timedelta(hours=48), before=end, limit=limit + 100)
    bars = [normalize_bar(r) for r in raw]
    out = []
    for b in bars:
        ct = parse_ts(b["close_time"])
        if ct.tzinfo is None:
            ct = ct.replace(tzinfo=timezone.utc)
        if ct >= start and len(out) < limit:
            b["timeframe"] = "1H"
            out.append(b)
    if not out:
        raise RuntimeError(
            f"No 1H bars from {CANONICAL_HOST}:{CANONICAL_SOURCE_PATH} for window starting {start.isoformat()}"
        )
    return out[:limit]


def _html_chart(payload: dict[str, Any], title: str) -> str:
    data_json = json.dumps(payload)
    return f"""<!DOCTYPE html>
<html><head><meta charset='utf-8'><title>{title}</title>
<style>body{{font-family:sans-serif;margin:16px}}canvas{{border:1px solid #ccc;max-width:100%}}</style>
</head><body>
<h2>{title}</h2>
<p>Research-only audit — ETHUSDT 1H from S7 canonical market data via S13 disposable cache.</p>
<canvas id='c' width='1200' height='700'></canvas>
<script>
const D = {data_json};
const c = document.getElementById('c');
const ctx = c.getContext('2d');
const n = D.closes.length;
const pad = {{l:60,r:20,t:30,b:40}};
const W = c.width - pad.l - pad.r;
const H = c.height - pad.t - pad.b;
const priceMin = Math.min(...D.closes, ...D.ob.filter(x=>x!=null), ...D.os.filter(x=>x!=null));
const priceMax = Math.max(...D.closes, ...D.ob.filter(x=>x!=null), ...D.os.filter(x=>x!=null));
const dnoMin = Math.min(...D.dno.filter(x=>x!=null));
const dnoMax = Math.max(...D.dno.filter(x=>x!=null));
function x(i){{return pad.l + (i/(n-1))*W;}}
function yPrice(v){{return pad.t + (1-(v-priceMin)/(priceMax-priceMin||1))*H*0.55;}}
function yDno(v){{return pad.t + H*0.6 + (1-(v-dnoMin)/(dnoMax-dnoMin||1))*H*0.35;}}
ctx.strokeStyle='#333'; ctx.beginPath();
for(let i=0;i<n;i++){{const px=x(i), py=yPrice(D.closes[i]); i?ctx.lineTo(px,py):ctx.moveTo(px,py);}}
ctx.stroke();
ctx.strokeStyle='#e74c3c'; ctx.beginPath();
D.ob.forEach((v,i)=>{{if(v==null)return; const px=x(i), py=yPrice(v); i&&D.ob[i-1]!=null?ctx.lineTo(px,py):ctx.moveTo(px,py);}});
ctx.stroke();
ctx.strokeStyle='#27ae60'; ctx.beginPath();
D.os.forEach((v,i)=>{{if(v==null)return; const px=x(i), py=yPrice(v); i&&D.os[i-1]!=null?ctx.lineTo(px,py):ctx.moveTo(px,py);}});
ctx.stroke();
ctx.strokeStyle='#8e44ad'; ctx.beginPath();
D.dno.forEach((v,i)=>{{if(v==null)return; const px=x(i), py=yDno(v); i&&D.dno[i-1]!=null?ctx.lineTo(px,py):ctx.moveTo(px,py);}});
ctx.stroke();
ctx.fillStyle='#e74c3c'; D.peak_idx.forEach(i=>{{ctx.beginPath();ctx.arc(x(i),yDno(D.dno[i]),4,0,7);ctx.fill();}});
ctx.fillStyle='#27ae60'; D.trough_idx.forEach(i=>{{ctx.beginPath();ctx.arc(x(i),yDno(D.dno[i]),4,0,7);ctx.fill();}});
</script></body></html>"""


def export_window(name: str, start_ms: int) -> None:
    bars = fetch_ethusdt_1h_from_canonical(start_ms)
    arrays = bars_to_arrays(bars, timeframe="1H")
    atr = np.array(
        [
            float(s.values["atr"]) if s.valid and s.values.get("atr") is not None else float("nan")
            for s in compute_atr_series(arrays, period=14)
        ]
    )
    dno = compute_masked_dno_series(arrays, period=7)
    preds = compute_predictor_feature_series(arrays, config=DEFAULT_PREDICTOR_CONFIG, atr=atr)
    cfg = DEFAULT_PREDICTOR_CONFIG
    peak_idx, trough_idx = [], []
    for i in range(len(bars)):
        peaks, troughs = confirmed_extrema_at(
            dno, arrays.gap_flags, i, peak_strength=cfg.peak_strength, lookback=cfg.lookback
        )
        if peaks:
            peak_idx.append(peaks[-1].index)
        if troughs:
            trough_idx.append(troughs[-1].index)
    payload = {
        "window": name,
        "symbol": "ETHUSDT",
        "timeframe": "1H",
        "data_provenance": {
            "source_host": CANONICAL_HOST,
            "source_path": CANONICAL_SOURCE_PATH,
        },
        "closes": [float(b["close"]) for b in bars],
        "dno": [None if np.isnan(x) else float(x) for x in dno],
        "ob": [p.get("PREDICTOR_OB_PRICE_NEXT_BAR") if p.get("valid") else None for p in preds],
        "os": [p.get("PREDICTOR_OS_PRICE_NEXT_BAR") if p.get("valid") else None for p in preds],
        "dynamic_ob": [p.get("DYNAMIC_OB_OSC_TARGET") if p.get("valid") else None for p in preds],
        "dynamic_os": [p.get("DYNAMIC_OS_OSC_TARGET") if p.get("valid") else None for p in preds],
        "peak_idx": sorted(set(peak_idx)),
        "trough_idx": sorted(set(trough_idx)),
    }
    ART.mkdir(parents=True, exist_ok=True)
    (ART / f"{name}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (ART / f"{name}.html").write_text(_html_chart(payload, f"ETHUSDT 1H — {name}"), encoding="utf-8")


def run_real_history_visual_audit() -> dict[str, Any]:
    try:
        for name, start_ms in WINDOWS:
            export_window(name, start_ms)
        (ART / "README.txt").write_text(
            "Real ETHUSDT 1H history visual audit from S7 canonical data via S13 disposable cache.\n"
            "Existing committed artifacts from prior Binance-API runs remain as historical evidence.\n"
            "Files: *.html charts + *.json machine-readable payloads.\n",
            encoding="utf-8",
        )
        return {
            "REAL_HISTORY_VISUAL_AUDIT": "PASS",
            "windows": [w[0] for w in WINDOWS],
            "data_source": f"{CANONICAL_HOST}:{CANONICAL_SOURCE_PATH}",
        }
    except Exception as exc:
        return {"REAL_HISTORY_VISUAL_AUDIT": "FAIL", "error": str(exc)}


def main() -> None:
    print(json.dumps(run_real_history_visual_audit(), indent=2))


if __name__ == "__main__":
    main()
