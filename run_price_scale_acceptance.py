#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

OUT = Path("/var/tmp/traiding_pilot_ui_workspace/price_scale_acceptance_report.json")
SCREENSHOT_DIR = Path("/var/tmp/traiding_pilot_ui_workspace/screenshots_price_scale")
BASE_URL = "http://127.0.0.1:8055"
PRICE_TOL = 0.015


def parse_banner(text: str) -> dict:
    out = {}
    for key, pattern in {
        "actual_visible": r"ACTUAL_VISIBLE_OHLC_BARS:\s*(\d+)",
    }.items():
        m = re.search(pattern, text)
        if m:
            out[key] = int(m.group(1))
    return out


def price_range(page) -> dict | None:
    return page.evaluate("() => window.getPriceScaleDiagnostics ? window.getPriceScaleDiagnostics() : null")


def range_span(rng: dict | None) -> float | None:
    if not rng:
        return None
    visible = rng.get("visible_range") or rng.get("locked_range")
    if not visible:
        return None
    return abs(float(visible["max"]) - float(visible["min"]))


def ranges_close(a: dict | None, b: dict | None, tol: float = PRICE_TOL) -> bool:
    sa = range_span(a)
    sb = range_span(b)
    if sa is None or sb is None or sa == 0:
        return False
    return abs(sa - sb) / sa <= tol


def main() -> int:
    report = {
        "wip": "EXPERT-CHART-PRICE-SCALE-AND-MANUAL-POINTS-FIX-1",
        "browser_screenshots_created": False,
        "ready_for_real_manual_markup": False,
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
            page.wait_for_function("() => typeof window.getPriceScaleDiagnostics === 'function'", timeout=60000)
            time.sleep(1.5)

            chart = page.locator("#lwc-chart")
            box = chart.bounding_box()
            cx = box["x"] + box["width"] * 0.5

            for count in (180, 120, 60):
                page.click(f"#range-{count}")
                page.wait_for_timeout(1500)
                report[f"visible_{count}"] = parse_banner(page.locator("#audit-banner").inner_text()).get("actual_visible")
                page.screenshot(path=str(SCREENSHOT_DIR / f"y_locked_{count}.png"), full_page=False)

            page.click("#range-180")
            page.wait_for_timeout(1500)
            baseline = price_range(page)
            report["baseline_price_diag"] = baseline

            y_scale_stable = True
            for count in (120, 60, 30):
                page.click(f"#range-{count}")
                page.wait_for_timeout(1200)
                current = price_range(page)
                report[f"price_diag_{count}"] = current
                if not ranges_close(baseline, current):
                    y_scale_stable = False

            report["horizontal_zoom_changes_y_scale"] = "NO" if y_scale_stable else "YES"
            report["price_y_locked"] = (baseline or {}).get("price_y_locked")

            page.click("#range-180")
            page.wait_for_timeout(1000)
            low_y = box["y"] + box["height"] * 0.72
            high_y = box["y"] + box["height"] * 0.28
            mid_y = box["y"] + box["height"] * 0.5

            points_visible = []
            for idx, y in enumerate((low_y, high_y, mid_y)):
                page.click("#add-point")
                page.wait_for_timeout(300)
                page.mouse.click(cx, y)
                page.wait_for_timeout(1200)
                panel = page.locator("aside").inner_text()
                points_visible.append(f"P{idx}" in panel)
                report[f"p{idx}_visible"] = f"P{idx}" in panel

            page.screenshot(path=str(SCREENSHOT_DIR / "blind_p0_p1_p2.png"), full_page=False)

            page.click("#range-120")
            page.wait_for_timeout(800)
            page.screenshot(path=str(SCREENSHOT_DIR / "blind_points_zoom_120.png"), full_page=False)

            checks = [
                abs((report.get("visible_180") or 0) - 180) <= 5,
                y_scale_stable,
                all(points_visible),
                (baseline or {}).get("price_y_mode") == "lock",
            ]
            report["browser_screenshots_created"] = True
            report["ready_for_real_manual_markup"] = all(checks)
            report["checks"] = checks
        finally:
            browser.close()

    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report.get("ready_for_real_manual_markup") else 1


if __name__ == "__main__":
    sys.exit(main())
