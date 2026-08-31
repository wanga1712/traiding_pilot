from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from crypto_trading_bot.research_v2.trading_runs.fixtures import (
    ALL_FIXTURES,
    fixture_completed_realistic,
    fixture_reconciliation_fail,
    fixture_running,
    fixture_structural_only,
    fixture_unknown_liquidations,
    fixture_zero_liquidations,
)
from crypto_trading_bot.research_v2.trading_runs.null_semantics import (
    format_currency,
    format_int,
    is_available,
    structural_only_blocks_monetary,
)
from crypto_trading_bot.research_v2.trading_runs.reconciliation import reconcile_run
from crypto_trading_bot.research_v2.trading_runs.repository import FileTradingRunRepository
from crypto_trading_bot.research_v2.trading_runs.schema import validate_run
from crypto_trading_bot.research_v2.trading_runs.version import TRADING_RUN_RESULT_SCHEMA_VERSION
from crypto_trading_bot.research_v2.visualization.trading_run_panel import (
    _equity_figure,
    _liquidations_tab,
    build_historical_run_panel,
)


def test_schema_validation_pass_completed_fixture():
    run = fixture_completed_realistic()
    assert validate_run(run) == []


def test_null_vs_zero_semantics():
    assert format_currency(None) == "—"
    assert format_currency(0) == "$0.00"
    assert format_int(None) == "—"
    assert format_int(0) == "0"
    assert is_available(0) is True
    assert is_available(None) is False


def test_economic_reconciliation_pass():
    run = fixture_completed_realistic()
    rec = reconcile_run(run)
    assert rec["ECONOMIC_RECONCILIATION_STATUS"] == "PASS"


def test_reconciliation_failure_detection():
    run = fixture_reconciliation_fail()
    rec = reconcile_run(run)
    assert rec["ECONOMIC_RECONCILIATION_STATUS"] == "FAIL"
    assert validate_run(run) != []


def test_run_status_running_not_final():
    panel = build_historical_run_panel(fixture_running(), runs_available=True)
    assert "Прогон выполняется" in str(panel)


def test_structural_only_monetary_suppression():
    run = fixture_structural_only()
    assert structural_only_blocks_monetary(run) is True
    assert validate_run(run) == []
    panel = build_historical_run_panel(run, runs_available=True)
    text = str(panel)
    assert "Торговый прогон ещё не выполнен" in text
    assert "Посмотреть исследование" in text
    assert "поиск разворотов" in text
    assert "$100" not in text
    assert "START" not in text
    assert "Precision" not in text.split("Посмотреть исследование")[0]
    assert "RUN_ID" not in text.split("Посмотреть исследование")[0]
    assert "{" not in text.split("Посмотреть исследование")[0]


def test_equity_series_rendering():
    run = fixture_completed_realistic()
    fig = _equity_figure(run["equity_curve"])
    assert fig is not None
    assert len(fig.data[0].y) == 12
    assert _equity_figure(None) is None


def test_empty_state_rendering():
    panel = build_historical_run_panel(None, runs_available=False)
    text = str(panel)
    assert "Торговый прогон ещё не выполнен" in text
    assert "$0" not in text


def test_human_composite_rows():
    from crypto_trading_bot.research_v2.visualization.trading_run_panel import _human_composite_rows

    rows = _human_composite_rows(
        {"dma": "3x3 display-aligned", "stoch": "14/3/3", "confirmation_window": 3, "signal_expiration": 5}
    )
    assert rows[0][0] == "DMA"
    assert "3×3" in rows[0][1]
    assert rows[2][1] == "3 свечи"


def test_single_run_selector_deemphasized():
    from crypto_trading_bot.research_v2.visualization.trading_run_panel import build_run_selector

    panel = build_run_selector(
        [{"run_id": "R1", "strategy_name": "Test Strategy", "run_status": "COMPLETED"}],
        "R1",
    )
    text = str(panel)
    assert "run-selector-single" in text
    assert "Test Strategy" in text


def test_monetary_primary_layout():
    run = fixture_completed_realistic()
    panel = build_historical_run_panel(run, runs_available=True)
    text = str(panel)
    assert "START" in text and "FINAL" in text and "RETURN" in text
    assert "Расходы" in text
    assert "Подробнее" in text
    assert "ONE_MINUTE_EXECUTION" not in text.split("Подробнее")[0]


def test_trades_null_field_tolerance():
    run = fixture_completed_realistic()
    run["trades"] = [{"trade_id": "T1", "gross_pnl": None, "fees": None}]
    panel = build_historical_run_panel(run, runs_available=True)
    assert panel is not None


def test_liquidation_unavailable_vs_zero():
    zero = _liquidations_tab(fixture_zero_liquidations())
    unknown = _liquidations_tab(fixture_unknown_liquidations())
    assert "NO LIQUIDATIONS" in str(zero)
    assert "LIQUIDATION DATA NOT AVAILABLE" in str(unknown)


def test_repository_list_and_api_shape(tmp_path):
    run = fixture_structural_only()
    run["run_id"] = "STRUCTURAL_ARTIFACT_V1"
    (tmp_path / "STRUCTURAL_ARTIFACT_V1.json").write_text(json.dumps(run), encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps({"run_ids": ["STRUCTURAL_ARTIFACT_V1"]}), encoding="utf-8")
    repo = FileTradingRunRepository(tmp_path, include_fixtures=False)
    rows = repo.list_runs()
    assert len(rows) == 1
    assert rows[0]["run_id"] == "STRUCTURAL_ARTIFACT_V1"
    loaded = repo.get_run("STRUCTURAL_ARTIFACT_V1")
    assert loaded is not None
    assert loaded["execution"]["execution_realism_level"] == "STRUCTURAL_ONLY"


def test_api_endpoints(tmp_path):
    from crypto_trading_bot.research_v2.trading_runs.api import bp, init_repository
    from flask import Flask

    run = fixture_completed_realistic()
    run_id = "API_FIXTURE_V1"
    run["run_id"] = run_id
    (tmp_path / f"{run_id}.json").write_text(json.dumps(run), encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps({"run_ids": [run_id]}), encoding="utf-8")
    repo = FileTradingRunRepository(tmp_path, include_fixtures=False)
    init_repository(repo)

    app = Flask(__name__)
    app.register_blueprint(bp)
    client = app.test_client()

    list_resp = client.get("/api/trading-runs")
    assert list_resp.status_code == 200
    assert run_id in json.dumps(list_resp.get_json())

    detail = client.get(f"/api/trading-runs/{run_id}")
    assert detail.status_code == 200
    body = detail.get_json()
    assert body["reconciliation"]["ECONOMIC_RECONCILIATION_STATUS"] == "PASS"

    summary = client.get(f"/api/trading-runs/{run_id}/summary")
    assert summary.status_code == 200

    equity = client.get(f"/api/trading-runs/{run_id}/equity")
    assert equity.status_code == 200
    assert equity.get_json()["equity_curve"] is not None


def test_existing_chart_layout_regression():
    from datetime import datetime, timezone

    from crypto_trading_bot.research_v2.visualization.expert_app import create_app

    candle = {
        "open_time_utc": datetime(2024, 1, 1, tzinfo=timezone.utc).isoformat(),
        "close_time_utc": datetime(2024, 1, 2, tzinfo=timezone.utc).isoformat(),
        "open": "100",
        "high": "101",
        "low": "99",
        "close": "100",
        "volume": "1",
        "trade_count": 1,
    }
    service = MagicMock()
    service.symbol = "ETHUSDT"
    service.get_bars.return_value = [candle] * 120
    service.audit.return_value = {
        "interval_check": "PASS",
        "loaded_bars": 120,
        "actual_visible_ohlc_bars": 100,
    }
    repo = FileTradingRunRepository(Path("/tmp/nonexistent_trading_runs_empty"), include_fixtures=False)
    app = create_app(service, run_repository=repo, oos_blind=True)
    layout = str(app.layout)
    assert "lwc-chart" in layout
    assert "historical-run-panel-wrap" in layout
    assert "trading-run-select" in layout


def test_all_fixtures_have_schema_version():
    for factory in ALL_FIXTURES.values():
        run = factory()
        assert run["schema_version"] == TRADING_RUN_RESULT_SCHEMA_VERSION
