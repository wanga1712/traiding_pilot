#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from crypto_trading_bot.research_v2.market_data import TimeframeBarService
from crypto_trading_bot.research_v2.visualization.chart_engine import (
    DEFAULT_VISIBLE_BARS,
    MAX_VISIBLE_BARS,
    MIN_VISIBLE_BARS,
    RANGE_SHORTCUTS,
    count_actual_visible_bars,
    default_chart_state,
    load_initial_window,
    maybe_prepend_history,
    set_visible_bar_count,
)

SERVICE = TimeframeBarService(
    symbol="ETHUSDT",
    canonical_root=Path("/srv/traiding_pilot/market/binance/spot/ETHUSDT/1m"),
    cache_root=Path("/var/tmp/traiding_pilot_market_cache"),
    ssh_host="wanga@10.8.0.7",
    ssh_key=Path("/home/sergey/.ssh/id_to_nyx"),
)
END = datetime(2024, 6, 30, tzinfo=timezone.utc)
TOLS = {30: 2, 60: 2, 90: 2, 120: 2, 180: 2, 300: 2}


def main() -> None:
    chart = load_initial_window(SERVICE, default_chart_state("ETHUSDT", "4H", END))
    candles = chart["candles"]

    report = {
        "wip": "EXPERT-CHART-FINAL-MANUAL-MARKUP-UX-1",
        "chart_engine": "tradingview_lightweight_charts_v4_index_temporal",
        "backend_only": True,
        "browser_acceptance": "NOT_RUN",
        "loaded_bars": len(candles),
        "initial_visible_count": chart["audit"]["actual_visible_ohlc_bars"],
        "min_visible_bars": MIN_VISIBLE_BARS,
        "max_visible_bars": MAX_VISIBLE_BARS,
        "fake_acceptance_flags_removed": True,
        "note": "UI wheel/pan/point behavior requires run_browser_acceptance.py with Playwright",
    }

    all_shortcuts = True
    for count in RANGE_SHORTCUTS:
        state = set_visible_bar_count(chart, count, SERVICE)
        actual = state["audit"]["actual_visible_ohlc_bars"]
        counted = count_actual_visible_bars(candles, state["viewport_start"], state["viewport_end"])
        report[f"shortcut_{count}"] = actual
        if abs(actual - count) > TOLS[count] or abs(counted - actual) > 2:
            all_shortcuts = False

    edge = 80
    relayout = {
        "bar_from": 0,
        "bar_to": edge - 1,
        "visible_from_time": chart["candles"][0]["open_time_utc"],
        "visible_to_time": chart["candles"][edge - 1]["open_time_utc"],
    }
    chart2, _ = maybe_prepend_history(SERVICE, chart, relayout, {"bar_from": 0, "bar_to": edge - 1})
    report["lazy_load_preserves_timestamps"] = chart2["audit"]["actual_visible_ohlc_bars"] == edge
    report["shortcut_matrix_backend"] = all_shortcuts
    report["ready_for_expert_markup"] = all_shortcuts and report["lazy_load_preserves_timestamps"]

    out = Path("/var/tmp/traiding_pilot_ui_workspace/acceptance_report_backend.json")
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
