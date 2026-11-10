"""Live-chart DiNapoli ABC→D selection payload."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from crypto_trading_bot.research_v2.dinapoli.validate_4h import FIB_COP, FIB_OP, FIB_XOP
from crypto_trading_bot.research_v2.zigzag.classic import classic_percent_zigzag_live
from crypto_trading_bot.research_v2.visualization.zigzag_live import (
    DEFAULT_ZIGZAG_BACKSTEP,
    DEFAULT_ZIGZAG_DEPTH,
    DEFAULT_ZIGZAG_DEVIATION,
)


def default_dinapoli_session() -> dict:
    return {
        "dinapoli_enabled": False,
        "dinapoli_window_index": 0,
        "dinapoli_revision": 0,
    }


def _ts_unix(value: str) -> int:
    text = str(value).replace("Z", "+00:00")
    if text.endswith("+00"):
        text += ":00"
    return int(datetime.fromisoformat(text).timestamp())


def _nearest_label(r: float) -> str:
    dist = {
        "COP": abs(r - FIB_COP),
        "OP": abs(r - FIB_OP),
        "XOP": abs(r - FIB_XOP),
    }
    best = min(dist, key=dist.get)
    if dist[best] > 0.35:
        if r > FIB_XOP + 0.35:
            return "ABOVE_XOP"
        if r < FIB_COP - 0.35:
            return "BELOW_COP"
        return "NONE"
    return best


def build_dinapoli_payload(candles: list[dict], session: dict) -> dict[str, Any]:
    enabled = bool(session.get("dinapoli_enabled", False))
    empty = {
        "enabled": enabled,
        "revision": int(session.get("dinapoli_revision", 0)),
        "window_index": None,
        "window_count": 0,
        "levels": [],
        "markers": [],
        "info": None,
    }
    if not enabled or not candles:
        return empty

    deviation = float(session.get("zigzag_deviation", DEFAULT_ZIGZAG_DEVIATION))
    depth = int(session.get("zigzag_depth", DEFAULT_ZIGZAG_DEPTH))
    backstep = int(session.get("zigzag_backstep", DEFAULT_ZIGZAG_BACKSTEP))
    live = classic_percent_zigzag_live(
        candles,
        deviation_percent=deviation,
        depth=depth,
        backstep=backstep,
    )
    pivots = live["confirmed"]
    window_count = max(0, len(pivots) - 3)
    if window_count <= 0:
        return empty

    idx = int(session.get("dinapoli_window_index") or 0)
    idx = max(0, min(idx, window_count - 1))
    a, b, c, d = pivots[idx], pivots[idx + 1], pivots[idx + 2], pivots[idx + 3]
    ab = float(b.price) - float(a.price)
    if ab == 0:
        return empty
    cop = float(c.price) + ab * FIB_COP
    op = float(c.price) + ab * FIB_OP
    xop = float(c.price) + ab * FIB_XOP
    r = (float(d.price) - float(c.price)) / ab
    nearest = _nearest_label(r)

    t_c = _ts_unix(c.timestamp)
    t_d = _ts_unix(d.timestamp)
    # Horizontal segments from C to D for objectives.
    levels = [
        {
            "id": "COP",
            "color": "#f5a623",
            "price": cop,
            "points": [{"time": t_c, "value": cop}, {"time": t_d, "value": cop}],
        },
        {
            "id": "OP",
            "color": "#ff4d8d",
            "price": op,
            "points": [{"time": t_c, "value": op}, {"time": t_d, "value": op}],
        },
        {
            "id": "XOP",
            "color": "#9b59b6",
            "price": xop,
            "points": [{"time": t_c, "value": xop}, {"time": t_d, "value": xop}],
        },
    ]
    markers = [
        {"time": _ts_unix(a.timestamp), "position": "belowBar", "color": "#ffffff", "shape": "circle", "text": "A"},
        {"time": _ts_unix(b.timestamp), "position": "aboveBar", "color": "#ffffff", "shape": "circle", "text": "B"},
        {"time": _ts_unix(c.timestamp), "position": "belowBar", "color": "#ffffff", "shape": "circle", "text": "C"},
        {"time": _ts_unix(d.timestamp), "position": "aboveBar", "color": "#ffeb3b", "shape": "circle", "text": "D"},
    ]
    info = {
        "window_index": idx,
        "window_count": window_count,
        "tf": session.get("timeframe") or session.get("chart_timeframe"),
        "zigzag_config": f"percent {deviation:g}% / depth {depth} / backstep {backstep}",
        "ab": ab,
        "cop": cop,
        "op": op,
        "xop": xop,
        "r": r,
        "nearest": nearest,
        "a": {"time": a.timestamp, "price": float(a.price), "kind": a.kind},
        "b": {"time": b.timestamp, "price": float(b.price), "kind": b.kind},
        "c": {"time": c.timestamp, "price": float(c.price), "kind": c.kind},
        "d": {"time": d.timestamp, "price": float(d.price), "kind": d.kind},
    }
    return {
        "enabled": True,
        "revision": int(session.get("dinapoli_revision", 0)),
        "window_index": idx,
        "window_count": window_count,
        "levels": levels,
        "markers": markers,
        "info": info,
    }
