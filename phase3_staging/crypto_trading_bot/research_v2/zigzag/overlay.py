"""Visual overlay of expert points vs classic ZigZag pivots."""
from __future__ import annotations

from pathlib import Path
from typing import Any


def write_overlay_html(
    path: Path,
    *,
    candles: list[dict],
    expert_points: list[dict],
    zigzag_pivots: list[Any],
    match_pairs: list[dict],
    title: str,
    params_label: str,
) -> Path:
    """Write a self-contained Lightweight Charts HTML overlay (no server required)."""
    import json

    candle_rows = []
    for c in candles:
        ts = c["open_time_utc"]
        if hasattr(ts, "timestamp"):
            t = int(ts.timestamp())
        else:
            from datetime import datetime

            text = str(ts).replace("Z", "+00:00")
            if text.endswith("+00"):
                text += ":00"
            t = int(datetime.fromisoformat(text).timestamp())
        candle_rows.append(
            {
                "time": t,
                "open": float(c["open"]),
                "high": float(c["high"]),
                "low": float(c["low"]),
                "close": float(c["close"]),
            }
        )

    def pt_time(ts) -> int:
        from datetime import datetime

        if hasattr(ts, "timestamp"):
            return int(ts.timestamp())
        text = str(ts).replace("Z", "+00:00")
        if text.endswith("+00"):
            text += ":00"
        return int(datetime.fromisoformat(text).timestamp())

    expert_markers = []
    for p in expert_points:
        expert_markers.append(
            {
                "time": pt_time(p["timestamp"]),
                "position": "aboveBar",
                "color": "#f5d76e",
                "shape": "circle",
                "text": f"P{p.get('point_index', '')}",
            }
        )
    expert_line = [{"time": pt_time(p["timestamp"]), "value": float(p["price"])} for p in expert_points]

    zig_markers = []
    zig_line = []
    for i, z in enumerate(zigzag_pivots):
        ts = z.timestamp if hasattr(z, "timestamp") else z["timestamp"]
        price = float(z.price if hasattr(z, "price") else z["price"])
        kind = z.kind if hasattr(z, "kind") else z.get("kind", "")
        zig_markers.append(
            {
                "time": pt_time(ts),
                "position": "belowBar" if kind == "LOW" else "aboveBar",
                "color": "#4fc3f7",
                "shape": "arrowUp" if kind == "LOW" else "arrowDown",
                "text": f"Z{i}",
            }
        )
        zig_line.append({"time": pt_time(ts), "value": price})

    matched_times = {pt_time(p["expert_timestamp"]) for p in match_pairs}

    payload = {
        "candles": candle_rows,
        "expert_line": expert_line,
        "expert_markers": expert_markers,
        "zig_line": zig_line,
        "zig_markers": zig_markers,
        "matched_times": sorted(matched_times),
        "title": title,
        "params": params_label,
    }

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>{title}</title>
  <script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>
  <style>
    html, body {{ margin:0; height:100%; background:#131722; color:#d1d4dc; font-family:Segoe UI,sans-serif; }}
    #meta {{ padding:10px 14px; border-bottom:1px solid #2a2e39; }}
    #chart {{ height: calc(100% - 52px); }}
  </style>
</head>
<body>
  <div id="meta"><b>{title}</b> · {params_label} · yellow=EXPERT · cyan=ZIGZAG</div>
  <div id="chart"></div>
  <script>
    const payload = {json.dumps(payload)};
    const chart = LightweightCharts.createChart(document.getElementById('chart'), {{
      autoSize: true,
      layout: {{ background: {{ color: '#131722' }}, textColor: '#d1d4dc' }},
      grid: {{ vertLines: {{ color: '#242833' }}, horzLines: {{ color: '#242833' }} }},
      rightPriceScale: {{ borderColor: '#363a45' }},
      timeScale: {{ borderColor: '#363a45', timeVisible: true }}
    }});
    const candles = chart.addCandlestickSeries({{
      upColor: '#26a69a', downColor: '#ef5350', borderVisible: false,
      wickUpColor: '#26a69a', wickDownColor: '#ef5350'
    }});
    candles.setData(payload.candles);
    const expert = chart.addLineSeries({{ color: '#f5d76e', lineWidth: 2, title: 'EXPERT' }});
    expert.setData(payload.expert_line);
    expert.setMarkers(payload.expert_markers);
    const zig = chart.addLineSeries({{ color: '#4fc3f7', lineWidth: 2, lineStyle: 2, title: 'ZIGZAG' }});
    zig.setData(payload.zig_line);
    zig.setMarkers(payload.zig_markers);
    chart.timeScale().fitContent();
  </script>
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path
