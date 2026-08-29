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
    RANGE_SHORTCUTS,
    add_or_move_point,
    apply_viewport_from_relayout,
    audit_panel_rows,
    build_chart_payload,
    default_chart_state,
    delete_point_at_click,
    load_initial_window,
    maybe_prepend_history,
    nearest_candle,
    reload_timeframe,
    set_visible_bar_count,
    sync_chart_state_from_relayout,
)


def _short_date(value) -> str:
    if not value or value == "—":
        return "—"
    text = str(value)
    return text[:10] if len(text) >= 10 else text


def side_panel(session: dict, chart_state: dict, oos_blind: bool) -> html.Div:
    rows = [
        ("MODE", session.get("mode") or "NAVIGATE"),
        ("SNAP", session.get("snap_mode", "FREE")),
        ("POINTS", len(session["points"])),
        *[(f"P{p['point_index']}", f"{p['timestamp'][:10]} · {p['price']}") for p in session["points"]],
    ]
    if not session["points"]:
        rows.append(("POINTS", "NOT SET"))
    if not oos_blind:
        evaluations = session.get("evaluations", [])
        selected = session.get("window_index")
        if evaluations and selected is not None:
            result = evaluations[int(selected)]
            rows += [
                ("WINDOW", result["window_label"]),
                ("CALCULATED COP", result["cop_price"]),
                ("CALCULATED OP", result["op_price"]),
                ("CALCULATED XOP", result["xop_price"]),
            ]
    return html.Div([html.Div([html.Span(key), html.Strong(str(value))], className="metric") for key, value in rows])


def compact_banner(chart_state: dict, viewport: dict | None, session: dict) -> html.Div:
    audit = dict(chart_state.get("audit", {}))
    if viewport:
        for key in ("actual_visible_ohlc_bars", "visible_from_time", "visible_to_time"):
            if key in viewport:
                audit[key] = viewport[key]
    mode = session.get("mode") or "NAVIGATE"
    snap = session.get("snap_mode", "FREE")
    y_mode = session.get("price_y_mode", "lock").upper()
    if y_mode == "LOCK":
        y_label = "LOCKED"
    elif y_mode == "AUTO":
        y_label = "AUTO"
    else:
        y_label = y_mode
    return html.Div(
        [
            html.Span(f"TF: {chart_state.get('timeframe', '—')}"),
            html.Span(f"Visible: {audit.get('actual_visible_ohlc_bars', '—')}"),
            html.Span(f"Range: {_short_date(audit.get('visible_from_time'))} → {_short_date(audit.get('visible_to_time'))}"),
            html.Span(f"Y: {y_label}"),
            html.Span(f"Snap: {snap}"),
            html.Span(f"Mode: {mode}"),
        ],
        className="audit-banner compact-banner",
    )


def debug_panel(chart_state: dict, viewport: dict | None) -> html.Details:
    audit = dict(chart_state.get("audit", {}))
    if viewport:
        audit.update({k: viewport[k] for k in viewport if k not in audit})
    rows = audit_panel_rows(audit)
    extra = [
        ("RAW_WHEEL", viewport.get("raw_wheel_event_count", "—") if viewport else "—"),
        ("APPLIED_WHEEL", viewport.get("applied_zoom_gesture_count", "—") if viewport else "—"),
        ("INDEX", f"{audit.get('bar_from', '—')}→{audit.get('bar_to', '—')}"),
        ("INVARIANT", audit.get("viewport_invariant", "—")),
    ]
    return html.Details(
        [
            html.Summary("Developer diagnostics"),
            html.Div(
                [html.Div([html.Span(k), html.Strong(str(v))], className="metric") for k, v in rows + extra],
                className="debug-panel-body",
            ),
        ],
        className="debug-panel",
        open=False,
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
    chart_state["fit_window_y"] = True
    viewport = {
        "bar_from": chart_state["bar_from"],
        "bar_to": chart_state["bar_to"],
        "visible_from_time": chart_state["viewport_start"],
        "visible_to_time": chart_state["viewport_end"],
        "actual_visible_ohlc_bars": chart_state["audit"]["actual_visible_ohlc_bars"],
        "shortcut_target": "NONE",
    }
    session = {
        "annotation_id": str(uuid.uuid4()),
        "annotation_timeframe": "4H",
        "points": [],
        "history": [],
        "mode": "ADD",
        "snap_mode": "FREE",
        "selected_index": None,
        "locked": False,
        "show_geometry": True,
        "price_y_mode": "lock",
        "evaluations": [],
        "window_index": None,
        "crosshair": None,
        "message": "ADD POINT: click chart to place P0",
        "debug": {},
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
                            html.Div(id="debug-panel-wrap"),
                            html.Div(
                                [
                                    html.Div(
                                        [
                                            html.Button("ADD POINT", id="add-point", className="point-tool active"),
                                            html.Button("MOVE / REPLACE", id="move-point", className="point-tool"),
                                            html.Button("DELETE POINT", id="delete-point", className="point-tool"),
                                            html.Button("UNDO", id="undo"),
                                        ],
                                        className="tool-group",
                                    ),
                                    html.Div(
                                        [
                                            html.Button("FREE", id="snap-free", className="snap-btn active"),
                                            html.Button("SNAP HIGH", id="snap-high", className="snap-btn"),
                                            html.Button("SNAP LOW", id="snap-low", className="snap-btn"),
                                        ],
                                        className="tool-group",
                                    ),
                                    html.Div(
                                        [
                                            html.Button("FIT WINDOW", id="fit-window", className="price-scale-btn active"),
                                            html.Button("LOCK Y", id="lock-y", className="price-scale-btn"),
                                            html.Button("AUTO Y", id="auto-y", className="price-scale-btn"),
                                        ],
                                        className="tool-group",
                                    ),
                                    html.Div(
                                        [html.Button(str(count), id=f"range-{count}", className="range-shortcut") for count in RANGE_SHORTCUTS],
                                        className="tool-group presets",
                                    ),
                                    html.Div(
                                        [
                                            dcc.Dropdown(id="point-select", placeholder="Select point", clearable=False),
                                            dcc.Input(id="notes", placeholder="Annotation notes", type="text"),
                                            html.Button("SAVE ANNOTATION", id="save"),
                                            html.Button("CLEAR UNSAVED", id="clear"),
                                        ],
                                        className="tool-group secondary",
                                    ),
                                    html.Button("EVALUATE ROLLING GEOMETRY", id="evaluate", style={"display": "none" if oos_blind else "inline-block"}),
                                    dcc.Checklist(
                                        [{"label": "SHOW MANUAL GEOMETRY", "value": "show"}],
                                        value=["show"] if not oos_blind else [],
                                        id="show-geometry",
                                        style={"display": "none" if oos_blind else "block"},
                                    ),
                                    dcc.Dropdown(id="window-select", placeholder="Rolling window", clearable=False, style={"display": "none" if oos_blind else "block"}),
                                ],
                                className="controls",
                            ),
                            html.Div(id="lwc-chart", className="tv-chart"),
                            html.Div(id="status", className="seedbar"),
                            dcc.Interval(id="status-tick", interval=300, n_intervals=0),
                            dcc.Store(id="session", data=session),
                            dcc.Store(id="chart-state", data=chart_state),
                            dcc.Store(id="viewport-store", data=viewport),
                            dcc.Input(id="chart-payload-bridge", type="text", value=json.dumps(initial_payload), style={"display": "none"}),
                            html.Div(id="chart-error-banner", className="chart-error-banner"),
                            html.Div(id="manual-click-applied", style={"display": "none"}),
                            dcc.Input(id="manual-click-bridge", type="text", style={"display": "none"}),
                            dcc.Input(id="crosshair-bridge", type="text", style={"display": "none"}),
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
            synced = sync_chart_state_from_relayout(chart_state, relayout)
            return viewport, synced
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
        chart_state["apply_viewport"] = True
        chart_state["viewport_count"] = bar_count
        chart_state["ui_revision"] = chart_state.get("ui_revision", 0) + 1
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
        Input("snap-free", "n_clicks"),
        Input("snap-high", "n_clicks"),
        Input("snap-low", "n_clicks"),
        Input("evaluate", "n_clicks"),
        Input("save", "n_clicks"),
        Input("auto-y", "n_clicks"),
        Input("lock-y", "n_clicks"),
        Input("fit-window", "n_clicks"),
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
    def mutate(add, move, delete, undo, clear, snap_free, snap_high, snap_low, evaluate, save, auto_y, lock_y, fit_window, clicked, show_geometry, selected_index, window_index, timeframe, notes, session, chart_state):
        trigger = callback_context.triggered_id
        candles = chart_state["candles"]
        chart_state = dict(chart_state)
        if trigger == "fit-window":
            session["price_y_mode"] = "lock"
            chart_state["fit_window_y"] = True
            chart_state["ui_revision"] = chart_state.get("ui_revision", 0) + 1
            session["message"] = "PRICE Y: FIT WINDOW (visible candles)"
            return session, chart_state
        if trigger == "auto-y":
            session["price_y_mode"] = "auto"
            chart_state["fit_window_y"] = False
            chart_state["ui_revision"] = chart_state.get("ui_revision", 0) + 1
            session["message"] = "PRICE Y: AUTO"
            return session, chart_state
        if trigger == "lock-y":
            session["price_y_mode"] = "lock"
            chart_state["fit_window_y"] = False
            chart_state["ui_revision"] = chart_state.get("ui_revision", 0) + 1
            session["message"] = "PRICE Y: LOCKED"
            return session, chart_state
        if trigger == "snap-free":
            session["snap_mode"] = "FREE"
            session["message"] = "SNAP: FREE CLICK"
            return session, chart_state
        if trigger == "snap-high":
            session["snap_mode"] = "HIGH"
            session["message"] = "SNAP: CANDLE HIGH"
            return session, chart_state
        if trigger == "snap-low":
            session["snap_mode"] = "LOW"
            session["message"] = "SNAP: CANDLE LOW"
            return session, chart_state
        if trigger == "timeframe":
            if session["points"] and timeframe != session.get("annotation_timeframe"):
                session["message"] = f"WARNING: unsaved points belong to {session.get('annotation_timeframe')}; change blocked"
                return session, chart_state
            chart_state = reload_timeframe(service, chart_state, timeframe)
            chart_state["apply_viewport"] = True
            chart_state["fit_window_y"] = True
            session["annotation_timeframe"] = timeframe
            session["message"] = f"TIMEFRAME RELOADED: {timeframe}"
            return session, chart_state
        if trigger == "add-point":
            session["mode"] = "ADD"
            session["message"] = "ADD POINT: CLICK CHART"
        elif trigger == "move-point":
            session["mode"] = "MOVE"
            session["selected_index"] = None
            session["message"] = "MOVE: CLICK POINT, THEN NEW LOCATION"
        elif trigger == "delete-point":
            session["mode"] = "DELETE"
            session["message"] = "DELETE: CLICK POINT TO REMOVE"
        elif trigger == "point-select":
            session["selected_index"] = selected_index
        elif trigger == "window-select":
            session["window_index"] = window_index
        elif trigger == "show-geometry":
            session["show_geometry"] = "show" in (show_geometry or [])
        elif trigger == "manual-click-bridge":
            try:
                event = json.loads(clicked)
                action = event.get("action", "place")
                if action == "select":
                    session["selected_index"] = event.get("point_index")
                    session["message"] = f"MOVE: P{event.get('point_index')} SELECTED"
                elif action == "delete":
                    session = delete_point_at_click(session, event, candles)
                else:
                    session = add_or_move_point(session, event, candles, session.get("annotation_timeframe", chart_state["timeframe"]))
            except Exception as exc:
                session["message"] = f"POINT ACTION FAILED: {exc}"
        elif trigger == "undo" and session["history"]:
            session["points"] = session["history"].pop()
            session["message"] = "UNDO COMPLETE"
        elif trigger == "clear":
            session.setdefault("history", []).append(deepcopy(session["points"]))
            session["points"] = []
            session["message"] = "UNSAVED POINTS CLEARED"
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
        Output("session", "data", allow_duplicate=True),
        Input("crosshair-bridge", "value"),
        State("session", "data"),
        prevent_initial_call=True,
    )
    def on_crosshair(raw, session):
        return no_update

    @app.callback(
        Output("chart-payload-bridge", "value"),
        Output("panel", "children"),
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
        viewport_count = chart_state_out.pop("viewport_count", None)
        fit_window_y = bool(chart_state_out.pop("fit_window_y", False))
        chart_state_out.pop("shortcut_target", None)
        merged = dict(chart_state_out)
        merged["apply_viewport"] = apply_viewport
        merged["fit_window_y"] = fit_window_y
        if apply_viewport and viewport_count is not None:
            merged["viewport_count"] = viewport_count
        payload = build_chart_payload(merged, session, oos_blind)
        return (
            json.dumps(payload),
            side_panel(session, chart_state, oos_blind),
            [{"label": f"P{p['point_index']}", "value": p["point_index"]} for p in session["points"]],
            [{"label": result["window_label"], "value": result["window_index"]} for result in session.get("evaluations", [])],
            len(session["points"]) < 6,
            chart_state_out,
        )

    app.clientside_callback(
        """
        function(n, session) {
            const base = (session && session.message) ? session.message : '';
            const c = window.lastCrosshair;
            if (!c) return base;
            const y = Number(c.cursor_price);
            const yText = Number.isFinite(y) ? y.toFixed(2) : c.cursor_price;
            return base + ' · Cursor ' + String(c.time).slice(0, 16) + ' · O=' + c.open + ' H=' + c.high + ' L=' + c.low + ' C=' + c.close + ' · Y=' + yText;
        }
        """,
        Output("status", "children"),
        Input("status-tick", "n_intervals"),
        State("session", "data"),
    )

    @app.callback(
        Output("add-point", "className"),
        Output("move-point", "className"),
        Output("delete-point", "className"),
        Output("snap-free", "className"),
        Output("snap-high", "className"),
        Output("snap-low", "className"),
        Output("fit-window", "className"),
        Output("lock-y", "className"),
        Output("auto-y", "className"),
        Input("session", "data"),
    )
    def style_tool_buttons(session):
        mode = session.get("mode")
        snap = session.get("snap_mode", "FREE")
        price_mode = session.get("price_y_mode", "lock")
        return (
            "point-tool active" if mode == "ADD" else "point-tool",
            "point-tool active" if mode == "MOVE" else "point-tool",
            "point-tool active" if mode == "DELETE" else "point-tool",
            "snap-btn active" if snap == "FREE" else "snap-btn",
            "snap-btn active" if snap == "HIGH" else "snap-btn",
            "snap-btn active" if snap == "LOW" else "snap-btn",
            "price-scale-btn",
            "price-scale-btn active" if price_mode == "lock" else "price-scale-btn",
            "price-scale-btn active" if price_mode == "auto" else "price-scale-btn",
        )

    @app.callback(Output("audit-banner", "children"), Input("chart-state", "data"), Input("viewport-store", "data"), Input("session", "data"))
    def render_audit(chart_state, viewport, session):
        return compact_banner(chart_state, viewport, session).children

    @app.callback(Output("debug-panel-wrap", "children"), Input("chart-state", "data"), Input("viewport-store", "data"))
    def render_debug(chart_state, viewport):
        return debug_panel(chart_state, viewport)

    app.clientside_callback(
        """
        function(raw) {
            return raw ? raw.slice(0, 64) : "";
        }
        """,
        Output("manual-click-applied", "children"),
        Input("manual-click-bridge", "value"),
    )

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
