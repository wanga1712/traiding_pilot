from __future__ import annotations

import bisect
from datetime import datetime, timedelta, timezone

from crypto_trading_bot.research_v2.market_data.bars_service import _parse_axis_time, verify_interval
from crypto_trading_bot.research_v2.resampling import TIMEFRAMES

INITIAL_LOAD_BARS = 1200
DEFAULT_VISIBLE_BARS = 480
MIN_VISIBLE_BARS = 60
MAX_VISIBLE_BARS = 800
ZOOM_STEP_FRACTION = 0.90
LAZY_CHUNK_BARS = 400
PAN_EDGE_BARS = 20
RANGE_SHORTCUTS = (60, 120, 240, 360, 480, 600, 800)
RIGHT_OFFSET_BARS = 0


def _bar_times(candles: list[dict]) -> list[datetime]:
    return [datetime.fromisoformat(c["open_time_utc"]) for c in candles]


def bar_index_ge(candles: list[dict], ts: datetime) -> int:
    times = _bar_times(candles)
    return bisect.bisect_left(times, ts)


def bar_index_le(candles: list[dict], ts: datetime) -> int:
    times = _bar_times(candles)
    idx = bisect.bisect_right(times, ts) - 1
    return max(0, min(idx, len(candles) - 1))


def count_actual_visible_bars(candles: list[dict], from_time: str | datetime, to_time: str | datetime) -> int:
    if not candles:
        return 0
    start = _parse_axis_time(from_time)
    end = _parse_axis_time(to_time)
    if start > end:
        start, end = end, start
    first = bar_index_ge(candles, start)
    last = bar_index_le(candles, end)
    if first > last or first >= len(candles):
        return 0
    return last - first + 1


def viewport_for_bar_count(
    candles: list[dict],
    bar_count: int,
    *,
    anchor_index: int | None = None,
    align: str = "right",
) -> tuple[int, int]:
    if not candles:
        return 0, 0
    bar_count = max(MIN_VISIBLE_BARS, min(MAX_VISIBLE_BARS, int(bar_count)))
    last_index = len(candles) - 1
    if anchor_index is None:
        anchor_index = last_index if align == "right" else 0
    anchor_index = max(0, min(anchor_index, last_index))
    if align == "right":
        end_idx = anchor_index
        start_idx = max(0, end_idx - bar_count + 1)
    else:
        start_idx = max(0, anchor_index)
        end_idx = min(last_index, start_idx + bar_count - 1)
        start_idx = max(0, end_idx - bar_count + 1)
    return start_idx, end_idx


def build_viewport_metrics(candles: list[dict], start_idx: int, end_idx: int) -> dict:
    if not candles:
        return {
            "bar_from": 0,
            "bar_to": 0,
            "visible_from_time": None,
            "visible_to_time": None,
            "actual_visible_ohlc_bars": 0,
            "first_visible_bar_timestamp": None,
            "last_visible_bar_timestamp": None,
            "debug_logical_from": 0,
            "debug_logical_to": 0,
        }
    start_idx = max(0, min(start_idx, len(candles) - 1))
    end_idx = max(start_idx, min(end_idx, len(candles) - 1))
    from_time = candles[start_idx]["open_time_utc"]
    to_time = candles[end_idx]["open_time_utc"]
    actual = end_idx - start_idx + 1
    return {
        "bar_from": start_idx,
        "bar_to": end_idx,
        "visible_from_time": from_time,
        "visible_to_time": to_time,
        "actual_visible_ohlc_bars": actual,
        "first_visible_bar_timestamp": from_time,
        "last_visible_bar_timestamp": to_time,
        "debug_logical_from": start_idx,
        "debug_logical_to": end_idx,
        "start": from_time,
        "end": to_time,
    }


def default_chart_state(symbol: str = "ETHUSDT", timeframe: str = "4H", end_at: datetime | None = None) -> dict:
    end = end_at or datetime(2024, 6, 30, tzinfo=timezone.utc)
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "candles": [],
        "viewport_start": None,
        "viewport_end": None,
        "bar_from": None,
        "bar_to": None,
        "chart_instance_id": 1,
        "ui_revision": 0,
        "market_data_revision": 0,
        "audit": {},
        "requested_end": end.isoformat(),
    }


def build_audit(service, timeframe: str, candles: list[dict], viewport: dict, extra: dict | None = None) -> dict:
    audit = service.audit(candles, timeframe, viewport["visible_from_time"], viewport["visible_to_time"])
    audit["loaded_bars"] = len(candles)
    audit["actual_visible_ohlc_bars"] = viewport["actual_visible_ohlc_bars"]
    audit["visible_from_time"] = viewport["visible_from_time"]
    audit["visible_to_time"] = viewport["visible_to_time"]
    audit["first_visible_bar_timestamp"] = viewport["first_visible_bar_timestamp"]
    audit["last_visible_bar_timestamp"] = viewport["last_visible_bar_timestamp"]
    audit["debug_logical_from"] = viewport["bar_from"]
    audit["debug_logical_to"] = viewport["bar_to"]
    audit["shortcut_target"] = viewport.get("shortcut_target", "NONE")
    audit["display_downsampling"] = "DISABLED"
    audit["chart_engine"] = "tradingview_lightweight_charts_v4_index_temporal"
    if extra:
        audit.update(extra)
    assert audit["actual_visible_ohlc_bars"] <= audit["loaded_bars"]
    return audit


def load_initial_window(service, chart_state: dict, *, load_bars: int = INITIAL_LOAD_BARS, visible_bars: int = DEFAULT_VISIBLE_BARS) -> dict:
    end_at = datetime.fromisoformat(chart_state["requested_end"])
    candles = service.get_bars(chart_state["timeframe"], before=end_at + timedelta(minutes=TIMEFRAMES[chart_state["timeframe"]]), limit=load_bars)
    if not candles:
        raise ValueError("initial candle load returned no rows")
    start_idx, end_idx = viewport_for_bar_count(candles, visible_bars, align="right")
    viewport = build_viewport_metrics(candles, start_idx, end_idx)
    chart_state = dict(chart_state)
    chart_state["candles"] = candles
    chart_state["viewport_start"] = viewport["visible_from_time"]
    chart_state["viewport_end"] = viewport["visible_to_time"]
    chart_state["bar_from"] = viewport["bar_from"]
    chart_state["bar_to"] = viewport["bar_to"]
    chart_state["chart_instance_id"] = chart_state.get("chart_instance_id", 1)
    chart_state["ui_revision"] = chart_state.get("ui_revision", 0) + 1
    chart_state["market_data_revision"] = chart_state.get("market_data_revision", 0) + 1
    chart_state["audit"] = build_audit(service, chart_state["timeframe"], candles, viewport)
    return chart_state


def sync_chart_state_from_relayout(chart_state: dict, relayout: dict) -> dict:
    candles = chart_state.get("candles", [])
    if not candles or relayout.get("bar_from") is None or relayout.get("bar_to") is None:
        return chart_state
    start_idx = int(relayout["bar_from"])
    end_idx = int(relayout["bar_to"])
    metrics = build_viewport_metrics(candles, start_idx, end_idx)
    updated = dict(chart_state)
    updated["bar_from"] = metrics["bar_from"]
    updated["bar_to"] = metrics["bar_to"]
    updated["viewport_start"] = metrics["visible_from_time"]
    updated["viewport_end"] = metrics["visible_to_time"]
    audit = dict(updated.get("audit", {}))
    audit.update(metrics)
    updated["audit"] = audit
    return updated


def apply_viewport_from_relayout(chart_state: dict, updated_chart: dict, relayout: dict, viewport: dict) -> dict:
    viewport = dict(viewport or {})
    candles = updated_chart.get("candles", [])
    if not candles:
        viewport["changed"] = False
        return viewport

    if relayout.get("bar_from") is not None and relayout.get("bar_to") is not None:
        start_idx = int(relayout["bar_from"])
        end_idx = int(relayout["bar_to"])
    elif relayout.get("visible_from_time") and relayout.get("visible_to_time"):
        start_idx = bar_index_ge(candles, _parse_axis_time(relayout["visible_from_time"]))
        end_idx = bar_index_le(candles, _parse_axis_time(relayout["visible_to_time"]))
    else:
        viewport["changed"] = False
        return viewport

    metrics = build_viewport_metrics(candles, start_idx, end_idx)
    counted = count_actual_visible_bars(candles, metrics["visible_from_time"], metrics["visible_to_time"])
    metrics["counted_visible_ohlc_bars"] = counted
    metrics["viewport_invariant"] = "PASS" if abs(counted - metrics["actual_visible_ohlc_bars"]) <= 2 else "FAIL"
    if relayout.get("shortcut_target") is not None:
        metrics["shortcut_target"] = relayout["shortcut_target"]
    elif viewport.get("shortcut_target") not in (None, "NONE"):
        metrics["shortcut_target"] = viewport["shortcut_target"]
    else:
        metrics["shortcut_target"] = "NONE"
    if relayout.get("viewport_invariant"):
        metrics["viewport_invariant"] = relayout["viewport_invariant"]
    if relayout.get("counted_visible_ohlc_bars") is not None:
        metrics["counted_visible_ohlc_bars"] = relayout["counted_visible_ohlc_bars"]
    if relayout.get("anchor_index") is not None:
        metrics["anchor_index"] = relayout["anchor_index"]
    if relayout.get("raw_wheel_event_count") is not None:
        metrics["raw_wheel_event_count"] = relayout["raw_wheel_event_count"]
    if relayout.get("applied_zoom_gesture_count") is not None:
        metrics["applied_zoom_gesture_count"] = relayout["applied_zoom_gesture_count"]
    viewport.update(metrics)
    viewport["changed"] = True
    viewport["zoom_event_count"] = int(viewport.get("zoom_event_count", 0)) + (1 if relayout.get("zoom_direction") else 0)
    if relayout.get("zoom_direction"):
        viewport["last_zoom_direction"] = relayout["zoom_direction"]
    if relayout.get("anchor_timestamp"):
        viewport["anchor_timestamp"] = relayout["anchor_timestamp"]
    return viewport


def maybe_prepend_history(service, chart_state: dict, relayout: dict | None, viewport: dict | None = None) -> tuple[dict, dict]:
    viewport = dict(viewport or {})
    if not chart_state.get("candles"):
        return chart_state, viewport
    candles = chart_state["candles"]

    if relayout and relayout.get("bar_from") is not None:
        bar_from = int(relayout["bar_from"])
        bar_to = int(relayout["bar_to"])
    else:
        bar_from = int(viewport.get("bar_from", chart_state.get("bar_from", 0)))
        bar_to = int(viewport.get("bar_to", chart_state.get("bar_to", len(candles) - 1)))

    visible_count = bar_to - bar_from + 1

    if bar_from > PAN_EDGE_BARS:
        metrics = build_viewport_metrics(candles, bar_from, bar_to)
        chart_state = dict(chart_state)
        chart_state.update(
            {
                "bar_from": metrics["bar_from"],
                "bar_to": metrics["bar_to"],
                "viewport_start": metrics["visible_from_time"],
                "viewport_end": metrics["visible_to_time"],
            }
        )
        return chart_state, viewport

    loaded_start = datetime.fromisoformat(candles[0]["open_time_utc"])
    older = service.get_bars(chart_state["timeframe"], before=loaded_start, limit=LAZY_CHUNK_BARS)
    older = [row for row in older if datetime.fromisoformat(row["open_time_utc"]) < loaded_start]
    if not older:
        return chart_state, viewport

    existing = {row["open_time_utc"] for row in candles}
    prepend = [row for row in older if row["open_time_utc"] not in existing]
    if not prepend:
        return chart_state, viewport

    prepend.sort(key=lambda row: row["open_time_utc"])
    shift = len(prepend)
    merged = prepend + candles
    center_idx = bar_from + visible_count // 2
    anchor_time = candles[center_idx]["open_time_utc"]
    new_center = next(i for i, row in enumerate(merged) if row["open_time_utc"] == anchor_time)
    new_start = max(0, new_center - visible_count // 2)
    new_end = new_start + visible_count - 1
    if new_end >= len(merged):
        new_end = len(merged) - 1
        new_start = max(0, new_end - visible_count + 1)

    metrics = build_viewport_metrics(merged, new_start, new_end)
    chart_state = dict(chart_state)
    chart_state["candles"] = merged
    chart_state["bar_from"] = metrics["bar_from"]
    chart_state["bar_to"] = metrics["bar_to"]
    chart_state["viewport_start"] = metrics["visible_from_time"]
    chart_state["viewport_end"] = metrics["visible_to_time"]
    chart_state["ui_revision"] = chart_state.get("ui_revision", 0) + 1
    chart_state["market_data_revision"] = chart_state.get("market_data_revision", 0) + 1
    chart_state["audit"] = build_audit(service, chart_state["timeframe"], merged, metrics)
    viewport.update(metrics)
    viewport["lazy_anchor_preserved"] = merged[new_center]["open_time_utc"] == anchor_time
    return chart_state, viewport


def reload_timeframe(service, chart_state: dict, timeframe: str) -> dict:
    chart_state = dict(chart_state)
    chart_state["timeframe"] = timeframe
    chart_state["candles"] = []
    chart_state["viewport_start"] = None
    chart_state["viewport_end"] = None
    chart_state["bar_from"] = None
    chart_state["bar_to"] = None
    chart_state["chart_instance_id"] = chart_state.get("chart_instance_id", 1) + 1
    return load_initial_window(service, chart_state)


def set_visible_bar_count(chart_state: dict, bar_count: int, service=None, anchor_index: int | None = None) -> dict:
    candles = chart_state["candles"]
    if not candles:
        return chart_state
    if anchor_index is None:
        anchor_index = chart_state.get("bar_to", len(candles) - 1)
    start_idx, end_idx = viewport_for_bar_count(candles, bar_count, anchor_index=anchor_index, align="right")
    viewport = build_viewport_metrics(candles, start_idx, end_idx)
    chart_state = dict(chart_state)
    chart_state.update(
        {
            "viewport_start": viewport["visible_from_time"],
            "viewport_end": viewport["visible_to_time"],
            "bar_from": viewport["bar_from"],
            "bar_to": viewport["bar_to"],
            "apply_viewport": True,
            "viewport_count": bar_count,
            "shortcut_target": bar_count,
        }
    )
    if service is not None:
        chart_state["audit"] = build_audit(service, chart_state["timeframe"], candles, viewport)
    else:
        chart_state["audit"] = {**chart_state.get("audit", {}), **viewport, "loaded_bars": len(candles)}
    return chart_state


def candles_to_lwc(candles: list[dict]) -> list[dict]:
    rows = []
    for candle in candles:
        ts = int(datetime.fromisoformat(candle["open_time_utc"]).timestamp())
        rows.append(
            {
                "time": ts,
                "open": float(candle["open"]),
                "high": float(candle["high"]),
                "low": float(candle["low"]),
                "close": float(candle["close"]),
                "open_time_utc": candle["open_time_utc"],
            }
        )
    return rows


def build_chart_payload(chart_state: dict, session: dict, oos_blind: bool) -> dict:
    candles = chart_state.get("candles", [])
    points = session.get("points", [])
    show_geometry = True if oos_blind else bool(session.get("show_geometry", False))
    apply_viewport = bool(chart_state.get("apply_viewport", False))
    price_y_mode = session.get("price_y_mode", "lock")
    return {
        "engine": "tradingview_lightweight_charts_v4_index_temporal",
        "symbol": chart_state.get("symbol"),
        "timeframe": chart_state.get("timeframe"),
        "chart_instance_id": chart_state.get("chart_instance_id", 1),
        "ui_revision": chart_state.get("ui_revision", 0),
        "market_data_revision": chart_state.get("market_data_revision", 0),
        "candles": candles_to_lwc(candles),
        "initial_visible_bars": DEFAULT_VISIBLE_BARS,
        "visible_start_index": chart_state.get("bar_from"),
        "visible_end_index": chart_state.get("bar_to"),
        "viewport_count": chart_state.get("viewport_count") if apply_viewport else None,
        "apply_viewport": apply_viewport,
        "points": points,
        "show_geometry": show_geometry,
        "add_point_armed": session.get("mode") == "ADD",
        "interaction_mode": session.get("mode"),
        "snap_mode": session.get("snap_mode", "FREE"),
        "selected_index": session.get("selected_index"),
        "fit_window_y": bool(chart_state.get("fit_window_y", False)),
        "price_y_mode": price_y_mode,
        "min_visible_bars": MIN_VISIBLE_BARS,
        "max_visible_bars": MAX_VISIBLE_BARS,
        "zoom_step_factor": ZOOM_STEP_FRACTION,
    }


def nearest_candle(candles: list[dict], clicked_x) -> dict:
    clicked = _parse_axis_time(clicked_x)
    return min(candles, key=lambda candle: abs(datetime.fromisoformat(candle["open_time_utc"]) - clicked))


def _resolve_candle(candles: list[dict], clicked: dict) -> tuple[dict, int]:
    if clicked.get("bar_index") is not None:
        idx = max(0, min(int(clicked["bar_index"]), len(candles) - 1))
        return candles[idx], idx
    candle = nearest_candle(candles, clicked["x"])
    idx = next(i for i, c in enumerate(candles) if c["open_time_utc"] == candle["open_time_utc"])
    return candle, idx


def _price_for_snap(candle: dict, snap_mode: str, clicked_y) -> tuple[str, str]:
    mode = (snap_mode or "FREE").upper()
    if mode == "HIGH":
        return str(candle["high"]), "HIGH"
    if mode == "LOW":
        return str(candle["low"]), "LOW"
    return str(clicked_y), "NONE"


def nearest_point_index(points: list[dict], clicked: dict, candles: list[dict]) -> int | None:
    if not points:
        return None
    _, bar_idx = _resolve_candle(candles, clicked)
    click_price = float(clicked["y"])
    best_idx = None
    best_score = float("inf")
    for i, point in enumerate(points):
        p_idx = next((j for j, c in enumerate(candles) if c["open_time_utc"] == point["timestamp"]), bar_idx)
        price_delta = abs(float(point["price"]) - click_price)
        bar_delta = abs(p_idx - bar_idx)
        score = price_delta + bar_delta * 25
        if score < best_score:
            best_score = score
            best_idx = i
    return best_idx


def _validate_chronology(points: list[dict], new_timestamp: str, *, mode: str, index: int | None = None) -> str | None:
    new_dt = datetime.fromisoformat(new_timestamp)
    if mode == "ADD":
        if not points:
            return None
        prev_dt = datetime.fromisoformat(points[-1]["timestamp"])
        if new_dt == prev_dt:
            return "POINT NOT ADDED: same 4H candle already used"
        if new_dt < prev_dt:
            return f"POINT NOT ADDED: new point must be after P{len(points) - 1}"
        return None
    if mode == "MOVE" and index is not None:
        if index > 0:
            prev_dt = datetime.fromisoformat(points[index - 1]["timestamp"])
            if new_dt <= prev_dt:
                return f"POINT NOT MOVED: must be after P{index - 1}"
        if index < len(points) - 1:
            next_dt = datetime.fromisoformat(points[index + 1]["timestamp"])
            if new_dt >= next_dt:
                return f"POINT NOT MOVED: must be before P{index + 1}"
        return None
    return None


def add_or_move_point(session, clicked, candles, annotation_timeframe: str):
    if not clicked or session.get("locked"):
        return session
    mode = session.get("mode")
    if mode not in ("ADD", "MOVE"):
        return session
    candle, _ = _resolve_candle(candles, clicked)
    price, snap_source = _price_for_snap(candle, session.get("snap_mode", "FREE"), clicked["y"])
    from copy import deepcopy

    if mode == "MOVE" and session.get("selected_index") is None:
        picked = nearest_point_index(session["points"], clicked, candles)
        if picked is None:
            session["message"] = "MOVE: NO POINT NEAR CLICK"
            return session
        session["selected_index"] = picked
        session["message"] = f"MOVE: P{picked} SELECTED — CLICK NEW LOCATION"
        return session

    move_index = int(session["selected_index"]) if mode == "MOVE" and session.get("selected_index") is not None else None
    chrono_error = _validate_chronology(session["points"], candle["open_time_utc"], mode=mode, index=move_index)
    if chrono_error:
        session["message"] = chrono_error
        session["debug"] = {
            "add_point_armed": mode == "ADD",
            "click_received": True,
            "resolved_time": candle["open_time_utc"],
            "point_created": "—",
            "failure_reason": chrono_error,
        }
        return session

    point = {
        "point_index": len(session["points"]),
        "timestamp": candle["open_time_utc"],
        "price": price,
        "snap_source": snap_source,
        "annotation_timeframe": annotation_timeframe,
    }
    session.setdefault("history", []).append(deepcopy(session["points"]))
    if mode == "MOVE" and move_index is not None:
        point["point_index"] = move_index
        session["points"][move_index] = point
        session["selected_index"] = None
        session["mode"] = "MOVE"
        session["message"] = f"P{move_index} MOVED"
    else:
        session["points"].append(point)
        session["selected_index"] = len(session["points"]) - 1
        session["mode"] = "ADD"
        session["message"] = f"P{point['point_index']} PLACED — ADD NEXT OR CHANGE TOOL"
    session["points"] = [{**p, "point_index": i} for i, p in enumerate(session["points"])]
    session["debug"] = {
        "add_point_armed": session["mode"] == "ADD",
        "click_received": True,
        "raw_x": clicked.get("x"),
        "raw_y": clicked.get("y"),
        "resolved_time": candle["open_time_utc"],
        "resolved_price": price,
        "point_created": f"P{point['point_index']}",
        "failure_reason": "NONE",
    }
    session["evaluations"] = []
    return session


def delete_point_at_click(session, clicked, candles):
    if not clicked or session.get("locked"):
        return session
    if session.get("mode") != "DELETE":
        return session
    picked = clicked.get("point_index")
    if picked is None:
        picked = nearest_point_index(session["points"], clicked, candles)
    if picked is None:
        session["message"] = "DELETE: NO POINT NEAR CLICK"
        return session
    from copy import deepcopy

    session.setdefault("history", []).append(deepcopy(session["points"]))
    session["points"].pop(int(picked))
    session["points"] = [{**p, "point_index": i} for i, p in enumerate(session["points"])]
    session["selected_index"] = None
    session["evaluations"] = []
    session["message"] = f"P{picked} DELETED"
    return session


def audit_panel_rows(audit: dict) -> list[tuple[str, str]]:
    return [
        ("SYMBOL", audit.get("symbol", "—")),
        ("SELECTED_TF", audit.get("selected_tf", "—")),
        ("ACTUAL_TF", audit.get("actual_tf", "—")),
        ("LOADED_BARS", audit.get("loaded_bars", "—")),
        ("ACTUAL_VISIBLE_OHLC_BARS", audit.get("actual_visible_ohlc_bars", "—")),
        ("VISIBLE_FROM_TIME", audit.get("visible_from_time", "—")),
        ("VISIBLE_TO_TIME", audit.get("visible_to_time", "—")),
        ("FIRST_VISIBLE_BAR", audit.get("first_visible_bar_timestamp", "—")),
        ("LAST_VISIBLE_BAR", audit.get("last_visible_bar_timestamp", "—")),
        ("VISIBLE_START_INDEX", audit.get("bar_from", "—")),
        ("VISIBLE_END_INDEX", audit.get("bar_to", "—")),
        ("VIEWPORT_INVARIANT", audit.get("viewport_invariant", "—")),
        ("COUNTED_VISIBLE", audit.get("counted_visible_ohlc_bars", "—")),
        ("ANCHOR_INDEX", audit.get("anchor_index", "—")),
        ("SHORTCUT_TARGET", audit.get("shortcut_target", "NONE")),
        ("INTERVAL_CHECK", audit.get("interval_check", "—")),
        ("DISPLAY_DOWNSAMPLING", audit.get("display_downsampling", "DISABLED")),
        ("MARKET_DATA_REVISION", audit.get("market_data_revision", "—")),
    ]
