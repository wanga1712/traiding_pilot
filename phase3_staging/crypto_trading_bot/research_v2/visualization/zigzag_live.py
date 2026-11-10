"""Live-chart ZigZag helpers (payload shaping for Lightweight Charts)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from crypto_trading_bot.research_v2.zigzag.classic import classic_percent_zigzag_live

DEFAULT_ZIGZAG_DEVIATION = 1.5
DEFAULT_ZIGZAG_DEPTH = 3
DEFAULT_ZIGZAG_BACKSTEP = 0


def default_zigzag_session() -> dict:
    return {
        "zigzag_enabled": True,
        "zigzag_deviation": DEFAULT_ZIGZAG_DEVIATION,
        "zigzag_depth": DEFAULT_ZIGZAG_DEPTH,
        "zigzag_backstep": DEFAULT_ZIGZAG_BACKSTEP,
        "zigzag_revision": 1,
    }


def _ts_unix(value: str) -> int:
    text = str(value).replace("Z", "+00:00")
    if text.endswith("+00"):
        text += ":00"
    return int(datetime.fromisoformat(text).timestamp())


def build_zigzag_payload(candles: list[dict], session: dict) -> dict[str, Any]:
    deviation = float(session.get("zigzag_deviation", DEFAULT_ZIGZAG_DEVIATION))
    depth = int(session.get("zigzag_depth", DEFAULT_ZIGZAG_DEPTH))
    backstep = int(session.get("zigzag_backstep", DEFAULT_ZIGZAG_BACKSTEP))
    enabled = bool(session.get("zigzag_enabled", True))
    if not candles or not enabled:
        return {
            "enabled": enabled,
            "deviation": deviation,
            "depth": depth,
            "backstep": backstep,
            "revision": int(session.get("zigzag_revision", 0)),
            "confirmed": [],
            "current": None,
            "line": [],
            "markers": [],
            "pivot_count": 0,
            "label": f"{deviation:g}% / D{depth} / B{backstep}",
        }

    live = classic_percent_zigzag_live(
        candles,
        deviation_percent=deviation,
        depth=depth,
        backstep=backstep,
    )
    confirmed = live["confirmed"]
    current = live["current"]

    line: list[dict] = []
    markers: list[dict] = []
    last_t = None
    for p in confirmed:
        t = _ts_unix(p.timestamp)
        if last_t is not None and t <= last_t:
            continue
        last_t = t
        line.append({"time": t, "value": float(p.price)})
        markers.append(
            {
                "time": t,
                "position": "aboveBar" if p.kind == "HIGH" else "belowBar",
                "color": "#26c6da" if p.kind == "HIGH" else "#ab47bc",
                "shape": "arrowDown" if p.kind == "HIGH" else "arrowUp",
                "text": "H" if p.kind == "HIGH" else "L",
            }
        )

    current_payload = None
    if current is not None:
        t = _ts_unix(current["timestamp"])
        current_payload = {
            "time": t,
            "value": float(current["price"]),
            "kind": current["kind"],
            "timestamp": current["timestamp"],
            "confirmed": False,
        }
        # Append current extreme to line for live leg visibility.
        if last_t is None or t > last_t:
            line.append({"time": t, "value": float(current["price"])})
            markers.append(
                {
                    "time": t,
                    "position": "aboveBar" if current["kind"] == "HIGH" else "belowBar",
                    "color": "#ffb74d",
                    "shape": "circle",
                    "text": "C",
                }
            )

    return {
        "enabled": True,
        "deviation": deviation,
        "depth": depth,
        "backstep": backstep,
        "revision": int(session.get("zigzag_revision", 0)),
        "confirmed_count": len(confirmed),
        "pivot_count": len(confirmed) + (1 if current_payload else 0),
        "confirmed": [
            {
                "index": p.index,
                "timestamp": p.timestamp,
                "price": float(p.price),
                "kind": p.kind,
                "confirmation_timestamp": p.confirmation_timestamp,
            }
            for p in confirmed
        ],
        "current": current_payload,
        "line": line,
        "markers": markers,
        "label": f"{deviation:g}% / D{depth} / B{backstep}",
    }
