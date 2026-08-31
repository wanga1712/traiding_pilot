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
    INITIAL_CHART_TIMEFRAME,
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
from crypto_trading_bot.research_v2.visualization.dinapoli_live import default_dinapoli_session
from crypto_trading_bot.research_v2.visualization.zigzag_live import (
    DEFAULT_ZIGZAG_BACKSTEP,
    DEFAULT_ZIGZAG_DEPTH,
    DEFAULT_ZIGZAG_DEVIATION,
    build_zigzag_payload,
    default_zigzag_session,
)
from crypto_trading_bot.research_v2.trading_runs.api import register_trading_run_api
from crypto_trading_bot.research_v2.trading_runs.repository import FileTradingRunRepository, TradingRunRepository
from crypto_trading_bot.research_v2.visualization.trading_run_panel import build_historical_run_panel, build_run_selector


def _short_date(value) -> str:
    if not value or value == "—":
        return "—"
    text = str(value)
    return text[:10] if len(text) >= 10 else text


def side_panel(session: dict, chart_state: dict, oos_blind: bool) -> html.Div:
    from crypto_trading_bot.research_v2.visualization.dinapoli_live import build_dinapoli_payload

    zz = build_zigzag_payload(chart_state.get("candles") or [], session)
    dn = build_dinapoli_payload(chart_state.get("candles") or [], session)
    rows = [
        ("CHART TF", chart_state.get("timeframe", "—")),
        ("ZIGZAG", zz.get("label", "—")),
        ("PIVOTS", zz.get("confirmed_count", 0)),
        ("CURRENT", (zz.get("current") or {}).get("kind", "—")),
    ]
    info = dn.get("info")
    if session.get("dinapoli_enabled") and info:
        rows += [
            ("ABC INDEX", f"{info['window_index']}/{info['window_count']-1}"),
            ("ABC WINDOW", f"{info['window_index']+1}/{info['window_count']}"),
            ("AB", f"{info['ab']:.4f}"),
            ("COP", f"{info['cop']:.4f}"),
            ("OP", f"{info['op']:.4f}"),
            ("XOP", f"{info['xop']:.4f}"),
            ("D", f"{info['d']['price']:.4f}"),
            ("R", f"{info['r']:.4f}"),
            ("NEAREST", info["nearest"]),
            ("A", f"{info['a']['kind']} {str(info['a']['time'])[:16]}"),
            ("B", f"{info['b']['kind']} {str(info['b']['time'])[:16]}"),
            ("C", f"{info['c']['kind']} {str(info['c']['time'])[:16]}"),
            ("Dtime", f"{info['d']['kind']} {str(info['d']['time'])[:16]}"),
        ]
    rows += [
        ("MODE", session.get("mode") or "NAVIGATE"),
        ("ANNOTATION TF", session.get("annotation_timeframe", "—")),
        ("POINTS", len(session["points"])),
    ]
    return html.Div([html.Div([html.Span(key), html.Strong(str(value))], className="metric") for key, value in rows])


def compact_banner(chart_state: dict, viewport: dict | None, session: dict) -> html.Div:
    audit = dict(chart_state.get("audit", {}))
    if viewport:
        for key in ("actual_visible_ohlc_bars", "visible_from_time", "visible_to_time", "anchor_timestamp"):
            if key in viewport:
                audit[key] = viewport[key]
    chart_tf = chart_state.get("timeframe", "—")
    zz = build_zigzag_payload(chart_state.get("candles") or [], session)
    y_mode = session.get("price_y_mode", "lock").upper()
    y_label = "LOCKED" if y_mode == "LOCK" else ("AUTO" if y_mode == "AUTO" else y_mode)
    current = zz.get("current")
    current_label = f"{current['kind']}@{str(current.get('timestamp', ''))[:16]}" if current else "—"
    spans = [
        html.Span(f"TF: {chart_tf}"),
        html.Span(f"ZIGZAG={zz.get('label', '—')}"),
        html.Span(f"PIVOTS={zz.get('confirmed_count', 0)}"),
        html.Span(f"CURRENT={current_label}"),
        html.Span(f"Visible: {audit.get('actual_visible_ohlc_bars', '—')}"),
        html.Span(f"Y: {y_label}"),
    ]
    return html.Div(spans, className="audit-banner compact-banner")


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
    run_repository: TradingRunRepository | None = None,
    trading_runs_root: Path | None = None,
):
    store = store or S7PostgresAnnotationStore()
    if run_repository is None:
        root = trading_runs_root or Path("artifacts/TRADING-RESEARCH-COCKPIT-FOUNDATION-1/trading_runs_store")
        run_repository = FileTradingRunRepository(root)
    app = Dash(
        __name__,
        assets_folder=str(Path(__file__).with_name("assets")),
        suppress_callback_exceptions=True,
        external_scripts=["https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"],
    )
    chart_state = load_initial_window(
        service,
        default_chart_state(
            service.symbol,
            INITIAL_CHART_TIMEFRAME,
            initial_end or datetime(2024, 6, 30, tzinfo=timezone.utc),
        ),
    )
    chart_state["apply_viewport"] = True
    chart_state["fit_window_y"] = True
    chart_state["anchor_timestamp"] = chart_state.get("viewport_end")
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
        # Annotation TF is independent of chart TF; unset until first expert point.
        "annotation_timeframe": None,
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
        "message": "ZIGZAG LIVE — tune deviation/depth/backstep then APPLY",
        "debug": {},
        **default_zigzag_session(),
        **default_dinapoli_session(),
    }
    initial_payload = build_chart_payload(chart_state, session, oos_blind)
    run_list = run_repository.list_runs()
    initial_run_id = run_list[0]["run_id"] if run_list else None
    initial_run = run_repository.get_run(initial_run_id) if initial_run_id else None
    register_trading_run_api(app.server, run_repository)
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
                                value=INITIAL_CHART_TIMEFRAME,
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
                                "CLASSIC ZIGZAG LIVE — auto swings on current TF candles",
                                className="mode-banner",
                            ),
                            html.Div(id="audit-banner", className="audit-banner-wrap"),
                            html.Div(id="debug-panel-wrap"),
                            html.Div(
                                [
                                    html.Div(
                                        [
                                            html.Span("DEV%", className="zz-label"),
                                            dcc.Input(
                                                id="zz-deviation",
                                                type="number",
                                                value=DEFAULT_ZIGZAG_DEVIATION,
                                                step=0.25,
                                                min=0.1,
                                                className="zz-input",
                                            ),
                                            html.Span("DEPTH", className="zz-label"),
                                            dcc.Input(
                                                id="zz-depth",
                                                type="number",
                                                value=DEFAULT_ZIGZAG_DEPTH,
                                                step=1,
                                                min=1,
                                                className="zz-input",
                                            ),
                                            html.Span("BACK", className="zz-label"),
                                            dcc.Input(
                                                id="zz-backstep",
                                                type="number",
                                                value=DEFAULT_ZIGZAG_BACKSTEP,
                                                step=1,
                                                min=0,
                                                className="zz-input",
                                            ),
                                            html.Button("APPLY ZIGZAG", id="zz-apply", className="zz-apply"),
                                            dcc.Checklist(
                                                id="zz-show",
                                                options=[{"label": "SHOW ZIGZAG", "value": "show"}],
                                                value=["show"],
                                                className="zz-show",
                                            ),
                                            dcc.Checklist(
                                                id="dn-show",
                                                options=[{"label": "SHOW DINAPOLI", "value": "show"}],
                                                value=[],
                                                className="zz-show",
                                            ),
                                            html.Button("PREV ABC", id="dn-prev", className="dn-nav"),
                                            html.Button("NEXT ABC", id="dn-next", className="dn-nav"),
                                        ],
                                        className="tool-group zigzag-controls",
                                    ),
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
                            html.Div(id="trading-run-selector-wrap", children=build_run_selector(run_list, initial_run_id)),
                            html.Div(
                                id="historical-run-panel-wrap",
                                children=build_historical_run_panel(initial_run, runs_available=bool(run_list)),
                            ),
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
                            dcc.Input(id="anchor-bridge", type="text", style={"display": "none"}),
                            dcc.Input(id="relayout-bridge", type="text", style={"display": "none"}),
                            dcc.Store(id="tf-change-request", data=None),
                            dcc.Store(id="zz-apply-request", data=None),
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

    app.clientside_callback(
        """
        function(n) {
            if (!n) {
                return window.dash_clientside.no_update;
            }
            const devEl = document.getElementById('zz-deviation');
            const depthEl = document.getElementById('zz-depth');
            const backEl = document.getElementById('zz-backstep');
            return {
                deviation: devEl ? parseFloat(devEl.value) : null,
                depth: depthEl ? parseInt(depthEl.value, 10) : null,
                backstep: backEl ? parseInt(backEl.value, 10) : null,
                nonce: Date.now()
            };
        }
        """,
        Output("zz-apply-request", "data"),
        Input("zz-apply", "n_clicks"),
        prevent_initial_call=True,
    )

    @app.callback(
        Output("session", "data", allow_duplicate=True),
        Input("zz-apply-request", "data"),
        Input("zz-show", "value"),
        State("session", "data"),
        prevent_initial_call=True,
    )
    def on_zigzag_controls(apply_req, show_value, session):
        trigger = callback_context.triggered_id
        session = dict(session or {})
        if trigger == "zz-show":
            session["zigzag_enabled"] = "show" in (show_value or [])
            session["zigzag_revision"] = int(session.get("zigzag_revision", 0)) + 1
            session["message"] = "ZIGZAG " + ("ON" if session["zigzag_enabled"] else "OFF")
            return session
        if not apply_req:
            return no_update
        try:
            deviation = apply_req.get("deviation")
            depth = apply_req.get("depth")
            backstep = apply_req.get("backstep")
            session["zigzag_deviation"] = float(deviation if deviation is not None else DEFAULT_ZIGZAG_DEVIATION)
            session["zigzag_depth"] = max(1, int(depth if depth is not None else DEFAULT_ZIGZAG_DEPTH))
            session["zigzag_backstep"] = max(0, int(backstep if backstep is not None else DEFAULT_ZIGZAG_BACKSTEP))
        except (TypeError, ValueError):
            session["message"] = "ZIGZAG PARAMS INVALID"
            return session
        if session["zigzag_deviation"] <= 0:
            session["message"] = "ZIGZAG DEVIATION MUST BE > 0"
            return session
        session["zigzag_enabled"] = True
        session["zigzag_revision"] = int(session.get("zigzag_revision", 0)) + 1
        session["dinapoli_revision"] = int(session.get("dinapoli_revision", 0)) + 1
        session["message"] = (
            f"ZIGZAG APPLY {session['zigzag_deviation']:g}% / "
            f"D{session['zigzag_depth']} / B{session['zigzag_backstep']}"
        )
        return session

    @app.callback(
        Output("session", "data", allow_duplicate=True),
        Input("dn-show", "value"),
        Input("dn-prev", "n_clicks"),
        Input("dn-next", "n_clicks"),
        State("session", "data"),
        State("chart-state", "data"),
        prevent_initial_call=True,
    )
    def on_dinapoli_nav(show_value, prev_clicks, next_clicks, session, chart_state):
        from crypto_trading_bot.research_v2.visualization.dinapoli_live import build_dinapoli_payload

        trigger = callback_context.triggered_id
        session = dict(session or {})
        if trigger == "dn-show":
            session["dinapoli_enabled"] = "show" in (show_value or [])
            session["dinapoli_revision"] = int(session.get("dinapoli_revision", 0)) + 1
            session["message"] = "DINAPOLI " + ("ON" if session["dinapoli_enabled"] else "OFF")
            return session
        # Ensure enabled when navigating.
        session["dinapoli_enabled"] = True
        # Probe window count via payload builder.
        probe = build_dinapoli_payload((chart_state or {}).get("candles") or [], {**session, "dinapoli_enabled": True})
        count = int(probe.get("window_count") or 0)
        idx = int(session.get("dinapoli_window_index") or 0)
        if count <= 0:
            session["message"] = "DINAPOLI: need ≥4 confirmed ZigZag pivots"
            session["dinapoli_revision"] = int(session.get("dinapoli_revision", 0)) + 1
            return session
        if trigger == "dn-prev":
            idx = (idx - 1) % count
        elif trigger == "dn-next":
            idx = (idx + 1) % count
        session["dinapoli_window_index"] = idx
        session["dinapoli_revision"] = int(session.get("dinapoli_revision", 0)) + 1
        info = probe.get("info") or {}
        # Rebuild info for new index
        session2 = {**session}
        info2 = build_dinapoli_payload((chart_state or {}).get("candles") or [], session2).get("info") or info
        session["message"] = (
            f"ABC {idx+1}/{count} · R={info2.get('r', float('nan')):.3f} · NEAREST={info2.get('nearest', '—')}"
        )
        return session

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
        State("notes", "value"),
        State("session", "data"),
        State("chart-state", "data"),
        prevent_initial_call=True,
    )
    def mutate(add, move, delete, undo, clear, snap_free, snap_high, snap_low, evaluate, save, auto_y, lock_y, fit_window, clicked, show_geometry, selected_index, window_index, notes, session, chart_state):
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
        if trigger == "add-point":
            if session.get("points") and chart_state.get("timeframe") != session.get("annotation_timeframe"):
                session["message"] = (
                    f"ADD blocked on {chart_state.get('timeframe')}: "
                    f"annotation SOURCE_TF={session.get('annotation_timeframe')} — switch back to annotate"
                )
                return session, chart_state
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
                    if session.get("points") and chart_state.get("timeframe") != session.get("annotation_timeframe"):
                        session["message"] = (
                            f"ADD blocked on {chart_state.get('timeframe')}: "
                            f"annotation SOURCE_TF={session.get('annotation_timeframe')}"
                        )
                    else:
                        if not session.get("points"):
                            session["annotation_timeframe"] = chart_state.get("timeframe")
                        session = add_or_move_point(
                            session,
                            event,
                            candles,
                            session.get("annotation_timeframe", chart_state["timeframe"]),
                        )
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

    app.clientside_callback(
        """
        function(tf) {
            if (!tf) {
                return window.dash_clientside.no_update;
            }
            let anchor = null;
            if (window.__forceAnchorIso) {
                anchor = window.__forceAnchorIso;
            } else if (window.lastCrosshair && window.lastCrosshair.time) {
                anchor = window.lastCrosshair.time;
            } else {
                try {
                    const el = document.getElementById('anchor-bridge');
                    if (el && el.value) {
                        const parsed = JSON.parse(el.value);
                        anchor = parsed.time || parsed.anchor_timestamp || null;
                    }
                } catch (err) {}
            }
            if (!anchor && window.getTimeframeDiagnostics) {
                const d = window.getTimeframeDiagnostics();
                if (d) {
                    anchor = d.viewport_center_timestamp || d.anchor_timestamp || null;
                }
            }
            return { timeframe: tf, anchor: anchor, nonce: Date.now() };
        }
        """,
        Output("tf-change-request", "data"),
        Input("timeframe", "value"),
        prevent_initial_call=True,
    )

    @app.callback(
        Output("session", "data", allow_duplicate=True),
        Output("chart-state", "data", allow_duplicate=True),
        Input("tf-change-request", "data"),
        State("session", "data"),
        State("chart-state", "data"),
        prevent_initial_call=True,
    )
    def on_timeframe_change(request, session, chart_state):
        if not request or not request.get("timeframe"):
            return no_update, no_update
        timeframe = request["timeframe"]
        chart_state = dict(chart_state or {})
        session = dict(session or {})
        old_tf = chart_state.get("timeframe")
        if timeframe == old_tf:
            session["message"] = f"CHART TF already {timeframe} — no reload"
            return session, chart_state

        anchor = None
        if session.get("selected_index") is not None and session.get("points"):
            try:
                anchor = session["points"][int(session["selected_index"])]["timestamp"]
            except (IndexError, TypeError, ValueError):
                anchor = None
        if not anchor:
            anchor = request.get("anchor")

        chart_state = reload_timeframe(
            service,
            chart_state,
            timeframe,
            anchor_timestamp=anchor,
            visible_bars=DEFAULT_VISIBLE_BARS,
        )
        session["price_y_mode"] = "lock"
        diag = chart_state.get("tf_change_diag") or {}
        session["message"] = (
            f"TF_CHANGE_FROM={diag.get('tf_change_from')} TF_CHANGE_TO={diag.get('tf_change_to')} "
            f"OLD_CANDLE_COUNT={diag.get('old_candle_count')} NEW_CANDLE_COUNT={diag.get('new_candle_count')} "
            f"OLD_FIRST_INTERVAL={diag.get('old_first_interval')} NEW_FIRST_INTERVAL={diag.get('new_first_interval')} "
            f"MARKET_DATA_REVISION_BEFORE={diag.get('market_data_revision_before')} "
            f"MARKET_DATA_REVISION_AFTER={diag.get('market_data_revision_after')} "
            f"VISIBLE≈{chart_state.get('viewport_count', DEFAULT_VISIBLE_BARS)} "
            f"ANCHOR={str(chart_state.get('anchor_timestamp', '—'))[:16]} · Y FIT→LOCK"
        )
        session["debug"] = {**(session.get("debug") or {}), **diag}
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
            side_panel(session, merged, oos_blind),
            [{"label": f"P{p['point_index']}", "value": i} for i, p in enumerate(session.get("points", []))],
            [{"label": e["window_label"], "value": i} for i, e in enumerate(session.get("evaluations", []))],
            len(session.get("points", [])) < 6,
            merged,
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

    @app.callback(
        Output("historical-run-panel-wrap", "children"),
        Output("trading-run-selector-wrap", "children"),
        Input("trading-run-select", "value"),
        prevent_initial_call=False,
    )
    def on_trading_run_selected(run_id):
        runs = run_repository.list_runs()
        panel = build_historical_run_panel(
            run_repository.get_run(run_id) if run_id else None,
            runs_available=bool(runs),
        )
        selector = build_run_selector(runs, run_id)
        return panel, selector

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
