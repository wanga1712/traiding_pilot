"""Trading run result panel — below chart."""
from __future__ import annotations

from typing import Any

import plotly.graph_objects as go
from dash import dcc, html

from crypto_trading_bot.research_v2.trading_runs.null_semantics import (
    css_class_for_number,
    format_currency,
    format_int,
    format_pct,
    format_signed_currency,
    is_available,
    structural_only_blocks_monetary,
)
from crypto_trading_bot.research_v2.trading_runs.reconciliation import reconcile_run


def _period_label(market: dict[str, Any] | None) -> str:
    if not market:
        return "—"
    start = str(market.get("start_time", ""))[:10]
    end = str(market.get("end_time", ""))[:10]
    inst = market.get("instrument", "—")
    cat = market.get("category", "")
    exch = market.get("exchange", "")
    return f"{inst} {cat} | {exch} | {start} → {end}"


def _status_badge(status: str | None) -> html.Span:
    cls = "run-status"
    if status == "COMPLETED":
        cls += " status-completed"
    elif status == "RUNNING":
        cls += " status-running"
    elif status == "FAILED":
        cls += " status-failed"
    elif status in ("PENDING", "INVALID"):
        cls += " status-pending"
    return html.Span(status or "—", className=cls)


def _summary_card(label: str, value: str, css: str = "") -> html.Div:
    return html.Div(
        [html.Div(label, className="run-card-label"), html.Div(value, className=f"run-card-value {css}")],
        className="run-summary-card",
    )


def _equity_figure(curve: list[dict[str, Any]] | None) -> go.Figure | None:
    if not curve:
        return None
    xs = [p.get("timestamp") for p in curve]
    ys = [p.get("equity") for p in curve]
    fig = go.Figure(
        data=[go.Scatter(x=xs, y=ys, mode="lines", line=dict(color="#26a69a", width=2), name="Equity")],
    )
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#131722",
        plot_bgcolor="#131722",
        margin=dict(l=40, r=12, t=8, b=28),
        height=180,
        xaxis=dict(showgrid=False, color="#787b86"),
        yaxis=dict(showgrid=True, gridcolor="#2a2e39", color="#787b86"),
        showlegend=False,
    )
    return fig


def build_run_selector(runs: list[dict[str, Any]], selected_id: str | None) -> html.Div:
    options = [{"label": f"{r['run_id']} ({r.get('run_status')})", "value": r["run_id"]} for r in runs]
    selected = next((r for r in runs if r["run_id"] == selected_id), None)
    meta = None
    if selected:
        meta = html.Div(
            [
                html.Div([html.Span("RUN_ID"), selected.get("run_id", "—")]),
                html.Div([html.Span("STATUS"), selected.get("run_status", "—")]),
                html.Div([html.Span("CREATED_AT"), str(selected.get("created_at", "—"))[:19]]),
                html.Div([html.Span("STRATEGY_VERSION"), selected.get("strategy_version", "—")]),
            ],
            className="run-selector-meta",
        )
    return html.Div(
        [
            html.Div("RUN", className="run-selector-label"),
            dcc.Dropdown(
                id="trading-run-select",
                options=options,
                value=selected_id,
                clearable=True,
                placeholder="Select run",
                className="run-selector-dropdown",
            ),
            meta,
        ],
        className="run-selector-row",
    )


def build_historical_run_panel(run: dict[str, Any] | None, *, runs_available: bool) -> html.Div:
    if not runs_available or run is None:
        return html.Div(
            [
                html.Div("HISTORICAL RUN RESULT", className="run-panel-title"),
                html.Div("NO EXECUTION RUN AVAILABLE", className="run-empty-title"),
                html.P(
                    "Historical execution results will appear here after a simulator run.",
                    className="run-empty-text",
                ),
            ],
            className="historical-run-panel empty",
            id="historical-run-panel",
        )

    status = run.get("run_status")
    structural = structural_only_blocks_monetary(run)
    strat = run.get("strategy") or {}
    market = run.get("market") or {}
    cap = run.get("capital") or {}
    perf = run.get("performance") or {}
    costs = run.get("costs") or {}
    exec_block = run.get("execution") or {}
    research = run.get("research_metrics") or {}
    rec = reconcile_run(run)

    if status == "RUNNING":
        return html.Div(
            [
                html.Div("HISTORICAL RUN RESULT", className="run-panel-title"),
                html.Div(
                    [
                        html.Div(strat.get("strategy_name", "—"), className="run-strategy-name"),
                        html.Div(_period_label(market), className="run-period"),
                        _status_badge(status),
                    ],
                    className="run-header-row",
                ),
                html.Div("RUN IN PROGRESS", className="run-running-banner"),
                html.P("Partial equity is not shown as a final result.", className="run-empty-text"),
            ],
            className="historical-run-panel running",
            id="historical-run-panel",
        )

    if status == "FAILED":
        return html.Div(
            [
                html.Div("HISTORICAL RUN RESULT", className="run-panel-title"),
                html.Div(strat.get("strategy_name", "—"), className="run-strategy-name"),
                _status_badge(status),
                html.P("This run failed before producing a completed result.", className="run-empty-text"),
            ],
            className="historical-run-panel failed",
            id="historical-run-panel",
        )

    if structural:
        return html.Div(
            [
                html.Div("HISTORICAL RUN RESULT", className="run-panel-title"),
                html.Div(
                    [
                        html.Div(strat.get("strategy_name", "—"), className="run-strategy-name"),
                        html.Div(_period_label(market), className="run-period"),
                        _status_badge(status),
                        html.Span("STRUCTURAL ONLY", className="realism-badge structural"),
                    ],
                    className="run-header-row",
                ),
                html.Div(
                    "This is WHEN/structure research — not a monetary backtest. "
                    "Start/final balance and execution costs are not available.",
                    className="structural-notice",
                ),
                html.Div(
                    [
                        _summary_card("Precision", f"{research.get('precision', '—')}", ""),
                        _summary_card("Recall", f"{research.get('recall', '—')}", ""),
                        _summary_card("FPR", f"{research.get('false_positive_rate', '—')}", ""),
                        _summary_card("Remaining wave", f"{research.get('remaining_wave_fraction', '—')}", ""),
                    ],
                    className="run-summary-grid research",
                ),
                html.Details(
                    [
                        html.Summary("Research metrics"),
                        html.Pre(str(research.get("best_human_composite", {})), className="run-params-pre"),
                    ],
                    open=False,
                ),
            ],
            className="historical-run-panel structural",
            id="historical-run-panel",
        )

    # Completed monetary run
    start = cap.get("start_equity")
    final = cap.get("final_equity")
    net_ret = cap.get("net_return_pct")
    mdd = perf.get("max_drawdown_pct")
    trades = perf.get("trade_count")
    liq = perf.get("liquidation_count")
    liq_status = run.get("liquidation_data_status")

    cards = [
        _summary_card("START", format_currency(start), css_class_for_number(start)),
        _summary_card("FINAL", format_currency(final), css_class_for_number(final)),
        _summary_card("RETURN", format_pct(net_ret), css_class_for_number(net_ret)),
        _summary_card("TRADES", format_int(trades), ""),
        _summary_card("MAX DD", format_pct(mdd, signed=False) if mdd is not None else "—", css_class_for_number(mdd)),
        _summary_card(
            "LIQUIDATIONS",
            "—" if liq is None and liq_status == "NOT_AVAILABLE" else format_int(liq if liq is not None else 0),
            "",
        ),
    ]

    cost_items = [
        ("Gross trading PnL", format_signed_currency(perf.get("gross_pnl")), False),
        (
            "Trading fees",
            format_signed_currency(-float(costs.get("total_trading_fees")))
            if is_available(costs.get("total_trading_fees"))
            else "—",
            False,
        ),
        ("Funding (net)", format_signed_currency(costs.get("net_funding")), False),
        (
            "Spread",
            format_signed_currency(-float(costs.get("spread_cost"))) if is_available(costs.get("spread_cost")) else "—",
            False,
        ),
        (
            "Slippage",
            format_signed_currency(-float(costs.get("slippage_cost")))
            if is_available(costs.get("slippage_cost"))
            else "—",
            False,
        ),
        (
            "Liquidation losses",
            format_signed_currency(-float(costs.get("liquidation_cost")))
            if is_available(costs.get("liquidation_cost"))
            else "—",
            False,
        ),
        ("NET PnL", format_signed_currency(perf.get("net_pnl")), True),
    ]

    curve = run.get("equity_curve")
    fig = _equity_figure(curve)

    realism = exec_block.get("execution_realism_level", "—")
    rec_status = rec.get("ECONOMIC_RECONCILIATION_STATUS", "NOT_AVAILABLE")

    return html.Div(
        [
            html.Div("HISTORICAL RUN RESULT", className="run-panel-title"),
            html.Div(
                [
                    html.Div(strat.get("strategy_name", "—"), className="run-strategy-name"),
                    html.Div(_period_label(market), className="run-period"),
                    _status_badge(status),
                    html.Span(f"REALISM: {realism}", className="realism-badge"),
                ],
                className="run-header-row",
            ),
            html.Div(cards, className="run-summary-grid"),
            html.Div(
                dcc.Graph(figure=fig, config={"displayModeBar": False})
                if fig
                else html.Div("EQUITY CURVE NOT AVAILABLE", className="run-empty-text"),
                className="run-equity-wrap",
            ),
            html.Div(
                [
                    html.Div(
                        [html.Span(label), html.Strong(val, className="cost-val" + (" emphasis" if emph else ""))],
                        className="cost-row",
                    )
                    for label, val, emph in cost_items
                ],
                className="run-cost-breakdown",
            ),
            html.Div(
                f"Reconciliation: {rec_status}",
                className="reconciliation-line " + ("rec-pass" if rec_status == "PASS" else "rec-fail" if rec_status == "FAIL" else "rec-na"),
            ),
            html.Div(
                [
                    html.Span(f"Win rate {perf.get('win_rate', '—')}"),
                    html.Span(f"Profit factor {perf.get('profit_factor', '—')}"),
                ],
                className="run-secondary-metrics",
            ),
            dcc.Tabs(
                id="run-detail-tabs",
                value="trades",
                children=[
                    dcc.Tab(label="TRADES", value="trades", children=[_trades_tab(run)]),
                    dcc.Tab(label="COSTS", value="costs", children=[_costs_tab(costs, perf)]),
                    dcc.Tab(label="LIQUIDATIONS", value="liquidations", children=[_liquidations_tab(run)]),
                    dcc.Tab(label="RUN PARAMETERS", value="parameters", children=[_parameters_tab(run)]),
                ],
                className="run-detail-tabs",
            ),
        ],
        className="historical-run-panel completed",
        id="historical-run-panel",
    )


def _trades_tab(run: dict[str, Any]) -> html.Div:
    trades = run.get("trades") or []
    if not trades:
        return html.Div("No trade detail rows.", className="run-tab-body")
    return html.Div([html.Pre(str(t), className="run-params-pre") for t in trades[:20]], className="run-tab-body")


def _costs_tab(costs: dict[str, Any], perf: dict[str, Any]) -> html.Div:
    rows = [
        ("Maker/Taker fees (total)", costs.get("total_trading_fees")),
        ("Funding paid", costs.get("funding_paid")),
        ("Funding received", costs.get("funding_received")),
        ("Net funding", costs.get("net_funding")),
        ("Spread", costs.get("spread_cost")),
        ("Slippage", costs.get("slippage_cost")),
        ("Liquidation costs", costs.get("liquidation_cost")),
        ("TOTAL COSTS", costs.get("total_costs")),
    ]
    gross = perf.get("gross_pnl")
    total_costs = costs.get("total_costs")
    pct = None
    if is_available(gross) and is_available(total_costs) and gross > 0:
        pct = float(total_costs) / float(gross) * 100
    return html.Div(
        [
            html.Div([html.Span(k), html.Strong(format_signed_currency(v) if isinstance(v, (int, float)) else "—")], className="metric")
            for k, v in rows
        ]
        + ([html.Div(f"Costs as % of gross profit: {pct:.1f}%", className="run-secondary-metrics")] if pct is not None else []),
        className="run-tab-body",
    )


def _liquidations_tab(run: dict[str, Any]) -> html.Div:
    status = run.get("liquidation_data_status")
    liq_count = (run.get("performance") or {}).get("liquidation_count")
    if status == "ZERO_CONFIRMED" or liq_count == 0:
        return html.Div("NO LIQUIDATIONS", className="run-tab-body")
    if status == "NOT_AVAILABLE" or liq_count is None:
        return html.Div("LIQUIDATION DATA NOT AVAILABLE", className="run-tab-body")
    liqs = run.get("liquidations") or []
    return html.Div([html.Pre(str(x), className="run-params-pre") for x in liqs], className="run-tab-body")


def _parameters_tab(run: dict[str, Any]) -> html.Div:
    params = run.get("parameters") or {}
    exec_block = run.get("execution") or {}
    merged = {**params, **{f"execution.{k}": v for k, v in exec_block.items()}}
    return html.Pre(str(merged), className="run-params-pre")
