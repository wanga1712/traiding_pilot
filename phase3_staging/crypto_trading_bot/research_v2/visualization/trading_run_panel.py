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


def _period_label(market: dict[str, Any] | None, *, compact: bool = False) -> str:
    if not market:
        return "—"
    start = str(market.get("start_time", ""))[:10]
    end = str(market.get("end_time", ""))[:10]
    inst = market.get("instrument", "—")
    if compact:
        return f"{inst} · {start} → {end}"
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


def _technical_meta_block(run: dict[str, Any] | None, run_index: dict[str, Any] | None = None) -> html.Div:
    row = run_index or {}
    strat = (run or {}).get("strategy") or {}
    exec_block = (run or {}).get("execution") or {}
    rows = [
        ("RUN_ID", row.get("run_id") or (run or {}).get("run_id")),
        ("STATUS", row.get("run_status") or (run or {}).get("run_status")),
        ("CREATED_AT", str(row.get("created_at") or (run or {}).get("created_at") or "—")[:19]),
        ("STRATEGY_VERSION", row.get("strategy_version") or strat.get("strategy_version")),
        ("EXECUTION_REALISM", exec_block.get("execution_realism_level")),
    ]
    return html.Div(
        [html.Div([html.Span(k), html.Strong(str(v or "—"))], className="metric") for k, v in rows],
        className="run-tech-meta",
    )


def build_run_selector(runs: list[dict[str, Any]], selected_id: str | None) -> html.Div:
    options = [{"label": r.get("strategy_name") or r["run_id"], "value": r["run_id"]} for r in runs]
    if len(runs) == 1:
        name = runs[0].get("strategy_name") or runs[0]["run_id"]
        return html.Div(
            [
                dcc.Dropdown(
                    id="trading-run-select",
                    options=options,
                    value=selected_id or runs[0]["run_id"],
                    clearable=False,
                    className="run-selector-dropdown run-selector-hidden",
                ),
                html.Div(name, className="run-single-strategy-label"),
            ],
            className="run-selector-row run-selector-single",
        )
    return html.Div(
        [
            html.Div("Прогон", className="run-selector-label"),
            dcc.Dropdown(
                id="trading-run-select",
                options=options,
                value=selected_id,
                clearable=True,
                placeholder="Выберите прогон",
                className="run-selector-dropdown",
            ),
        ],
        className="run-selector-row",
    )


def _human_composite_rows(composite: dict[str, Any] | None) -> list[tuple[str, str]]:
    if not composite:
        return []
    dma_raw = str(composite.get("dma") or "—")
    dma = dma_raw.replace("3x3", "3×3")
    if "display-aligned" in dma_raw.lower():
        dma = dma.replace("display-aligned", "").replace("  ", " ").strip(" ,")
        dma = f"{dma}, смещение 3" if dma else "3×3, смещение 3"
    stoch = str(composite.get("stoch") or "—")
    conf = composite.get("confirmation_window")
    expire = composite.get("signal_expiration")
    return [
        ("DMA", dma),
        ("Stochastic", stoch),
        ("Окно подтверждения", f"{conf} свечи" if conf is not None else "—"),
        ("Срок сигнала", f"{expire} свечей" if expire is not None else "—"),
    ]


def _metric_row(label: str, value: str) -> html.Div:
    return html.Div([html.Span(label), html.Strong(value)], className="metric")


def _research_details_block(
    run: dict[str, Any],
    research: dict[str, Any],
    *,
    run_index: dict[str, Any] | None,
) -> html.Details:
    row = run_index or {}
    strat = run.get("strategy") or {}
    exec_block = run.get("execution") or {}
    composite_rows = _human_composite_rows(research.get("best_human_composite"))

    inner = html.Div(
        [
            html.Div("Метрики исследования", className="run-section-title"),
            html.Div(
                [
                    _metric_row("Precision", str(research.get("precision", "—"))),
                    _metric_row("Recall", str(research.get("recall", "—"))),
                    _metric_row("FPR", str(research.get("false_positive_rate", "—"))),
                    _metric_row("Remaining wave", str(research.get("remaining_wave_fraction", "—"))),
                ],
                className="run-research-metrics-list",
            ),
            html.Div("Параметры стратегии", className="run-section-title"),
            html.Div([_metric_row(k, v) for k, v in composite_rows], className="run-research-metrics-list")
            if composite_rows
            else html.Div("—", className="run-empty-text"),
            html.Div("Техническая информация", className="run-section-title"),
            html.Div(
                [
                    _metric_row("RUN_ID", str(row.get("run_id") or run.get("run_id") or "—")),
                    _metric_row("STATUS", str(row.get("run_status") or run.get("run_status") or "—")),
                    _metric_row("CREATED_AT", str(row.get("created_at") or run.get("created_at") or "—")[:19]),
                    _metric_row("STRATEGY_VERSION", str(row.get("strategy_version") or strat.get("strategy_version") or "—")),
                    _metric_row("EXECUTION_REALISM", str(exec_block.get("execution_realism_level") or "—")),
                ],
                className="run-research-metrics-list",
            ),
        ],
        className="run-research-inner",
    )
    return html.Details(
        [html.Summary("Посмотреть исследование"), inner],
        open=False,
        className="run-details-block run-research-details",
    )


def _cost_breakdown_section(cost_items: list[tuple[str, str, bool]]) -> html.Div:
    return html.Div(
        [
            html.Div("Расходы", className="run-section-title"),
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
        ],
        className="run-cost-section",
    )


def _details_section(
    run: dict[str, Any],
    *,
    run_index: dict[str, Any] | None,
    rec_status: str,
    perf: dict[str, Any],
    costs: dict[str, Any],
    include_tabs: bool = True,
) -> html.Details:
    children: list[Any] = [
        html.Summary("Подробнее"),
        _technical_meta_block(run, run_index),
    ]
    if rec_status != "NOT_AVAILABLE":
        children.append(
            html.Div(
                f"Сверка экономики: {rec_status}",
                className="reconciliation-line "
                + ("rec-pass" if rec_status == "PASS" else "rec-fail" if rec_status == "FAIL" else "rec-na"),
            )
        )
    children.append(
        html.Div(
            [
                html.Span(f"Win rate {perf.get('win_rate', '—')}"),
                html.Span(f"Profit factor {perf.get('profit_factor', '—')}"),
            ],
            className="run-secondary-metrics",
        )
    )
    if include_tabs:
        children.append(
            dcc.Tabs(
                id="run-detail-tabs",
                value="trades",
                children=[
                    dcc.Tab(label="Сделки", value="trades", children=[_trades_tab(run)]),
                    dcc.Tab(label="Расходы", value="costs", children=[_costs_tab(costs, perf)]),
                    dcc.Tab(label="Ликвидации", value="liquidations", children=[_liquidations_tab(run)]),
                    dcc.Tab(label="Параметры", value="parameters", children=[_parameters_tab(run)]),
                ],
                className="run-detail-tabs",
            )
        )
    return html.Details(children, open=False, className="run-details-block")


def build_historical_run_panel(
    run: dict[str, Any] | None,
    *,
    runs_available: bool,
    run_index: dict[str, Any] | None = None,
) -> html.Div:
    if not runs_available or run is None:
        return html.Div(
            [
                html.Div("Исторический прогон", className="run-panel-title"),
                html.Div("Торговый прогон ещё не выполнен", className="run-empty-title"),
                html.P(
                    "Здесь появятся результаты после запуска симулятора исполнения.",
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
    research = run.get("research_metrics") or {}
    rec = reconcile_run(run)

    if status == "RUNNING":
        return html.Div(
            [
                html.Div("Исторический прогон", className="run-panel-title"),
                html.Div(strat.get("strategy_name", "—"), className="run-strategy-name run-strategy-name-lg"),
                html.Div(_period_label(market, compact=True), className="run-period"),
                html.Div("Прогон выполняется", className="run-running-banner"),
                html.P("Промежуточный результат не показывается как финальный.", className="run-empty-text"),
            ],
            className="historical-run-panel running",
            id="historical-run-panel",
        )

    if status == "FAILED":
        return html.Div(
            [
                html.Div("Исторический прогон", className="run-panel-title"),
                html.Div(strat.get("strategy_name", "—"), className="run-strategy-name run-strategy-name-lg"),
                html.Div("Прогон завершился с ошибкой", className="run-empty-title"),
                html.P("Финальный результат недоступен.", className="run-empty-text"),
            ],
            className="historical-run-panel failed",
            id="historical-run-panel",
        )

    if structural:
        return html.Div(
            [
                html.Div("Исторический прогон", className="run-panel-title"),
                html.Div(strat.get("strategy_name", "—"), className="run-strategy-name run-strategy-name-lg"),
                html.Div(_period_label(market, compact=True), className="run-period run-period-lg"),
                html.Div("Торговый прогон ещё не выполнен", className="structural-headline"),
                html.P(
                    "Эта стратегия пока проверялась только на поиск разворотов. "
                    "Баланс, сделки, комиссии и ликвидации будут рассчитаны торговым симулятором.",
                    className="run-empty-text structural-support",
                ),
                _research_details_block(run, research, run_index=run_index),
            ],
            className="historical-run-panel structural",
            id="historical-run-panel",
        )

    # Completed monetary run — primary screen only
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
    rec_status = rec.get("ECONOMIC_RECONCILIATION_STATUS", "NOT_AVAILABLE")

    return html.Div(
        [
            html.Div("Исторический прогон", className="run-panel-title"),
            html.Div(strat.get("strategy_name", "—"), className="run-strategy-name run-strategy-name-lg"),
            html.Div(_period_label(market, compact=True), className="run-period run-period-lg"),
            html.Div(cards, className="run-summary-grid"),
            html.Div(
                dcc.Graph(figure=fig, config={"displayModeBar": False})
                if fig
                else html.Div("Кривая капитала недоступна", className="run-empty-text"),
                className="run-equity-wrap",
            ),
            _cost_breakdown_section(cost_items),
            _details_section(
                run,
                run_index=run_index,
                rec_status=rec_status,
                perf=perf,
                costs=costs,
                include_tabs=True,
            ),
        ],
        className="historical-run-panel completed",
        id="historical-run-panel",
    )


def _trades_tab(run: dict[str, Any]) -> html.Div:
    trades = run.get("trades") or []
    if not trades:
        return html.Div("Нет данных по сделкам.", className="run-tab-body")
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
