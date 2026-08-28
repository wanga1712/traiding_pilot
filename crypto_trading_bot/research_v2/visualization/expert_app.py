from __future__ import annotations

import argparse
import json
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from dash import Dash, Input, Output, State, callback_context, dcc, html, no_update

from crypto_trading_bot.research_v2.annotations import S7PostgresAnnotationStore, evaluate_rolling_windows
from crypto_trading_bot.research_v2.market_data import TimeframeBarService
from crypto_trading_bot.research_v2.resampling import UI_TIMEFRAMES
from crypto_trading_bot.research_v2.visualization.chart_engine import (
    DEFAULT_VISIBLE_BARS,
    INITIAL_LOAD_BARS,
    MAX_VISIBLE_BARS,
    MIN_VISIBLE_BARS,
    RANGE_SHORTCUTS,
    add_or_move_point,
    apply_viewport_from_relayout,
    audit_panel_rows,
    build_chart_payload,
    default_chart_state,
    load_initial_window,
    maybe_prepend_history,
    nearest_candle,
    reload_timeframe,
    set_visible_bar_count,
)


def side_panel(session: dict, chart_state: dict, oos_blind: bool) -> html.Div:
    rows = [
        ("MODE", session.get("mode") or "NAVIGATE"),
        ("ANNOTATION ID", session["annotation_id"]),
        ("ANNOTATION TF", session.get("annotation_timeframe", chart_state["timeframe"])),
        ("POINT COUNT", len(session["points"])),
        *[(f"P{p['point_index']}", f"{p['timestamp']} / {p['price']} / {p.get('snap_source', 'NONE')}") for p in session["points"]],
    ]
    if not session["points"]:
        rows.append(("POINTS", "NOT SET"))
    rows.extend(audit_panel_rows(chart_state.get("audit", {})))
    debug = session.get("debug", {})
    rows += [
        ("ANNOTATION DEBUG", ""),
        ("add_point_armed", debug.get("add_point_armed", False)),
        ("click_received", debug.get("click_received", False)),
        ("resolved_time", debug.get("resolved_time", "—")),
        ("point_created", debug.get("point_created", "—")),
        ("failure_reason", debug.get("failure_reason", "—")),
    ]
    if not oos_blind:
        evaluations = session.get("evaluations", [])
        selected = session.get("window_index")
        if evaluations and selected is not None:
            result = evaluations[int(selected)]
            start = result["window_index"]
            rows += [
                ("WINDOW", result["window_label"]),
                ("CALCULATED COP", result["cop_price"]),
                ("CALCULATED OP", result["op_price"]),
                ("CALCULATED XOP", result["xop_price"]),
                ("MANUAL NEXT", f"P{start + 5}={result['manual_next_price']}"),
            ]
    return html.Div([html.Div([html.Span(key), html.Strong(str(value))], className="metric") for key, value in rows])


def audit_banner(chart_state: dict, viewport: dict | None = None) -> html.Div:
    audit = dict(chart_state.get("audit", {}))
    if viewport:
        for key in (
            "actual_visible_ohlc_bars",
            "visible_from_time",
            "visible_to_time",
            "first_visible_bar_timestamp",
            "last_visible_bar_timestamp",
            "visible_start_index",
            "visible_end_index",
            "viewport_invariant",
            "counted_visible_ohlc_bars",
            "anchor_index",
            "zoom_step_factor",
            "wheel_delta_raw",
            "wheel_direction",
            "min_visible_limit",
            "max_visible_limit",
            "shortcut_target",
            "last_zoom_direction",
            "zoom_event_count",
        ):
            if key in viewport:
                audit[key] = viewport[key]
    loaded = audit.get("loaded_bars", "—")
    actual = audit.get("actual_visible_ohlc_bars", "—")
    return html.Div(
        [
            html.Span(f"SELECTED_TF: {audit.get('selected_tf', '—')}"),
            html.Span(f"ACTUAL_TF: {audit.get('actual_tf', '—')}"),
            html.Span(f"LOADED_BARS: {loaded}"),
            html.Span(f"ACTUAL_VISIBLE_OHLC_BARS: {actual}"),
            html.Span(f"INDEX: {audit.get('bar_from', '—')}→{audit.get('bar_to', '—')}"),
            html.Span(f"INVARIANT: {audit.get('viewport_invariant', '—')}"),
            html.Span(f"VISIBLE_FROM: {audit.get('visible_from_time', '—')}"),
            html.Span(f"VISIBLE_TO: {audit.get('visible_to_time', '—')}"),
            html.Span(f"ANCHOR: {audit.get('anchor_index', '—')}"),
            html.Span(f"WHEEL: {audit.get('wheel_direction', '—')} step={audit.get('zoom_step_factor', '—')}"),
            html.Span(f"LIMITS: {audit.get('min_visible_limit', MIN_VISIBLE_BARS)}–{audit.get('max_visible_limit', MAX_VISIBLE_BARS)}"),
            html.Span(f"SHORTCUT: {audit.get('shortcut_target', 'NONE')}"),
        ],
        className="audit-banner",
    )


def create_app(
    service: TimeframeBarService,
    *,
    store: S7PostgresAnnotationStore | None = None,
    oos_blind: bool = True,
    initial_end: datetime | None = None,
):
    store = store or S7PostgresAnnotationStore()
    app = Dash(
        __name__,
        assets_folder=str(Path(__file__).with_name("assets")),
        suppress_callback_exceptions=True,
        external_scripts=["https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"],
    )
    chart_state = load_initial_window(
        service,
        default_chart_state(service.symbol, "4H", initial_end or datetime(2024, 6, 30, tzinfo=timezone.utc)),
    )
    chart_state["apply_viewport"] = True
    viewport = {
        "bar_from": chart_state["bar_from"],
        "bar_to": chart_state["bar_to"],
        "visible_from_time": chart_state["viewport_start"],
        "visible_to_time": chart_state["viewport_end"],
        "actual_visible_ohlc_bars": chart_state["audit"]["actual_visible_ohlc_bars"],
        "shortcut_target": "NONE",
        "zoom_event_count": 0,
    }
    session = {
        "annotation_id": str(uuid.uuid4()),
        "annotation_timeframe": "4H",
        "points": [],
        "history": [],
        "mode": None,
        "selected_index": None,
        "locked": False,
        "show_geometry": False,
        "evaluations": [],
        "window_index": None,
        "message": "OOS BLIND ANNOTATION READY" if oos_blind else "EXPERT ANNOTATION READY",
        "debug": {
            "add_point_armed": False,
            "click_received": False,
            "resolved_time": "—",
            "point_created": "—",
            "failure_reason": "NONE",
        },
    }
    initial_payload = build_chart_payload(chart_state, session, oos_blind)
    app.layout = html.Div(
        [
            html.Header(
                [
                    html.Div([html.Span("RG", className="brand"), html.B("Expert Geometry Workspace")]),
                    html.Div(
                        [
                            html.B(service.symbol),
                            html.Span(" · Spot · Binance · "),
                            dcc.Dropdown(
                                id="timeframe",
                                options=[{"label": tf, "value": tf} for tf in UI_TIMEFRAMES],
                                value="4H",
                                clearable=False,
                                className="tf-dropdown",
                            ),
                        ],
                        className="ticker",
                    ),
                    html.Div("OOS BLIND" if oos_blind else "GOLD ANNOTATION", className="algo"),
                ]
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                "EXPERT MANUAL GEOMETRY — P0 → P1 → ... → Pn" + (" · BLIND MODE" if oos_blind else ""),
                                className="mode-banner",
                            ),
                            html.Div(id="audit-banner", className="audit-banner-wrap"),
                            html.Div(
                                [
                                    html.Button("ADD POINT", id="add-point"),
                                    html.Button("MOVE / REPLACE", id="move-point"),
                                    html.Button("DELETE POINT", id="delete-point"),
                                    html.Button("UNDO", id="undo"),
                                    html.Button("CLEAR UNSAVED", id="clear"),
                                    html.Button("SNAP HIGH", id="snap-high"),
                                    html.Button("SNAP LOW", id="snap-low"),
                                    *[html.Button(str(count), id=f"range-{count}", className="range-shortcut") for count in RANGE_SHORTCUTS],
                                    dcc.Dropdown(id="point-select", placeholder="Select point", clearable=False),
                                    dcc.Checklist(
                                        [{"label": "SHOW MANUAL GEOMETRY", "value": "show"}],
                                        value=[],
                                        id="show-geometry",
                                        style={"display": "none" if oos_blind else "block"},
                                    ),
                                    html.Button("EVALUATE ROLLING GEOMETRY", id="evaluate", style={"display": "none" if oos_blind else "inline-block"}),
                                    dcc.Dropdown(id="window-select", placeholder="Rolling window", clearable=False, style={"display": "none" if oos_blind else "block"}),
                                    dcc.Input(id="notes", placeholder="Annotation notes", type="text"),
                                    html.Button("SAVE ANNOTATION", id="save"),
                                ],
                                className="controls",
                            ),
                            html.Div(id="lwc-chart", className="tv-chart"),
                            html.Div(id="status", className="seedbar"),
                            dcc.Store(id="session", data=session),
                            dcc.Store(id="chart-state", data=chart_state),
                            dcc.Store(id="viewport-store", data=viewport),
                            dcc.Input(id="chart-payload-bridge", type="text", value=json.dumps(initial_payload), style={"display": "none"}),
                            dcc.Input(id="manual-click-bridge", type="text", style={"display": "none"}),
                            dcc.Input(id="relayout-bridge", type="text", style={"display": "none"}),
                        ],
                        className="chartcol",
                    ),
                    html.Aside(id="panel"),
                ],
                className="grid",
            ),
        ],
        className="app",
    )

    @app.callback(
        Output("viewport-store", "data"),
        Output("chart-state", "data", allow_duplicate=True),
        Input("relayout-bridge", "value"),
        State("chart-state", "data"),
        State("viewport-store", "data"),
        prevent_initial_call=True,
    )
    def on_relayout(relayout_raw, chart_state, viewport):
        try:
            relayout = json.loads(relayout_raw) if relayout_raw else None
        except Exception:
            return no_update, no_update
        if not relayout:
            return no_update, no_update
        updated_chart, viewport = maybe_prepend_history(service, chart_state, relayout, viewport or {})
        viewport = apply_viewport_from_relayout(chart_state, updated_chart, relayout, viewport)
        candles_changed = len(updated_chart.get("candles", [])) != len(chart_state.get("candles", []))
        if candles_changed:
            updated_chart = dict(updated_chart)
            updated_chart["apply_viewport"] = True
            viewport["visible_from_time"] = updated_chart.get("viewport_start")
            viewport["visible_to_time"] = updated_chart.get("viewport_end")
            return viewport, updated_chart
        if viewport.get("changed"):
            return viewport, no_update
        return no_update, no_update

    @app.callback(
        Output("viewport-store", "data", allow_duplicate=True),
        Output("chart-state", "data", allow_duplicate=True),
        [Input(f"range-{count}", "n_clicks") for count in RANGE_SHORTCUTS],
        State("chart-state", "data"),
        State("viewport-store", "data"),
        prevent_initial_call=True,
    )
    def on_range_shortcut(*args):
        chart_state = args[-2]
        viewport = args[-1]
        trigger = callback_context.triggered_id
        if not trigger or not trigger.startswith("range-"):
            return no_update, no_update
        bar_count = int(trigger.split("-")[1])
        anchor = chart_state.get("bar_to", len(chart_state.get("candles", [])) - 1)
        chart_state = set_visible_bar_count(chart_state, bar_count, service, anchor_index=anchor)
        viewport = dict(viewport or {})
        viewport.update(chart_state.get("audit", {}))
        viewport["shortcut_target"] = bar_count
        return viewport, chart_state

    @app.callback(
        Output("session", "data"),
        Output("chart-state", "data"),
        Input("add-point", "n_clicks"),
        Input("move-point", "n_clicks"),
        Input("delete-point", "n_clicks"),
        Input("undo", "n_clicks"),
        Input("clear", "n_clicks"),
        Input("snap-high", "n_clicks"),
        Input("snap-low", "n_clicks"),
        Input("evaluate", "n_clicks"),
        Input("save", "n_clicks"),
        Input("manual-click-bridge", "value"),
        Input("show-geometry", "value"),
        Input("point-select", "value"),
        Input("window-select", "value"),
        Input("timeframe", "value"),
        State("notes", "value"),
        State("session", "data"),
        State("chart-state", "data"),
        prevent_initial_call=True,
    )
    def mutate(add, move, delete, undo, clear, snap_high, snap_low, evaluate, save, clicked, show_geometry, selected_index, window_index, timeframe, notes, session, chart_state):
        trigger = callback_context.triggered_id
        candles = chart_state["candles"]
        if trigger == "timeframe":
            if session["points"] and timeframe != session.get("annotation_timeframe"):
                session["message"] = f"WARNING: unsaved points belong to {session.get('annotation_timeframe')}; change blocked"
                return session, chart_state
            chart_state = reload_timeframe(service, chart_state, timeframe)
            chart_state["apply_viewport"] = True
            session["annotation_timeframe"] = timeframe
            session["message"] = f"TIMEFRAME RELOADED: {timeframe}"
            return session, chart_state
        if trigger == "add-point":
            session["mode"] = "ADD"
            session["message"] = "ADD POINT: CLICK PRICE CHART"
            session["debug"] = {"add_point_armed": True, "click_received": False, "resolved_time": "—", "point_created": "—", "failure_reason": "WAITING_FOR_CLICK"}
        elif trigger == "move-point":
            session["mode"] = "MOVE"
            session["message"] = "SELECT POINT THEN CLICK NEW LOCATION"
        elif trigger == "point-select":
            session["selected_index"] = selected_index
        elif trigger == "window-select":
            session["window_index"] = window_index
        elif trigger == "show-geometry":
            session["show_geometry"] = "show" in (show_geometry or [])
        elif trigger == "manual-click-bridge":
            try:
                event = json.loads(clicked)
                session = add_or_move_point(session, event, candles, session.get("annotation_timeframe", chart_state["timeframe"]))
            except Exception as exc:
                session["debug"] = {"click_received": True, "failure_reason": f"COORDINATE_CONVERSION_FAILED: {exc}"}
                session["message"] = "POINT PLACEMENT FAILED"
        elif trigger == "delete-point" and selected_index is not None:
            session["history"].append(deepcopy(session["points"]))
            session["points"].pop(int(selected_index))
            session["points"] = [{**p, "point_index": i} for i, p in enumerate(session["points"])]
            session["selected_index"] = None
            session["evaluations"] = []
            session["message"] = "POINT DELETED"
        elif trigger == "undo" and session["history"]:
            session["points"] = session["history"].pop()
            session["evaluations"] = []
            session["message"] = "UNDO COMPLETE"
        elif trigger == "clear":
            session["history"].append(deepcopy(session["points"]))
            session["points"] = []
            session["evaluations"] = []
            session["message"] = "UNSAVED POINTS CLEARED"
        elif trigger in ("snap-high", "snap-low") and selected_index is not None:
            session["history"].append(deepcopy(session["points"]))
            point = session["points"][int(selected_index)]
            candle = nearest_candle(candles, point["timestamp"])
            source = "HIGH" if trigger == "snap-high" else "LOW"
            point["price"] = candle[source.lower()]
            point["snap_source"] = source
            session["message"] = f"P{selected_index} SNAP {source}"
        elif trigger == "evaluate" and not oos_blind:
            session["evaluations"] = evaluate_rolling_windows(session["points"])
            session["window_index"] = 0 if session["evaluations"] else None
            session["message"] = f"{len(session['evaluations'])} WINDOWS EVALUATED" if session["evaluations"] else "AT LEAST 6 POINTS REQUIRED"
        elif trigger == "save" and session["points"]:
            now = datetime.now(timezone.utc).isoformat()
            annotation = {
                "annotation_id": session["annotation_id"],
                "symbol": chart_state["symbol"],
                "timeframe": session.get("annotation_timeframe", chart_state["timeframe"]),
                "start_time": session["points"][0]["timestamp"],
                "end_time": session["points"][-1]["timestamp"],
                "created_at": now,
                "notes": notes or "",
                "points": session["points"],
            }
            try:
                store.save(annotation)
                session["message"] = "SAVED TO S7 POSTGRESQL"
            except Exception as exc:
                session["message"] = f"SAVE FAILED: {exc}"
        return session, chart_state

    @app.callback(
        Output("chart-payload-bridge", "value"),
        Output("panel", "children"),
        Output("status", "children"),
        Output("point-select", "options"),
        Output("window-select", "options"),
        Output("evaluate", "disabled"),
        Output("chart-state", "data", allow_duplicate=True),
        Input("session", "data"),
        Input("chart-state", "data"),
        prevent_initial_call="initial_duplicate",
    )
    def render(session, chart_state):
        chart_state_out = dict(chart_state)
        apply_viewport = bool(chart_state_out.pop("apply_viewport", False))
        chart_state_out.pop("shortcut_target", None)
        chart_state_out.pop("viewport_count", None)
        merged = dict(chart_state_out)
        merged["apply_viewport"] = apply_viewport
        payload = build_chart_payload(merged, session, oos_blind)
        return (
            json.dumps(payload),
            side_panel(session, chart_state, oos_blind),
            session["message"],
            [{"label": f"P{p['point_index']}", "value": p["point_index"]} for p in session["points"]],
            [{"label": result["window_label"], "value": result["window_index"]} for result in session.get("evaluations", [])],
            len(session["points"]) < 6,
            chart_state_out,
        )

    @app.callback(Output("audit-banner", "children"), Input("chart-state", "data"), Input("viewport-store", "data"))
    def render_audit(chart_state, viewport):
        return audit_banner(chart_state, viewport).children

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="ETHUSDT")
    parser.add_argument("--canonical-root", type=Path, default=Path("/srv/traiding_pilot/market/binance/spot/ETHUSDT/1m"))
    parser.add_argument("--cache-root", type=Path, default=Path("/var/tmp/traiding_pilot_market_cache"))
    parser.add_argument("--ssh-host", default="wanga@10.8.0.7")
    parser.add_argument("--ssh-key", type=Path, default=Path("/home/sergey/.ssh/id_to_nyx"))
    parser.add_argument("--initial-end", default="2024-06-30")
    parser.add_argument("--oos-blind", action="store_true", default=True)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8055)
    args = parser.parse_args()
    service = TimeframeBarService(
        symbol=args.symbol,
        canonical_root=args.canonical_root,
        cache_root=args.cache_root,
        ssh_host=args.ssh_host,
        ssh_key=args.ssh_key,
    )
    end = datetime.fromisoformat(args.initial_end).replace(tzinfo=timezone.utc)
    create_app(service, oos_blind=args.oos_blind, initial_end=end).run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
