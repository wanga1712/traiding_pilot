#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

OUT = Path("/var/tmp/traiding_pilot_ui_workspace/markup_ux_acceptance_report.json")
SCREENSHOT_DIR = Path("/var/tmp/traiding_pilot_ui_workspace/screenshots_markup_ux")
BASE_URL = "http://127.0.0.1:8055"
PRICE_TOL = 0.02


def parse_visible(text: str) -> int | None:
    m = re.search(r"Visible:\s*(\d+)", text)
    return int(m.group(1)) if m else None


def price_diag(page):
    return page.evaluate("() => window.getPriceScaleDiagnostics ? window.getPriceScaleDiagnostics() : null")


def span(rng):
    if not rng:
        return None
    visible = rng.get("visible_range") or rng.get("locked_range")
    if not visible:
        return None
    return abs(float(visible["max"]) - float(visible["min"]))


def main() -> int:
    report = {"wip": "EXPERT-CHART-FINAL-MANUAL-MARKUP-UX-1"}
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
            time.sleep(2)

            chart = page.locator("#lwc-chart")
            box = chart.bounding_box()
            cx = box["x"] + box["width"] * 0.5

            baseline_span = None
            y_stable = True
            for count in (180, 120, 90, 60, 30):
                page.click(f"#range-{count}")
                page.wait_for_timeout(1200)
                page.click("#fit-window")
                page.wait_for_timeout(800)
                page.click("#lock-y")
                page.wait_for_timeout(400)
                banner = page.locator("#audit-banner").inner_text()
                report[f"screenshot_{count}"] = True
                report[f"visible_{count}"] = parse_visible(banner)
                page.screenshot(path=str(SCREENSHOT_DIR / f"scale_{count}.png"), full_page=False)
                diag = price_diag(page)
                current_span = span(diag)
                if baseline_span is None:
                    baseline_span = current_span
                elif baseline_span and current_span and abs(current_span - baseline_span) / baseline_span > PRICE_TOL:
                    y_stable = False

            report["horizontal_zoom_preserves_y"] = y_stable

            page.click("#range-90")
            page.wait_for_timeout(1000)
            page.click("#fit-window")
            page.wait_for_timeout(500)
            lows = [box["y"] + box["height"] * 0.75, box["y"] + box["height"] * 0.25, box["y"] + box["height"] * 0.55, box["y"] + box["height"] * 0.40]
            points_ok = []
            for i, y in enumerate(lows):
                page.click("#add-point")
                page.wait_for_timeout(250)
                page.mouse.click(cx, y)
                page.wait_for_timeout(900)
                panel = page.locator("aside").inner_text()
                points_ok.append(f"P{i}" in panel)
                report[f"p{i}_visible"] = f"P{i}" in panel
            page.screenshot(path=str(SCREENSHOT_DIR / "points_p0_p3.png"), full_page=False)

            page.click("#move-point")
            page.wait_for_timeout(200)
            page.mouse.click(cx, lows[2])
            page.wait_for_timeout(500)
            page.mouse.click(cx, lows[2] - 40)
            page.wait_for_timeout(800)

            page.click("#delete-point")
            page.wait_for_timeout(200)
            page.mouse.click(cx, lows[1])
            page.wait_for_timeout(800)

            page.click("#undo")
            page.wait_for_timeout(800)
            panel_after = page.locator("aside").inner_text()
            report["undo_restored_p1"] = "P1" in panel_after

            page.mouse.move(cx, box["y"] + box["height"] * 0.5)
            page.wait_for_timeout(500)
            status = page.locator("#status").inner_text()
            report["crosshair_info"] = "Cursor" in status and "Y=" in status

            debug_collapsed = page.locator(".debug-panel").evaluate("el => !el.open")
            report["debug_panel_collapsed"] = debug_collapsed

            checks = [
                abs((report.get("visible_90") or 0) - 90) <= 5,
                y_stable,
                all(points_ok),
                report.get("undo_restored_p1"),
                report.get("crosshair_info"),
                debug_collapsed,
            ]
            report["p0_p1_p2_p3_acceptance"] = all(points_ok)
            report["ready_for_real_expert_annotation"] = all(checks)
            report["checks"] = checks
        finally:
            browser.close()

    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report.get("ready_for_real_expert_annotation") else 1


if __name__ == "__main__":
    sys.exit(main())
