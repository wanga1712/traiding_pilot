#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

OUT = Path("/var/tmp/traiding_pilot_ui_workspace/stability_acceptance_report.json")
SCREENSHOT_DIR = Path("/var/tmp/traiding_pilot_ui_workspace/screenshots_stability")
BASE_URL = "http://127.0.0.1:8055"
PRICE_TOL = 0.02


def parse_visible(text: str) -> int | None:
    m = re.search(r"Visible:\s*(\d+)", text)
    return int(m.group(1)) if m else None


def main() -> int:
    report = {
        "wip": "EXPERT-CHART-POST-AUDIT-STABILITY-FIX-1",
        "browser_acceptance": "NOT_RUN",
    }
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        report["error"] = "playwright not installed"
        OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 1

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 900})
        try:
            page.goto(BASE_URL, wait_until="networkidle", timeout=120000)
            page.wait_for_selector("#audit-banner", timeout=60000)
            page.wait_for_function("() => typeof window.getChartStabilityDiagnostics === 'function'", timeout=60000)
            time.sleep(2.5)

            chart = page.locator("#lwc-chart")
            box = chart.bounding_box()
            assert box is not None

            page.click("#range-480")
            page.wait_for_timeout(1200)
            page.click("#fit-window")
            page.wait_for_timeout(700)
            page.click("#lock-y")
            page.wait_for_timeout(500)

            banner = page.locator("#audit-banner").inner_text()
            report["default_visible_4h"] = parse_visible(banner)
            page.screenshot(path=str(SCREENSHOT_DIR / "default_480.png"), full_page=False)
            report["screenshot_default_480"] = True

            y_before = page.evaluate("() => window.getPriceScaleDiagnostics()")
            report["y_range_before_x_zoom"] = (y_before or {}).get("visible_range")

            for count in (360, 240, 120, 60):
                page.click(f"#range-{count}")
                page.wait_for_timeout(1000)

            y_after = page.evaluate("() => window.getPriceScaleDiagnostics()")
            report["y_range_after_x_zoom"] = (y_after or {}).get("visible_range")
            before_span = abs(report["y_range_before_x_zoom"]["max"] - report["y_range_before_x_zoom"]["min"])
            after_span = abs(report["y_range_after_x_zoom"]["max"] - report["y_range_after_x_zoom"]["min"])
            report["y_lock_stable"] = abs(after_span - before_span) / before_span <= PRICE_TOL

            page.click("#range-480")
            page.wait_for_timeout(1000)

            stab0 = page.evaluate("() => window.getChartStabilityDiagnostics()")
            report["candle_set_data_before"] = stab0.get("candle_set_data_count")
            report["payload_received_before"] = stab0.get("payload_received_count")
            report["payload_applied_before"] = stab0.get("payload_applied_count")
            report["pan_writes_before"] = stab0.get("pan_programmatic_range_writes")

            xs = [0.25, 0.40, 0.55, 0.70]
            ys = [0.72, 0.28, 0.65, 0.35]
            for x_frac, y_frac in zip(xs, ys):
                page.click("#add-point")
                page.wait_for_timeout(250)
                page.mouse.click(box["x"] + box["width"] * x_frac, box["y"] + box["height"] * y_frac)
                page.wait_for_timeout(1100)

            page.screenshot(path=str(SCREENSHOT_DIR / "points_p0_p3.png"), full_page=False)
            report["screenshot_points"] = True

            points = page.evaluate("() => window.getManualPointDiagnostics()")
            stab1 = page.evaluate("() => window.getChartStabilityDiagnostics()")
            report["session_point_count"] = points.get("session_point_count")
            report["rendered_point_count"] = points.get("rendered_point_count")
            report["last_point_render_error"] = points.get("last_render_error")
            report["point_timestamps"] = points.get("timestamps")
            report["candle_set_data_after_points"] = stab1.get("candle_set_data_count")
            report["payload_received_after"] = stab1.get("payload_received_count")
            report["payload_applied_after"] = stab1.get("payload_applied_count")

            recv_delta = report["payload_received_after"] - report["payload_received_before"]
            appl_delta = report["payload_applied_after"] - report["payload_applied_before"]
            report["payload_apply_ratio"] = f"{appl_delta}/{recv_delta}" if recv_delta else "0/0"

            # Place more points to reach ~10 actions if possible (may reject same/earlier candles)
            extra = 0
            for x_frac in (0.75, 0.80, 0.85, 0.90, 0.92, 0.95):
                page.click("#add-point")
                page.wait_for_timeout(200)
                page.mouse.click(box["x"] + box["width"] * x_frac, box["y"] + box["height"] * 0.45)
                page.wait_for_timeout(900)
                extra += 1
            stab2 = page.evaluate("() => window.getChartStabilityDiagnostics()")
            report["candle_set_data_after_10_points"] = stab2.get("candle_set_data_count")
            report["extra_add_attempts"] = extra

            page.click("#range-480")
            page.wait_for_timeout(800)
            pan_before_writes = page.evaluate("() => window.getChartStabilityDiagnostics().pan_programmatic_range_writes")
            page.mouse.move(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5)
            page.mouse.down()
            page.mouse.move(box["x"] + box["width"] * 0.5 - 280, box["y"] + box["height"] * 0.5, steps=25)
            page.mouse.up()
            page.wait_for_timeout(800)
            pan_after = page.evaluate("() => window.getChartStabilityDiagnostics()")
            report["pan_programmatic_range_writes"] = pan_after.get("pan_programmatic_range_writes") - pan_before_writes
            report["pan_visible_after"] = parse_visible(page.locator("#audit-banner").inner_text())

            day_span = None
            if report.get("point_timestamps") and len(report["point_timestamps"]) >= 1:
                day_span = 480 / 6.0
            report["default_4h_day_span"] = day_span if day_span is not None else 80.0

            unique_ts = len(set(report.get("point_timestamps") or []))
            checks = [
                abs((report.get("default_visible_4h") or 0) - 480) <= 5,
                report.get("y_lock_stable") is True,
                (report.get("session_point_count") or 0) >= 4,
                report.get("session_point_count") == report.get("rendered_point_count"),
                report.get("last_point_render_error") is None,
                report.get("candle_set_data_before") == report.get("candle_set_data_after_points"),
                report.get("candle_set_data_before") == report.get("candle_set_data_after_10_points"),
                unique_ts == (report.get("session_point_count") or 0),
                (report.get("pan_programmatic_range_writes") or 0) == 0,
            ]
            report["checks"] = checks
            report["browser_acceptance"] = "PASS" if all(checks) else "FAIL"
            report["ready_for_real_expert_markup"] = report["browser_acceptance"] == "PASS"
        finally:
            browser.close()

    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report.get("browser_acceptance") == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
