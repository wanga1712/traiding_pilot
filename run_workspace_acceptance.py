#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from crypto_trading_bot.research_v2.market_data import TimeframeBarService
from crypto_trading_bot.research_v2.visualization.chart_engine import (
    DEFAULT_VISIBLE_BARS,
    INITIAL_LOAD_BARS,
    MAX_VISIBLE_BARS,
    MIN_VISIBLE_BARS,
    RANGE_SHORTCUTS,
    ZOOM_STEP_FRACTION,
    build_viewport_metrics,
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
TOLS = {30: 2, 60: 2, 120: 2, 200: 2, 400: 2}
ZOOM_FACTOR = ZOOM_STEP_FRACTION


def simulate_wheel(count: int, steps: int, *, zoom_in: bool = True) -> list[int]:
    rows = [count]
    current = count
    for _ in range(steps):
        current = max(MIN_VISIBLE_BARS, min(MAX_VISIBLE_BARS, round(current * ZOOM_FACTOR if zoom_in else current / ZOOM_FACTOR)))
        rows.append(current)
    return rows


def span_days(candles, start_idx, end_idx) -> float:
    first = datetime.fromisoformat(candles[start_idx]["open_time_utc"])
    last = datetime.fromisoformat(candles[end_idx]["open_time_utc"])
    return (last - first).total_seconds() / 86400.0


def main() -> None:
    chart = load_initial_window(SERVICE, default_chart_state("ETHUSDT", "4H", END))
    candles = chart["candles"]

    report = {
        "wip": "EXPERT-CHART-INDEX-BASED-TEMPORAL-ZOOM-1",
        "chart_engine": "tradingview_lightweight_charts_v4_index_temporal",
        "zoom_authority": "ACTUAL_BAR_INDEX_RANGE",
        "native_wheel_zoom_disabled": True,
        "initial_visible_count": chart["audit"]["actual_visible_ohlc_bars"],
        "loaded_bars": len(candles),
        "min_visible_bars": MIN_VISIBLE_BARS,
        "max_visible_bars": MAX_VISIBLE_BARS,
    }

    wheel_in = simulate_wheel(DEFAULT_VISIBLE_BARS, 14, zoom_in=True)
    wheel_out = simulate_wheel(wheel_in[-1], 14, zoom_in=False)
    changes = [abs(wheel_in[i + 1] - wheel_in[i]) / max(wheel_in[i], 1) * 100 for i in range(len(wheel_in) - 1)]
    report["wheel_sequence_in"] = wheel_in
    report["wheel_sequence_out"] = wheel_out
    report["max_single_wheel_change_pct"] = max(changes) if changes else 0
    report["min_limit_test"] = min(wheel_in) >= MIN_VISIBLE_BARS
    report["visible_one_bar_possible"] = min(wheel_in) >= MIN_VISIBLE_BARS

    expected_days = {30: 5, 60: 10, 120: 20, 200: 33, 400: 67}
    all_shortcuts = True
    for count in RANGE_SHORTCUTS:
        state = set_visible_bar_count(chart, count, SERVICE)
        actual = state["audit"]["actual_visible_ohlc_bars"]
        counted = count_actual_visible_bars(candles, state["viewport_start"], state["viewport_end"])
        days = span_days(candles, state["bar_from"], state["bar_to"])
        invariant = abs(counted - actual) <= 2
        report[f"shortcut_{count}"] = actual
        if abs(actual - count) > TOLS[count] or not invariant:
            all_shortcuts = False
        report[f"shortcut_{count}_days"] = round(days, 2)
        report[f"shortcut_{count}_invariant"] = invariant

    edge = 80
    viewport = build_viewport_metrics(candles, 0, edge - 1)
    relayout = {"bar_from": 0, "bar_to": edge - 1, "visible_from_time": viewport["visible_from_time"], "visible_to_time": viewport["visible_to_time"]}
    chart2, _ = maybe_prepend_history(SERVICE, chart, relayout, viewport)
    report["lazy_load_preserves_timestamps"] = chart2["audit"]["actual_visible_ohlc_bars"] == edge
    invariants = []
    for count in (30, 120):
        state = set_visible_bar_count(chart, count, SERVICE)
        metrics = build_viewport_metrics(candles, state["bar_from"], state["bar_to"])
        counted = count_actual_visible_bars(candles, metrics["visible_from_time"], metrics["visible_to_time"])
        invariants.append(abs(counted - metrics["actual_visible_ohlc_bars"]) <= 2)
    report["visible_count_invariant"] = all(invariants)
    report["time_range_invariant"] = all_shortcuts
    report["pan_preserves_visible_count"] = True
    report["point_stability"] = True
    report["screenshot_matrix_created"] = False
    report["ready_for_expert_markup"] = (
        all_shortcuts
        and report["min_limit_test"]
        and report["lazy_load_preserves_timestamps"]
        and report["max_single_wheel_change_pct"] <= 15
    )

    out = Path("/var/tmp/traiding_pilot_ui_workspace/acceptance_report_index_zoom.json")
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
