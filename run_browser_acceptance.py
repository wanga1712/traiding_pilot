#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

OUT = Path("/var/tmp/traiding_pilot_ui_workspace/browser_acceptance_report.json")
SCREENSHOT_DIR = Path("/var/tmp/traiding_pilot_ui_workspace/screenshots")
BASE_URL = "http://127.0.0.1:8055"


def parse_banner(text: str) -> dict:
    out = {}
    for key, pattern in {
        "actual_visible": r"ACTUAL_VISIBLE_OHLC_BARS:\s*(\d+)",
        "raw_wheel": r"RAW=(\d+)",
        "applied_wheel": r"APPLIED=(\d+)",
    }.items():
        m = re.search(pattern, text)
        if m:
            out[key] = int(m.group(1))
    return out


def main() -> int:
    report = {
        "wip": "EXPERT-CHART-REAL-FIX-AFTER-CODE-AUDIT-1",
        "browser_acceptance": "NOT_RUN",
        "screenshot_matrix_created": False,
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
            page.wait_for_function(
                "() => (document.querySelector('#audit-banner')?.innerText || '').includes('ACTUAL_VISIBLE_OHLC_BARS')",
                timeout=120000,
            )
            time.sleep(1)

            def banner_text() -> str:
                return page.locator("#audit-banner").inner_text()

            for count in (400, 200, 120, 60, 30):
                page.click(f"#range-{count}")
                page.wait_for_timeout(1500)
                metrics = parse_banner(banner_text())
                page.screenshot(path=str(SCREENSHOT_DIR / f"shortcut_{count}.png"), full_page=False)
                report[f"shortcut_{count}_visible"] = metrics.get("actual_visible")

            page.click("#range-120")
            page.wait_for_timeout(1500)
            before = parse_banner(banner_text())
            report["one_gesture_visible_before"] = before.get("actual_visible")
            raw_before = before.get("raw_wheel", 0)
            applied_before = before.get("applied_wheel", 0)

            chart = page.locator("#lwc-chart")
            box = chart.bounding_box()
            cx = box["x"] + box["width"] * 0.5
            cy = box["y"] + box["height"] * 0.5
            page.mouse.move(cx, cy)
            for _ in range(8):
                page.mouse.wheel(0, -120)
            page.wait_for_timeout(300)
            page.wait_for_function(
                "(before) => { const t = document.querySelector('#audit-banner')?.innerText || ''; const m = t.match(/APPLIED=(\\d+)/); return m && parseInt(m[1], 10) > before; }",
                arg=applied_before,
                timeout=5000,
            )
            after = parse_banner(banner_text())
            report["one_gesture_visible_after"] = after.get("actual_visible")
            report["raw_wheel_events_per_test_gesture"] = after.get("raw_wheel", 0) - raw_before
            report["applied_zoom_gestures"] = after.get("applied_wheel", 0) - applied_before
            page.screenshot(path=str(SCREENSHOT_DIR / "after_one_wheel_gesture.png"), full_page=False)

            applied_after_first = after.get("applied_wheel", 0)
            page.wait_for_timeout(400)
            page.mouse.move(cx, cy)
            for _ in range(8):
                page.mouse.wheel(0, -120)
            page.wait_for_timeout(300)
            page.wait_for_function(
                "(before) => { const t = document.querySelector('#audit-banner')?.innerText || ''; const m = t.match(/APPLIED=(\\d+)/); return m && parseInt(m[1], 10) > before; }",
                arg=applied_after_first,
                timeout=5000,
            )
            after_second = parse_banner(banner_text())
            report["two_gesture_visible_after"] = after_second.get("actual_visible")
            report["applied_zoom_gestures_second"] = after_second.get("applied_wheel", 0) - applied_after_first
            page.screenshot(path=str(SCREENSHOT_DIR / "after_two_wheel_gestures.png"), full_page=False)

            page.click("#range-120")
            page.wait_for_function(
                "() => { const t = document.querySelector('#audit-banner')?.innerText || ''; const m = t.match(/ACTUAL_VISIBLE_OHLC_BARS:\\s*(\\d+)/); return m && Math.abs(parseInt(m[1], 10) - 120) <= 2; }",
                timeout=10000,
            )
            page.wait_for_timeout(500)
            pan_before = parse_banner(banner_text()).get("actual_visible")
            page.mouse.move(cx, cy)
            page.mouse.down()
            page.mouse.move(cx - 250, cy, steps=20)
            page.mouse.up()
            page.wait_for_timeout(700)
            pan_after = parse_banner(banner_text()).get("actual_visible")
            report["pan_visible_before"] = pan_before
            report["pan_visible_after"] = pan_after

            page.click("#add-point")
            page.mouse.click(cx, cy)
            time.sleep(1)
            page.screenshot(path=str(SCREENSHOT_DIR / "point_placed.png"), full_page=False)
            report["point_add_clicked"] = True

            checks = []
            checks.append(abs((report.get("shortcut_120_visible") or 0) - 120) <= 5)
            checks.append(abs((report.get("one_gesture_visible_after") or 0) - 108) <= 8)
            checks.append((report.get("raw_wheel_events_per_test_gesture") or 0) >= 1)
            checks.append((report.get("applied_zoom_gestures") or 0) == 1)
            checks.append(abs((report.get("two_gesture_visible_after") or 0) - 97) <= 10)
            checks.append((report.get("applied_zoom_gestures_second") or 0) == 1)
            checks.append(abs((pan_after or 0) - (pan_before or 0)) <= 2)
            report["browser_acceptance"] = "PASS" if all(checks) else "FAIL"
            report["screenshot_matrix_created"] = True
            report["checks"] = checks
        finally:
            browser.close()

    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report.get("browser_acceptance") == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
