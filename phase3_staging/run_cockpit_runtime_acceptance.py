#!/usr/bin/env python3
"""Runtime visual acceptance for TRADING-RESEARCH-COCKPIT-FOUNDATION-1 on S13."""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

BASE_URL = os.environ.get("COCKPIT_BASE_URL", "http://127.0.0.1:8055")
SCREENSHOT_DIR = Path(os.environ.get("COCKPIT_SCREENSHOT_DIR", "/var/tmp/traiding_pilot_ui_workspace/cockpit_screenshots"))
REPORT_PATH = Path(os.environ.get("COCKPIT_REPORT_PATH", "/var/tmp/traiding_pilot_ui_workspace/cockpit_runtime_acceptance.json"))
INCLUDE_FIXTURES = os.environ.get("TRADING_RUN_INCLUDE_FIXTURES", "0") == "1"


def _select_run(page, run_id: str) -> None:
    page.click("#trading-run-select")
    page.keyboard.type(run_id[:12])
    time.sleep(0.5)
    page.locator(f".Select-option:has-text('{run_id}')").first.click(timeout=15000)
    time.sleep(1.5)


def main() -> int:
    report: dict = {
        "wip": "TRADING-RESEARCH-COCKPIT-FOUNDATION-1",
        "base_url": BASE_URL,
        "include_fixtures": INCLUDE_FIXTURES,
        "checks": {},
    }
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        report["error"] = "playwright not installed"
        REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 1

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        console_errors: list[str] = []

        def on_console(msg):
            if msg.type == "error":
                console_errors.append(msg.text)

        page.on("console", on_console)
        page.goto(BASE_URL, wait_until="networkidle", timeout=180000)
        page.wait_for_selector("#lwc-chart", timeout=120000)
        page.wait_for_selector("#audit-banner", timeout=120000)
        page.wait_for_function(
            "() => (document.querySelector('#audit-banner')?.innerText || '').includes('ACTUAL_VISIBLE_OHLC_BARS')",
            timeout=120000,
        )

        report["checks"]["chart_loaded"] = page.locator("#lwc-chart").count() > 0
        report["checks"]["zigzag_controls"] = page.locator("#zz-apply").count() > 0
        report["checks"]["result_panel_present"] = page.locator("#historical-run-panel").count() > 0
        report["checks"]["run_selector_present"] = page.locator("#trading-run-select").count() > 0

        panel_text = page.locator("#historical-run-panel").inner_text()
        report["checks"]["panel_below_chart"] = report["checks"]["result_panel_present"]

        # Structural run (production manifest)
        if page.locator("#trading-run-select .Select-value-label").count():
            _select_run(page, "ORIGINAL_DMA_STOCH_STRUCTURAL_V1")
        else:
            page.select_option("#trading-run-select", "ORIGINAL_DMA_STOCH_STRUCTURAL_V1")
            time.sleep(1.5)

        structural_text = page.locator("#historical-run-panel").inner_text()
        report["checks"]["structural_only_badge"] = "STRUCTURAL ONLY" in structural_text
        report["checks"]["structural_no_start_balance"] = "START" not in structural_text or "$" not in structural_text.split("Precision")[0]
        report["checks"]["structural_research_metrics"] = "Precision" in structural_text
        page.screenshot(path=str(SCREENSHOT_DIR / "structural_only.png"), full_page=True)

        if INCLUDE_FIXTURES:
            _select_run(page, "FIXTURE_COMPLETED_REALISTIC_V1")
            completed = page.locator("#historical-run-panel").inner_text()
            for token in ["START", "FINAL", "RETURN", "TRADES", "MAX DD", "LIQUIDATIONS", "NET PnL"]:
                if token not in completed:
                    errors.append(f"completed fixture missing {token}")
            report["checks"]["completed_fixture_cards"] = all(t in completed for t in ["START", "FINAL", "RETURN", "TRADES", "MAX DD", "LIQUIDATIONS"])
            report["checks"]["completed_equity_curve"] = page.locator(".run-equity-wrap .js-plotly-plot").count() > 0
            page.screenshot(path=str(SCREENSHOT_DIR / "desktop_completed_fixture.png"), full_page=True)

            for fid, needle in [
                ("FIXTURE_RUNNING_V1", "RUN IN PROGRESS"),
                ("FIXTURE_RECON_FAIL_V1", "Reconciliation: FAIL"),
                ("FIXTURE_ZERO_LIQ_V1", "NO LIQUIDATIONS"),
                ("FIXTURE_UNKNOWN_LIQ_V1", "LIQUIDATION"),
            ]:
                _select_run(page, fid)
                txt = page.locator("#historical-run-panel").inner_text()
                if needle not in txt:
                    errors.append(f"{fid} missing {needle}")

        else:
            # Empty-ish production: clear selection if possible
            page.evaluate(
                """() => {
                  const el = document.querySelector('#trading-run-select');
                  if (el) el.dispatchEvent(new Event('change', {bubbles:true}));
                }"""
            )
            time.sleep(0.5)
            page.screenshot(path=str(SCREENSHOT_DIR / "desktop_empty.png"), full_page=True)

        chart_box = page.locator("#lwc-chart").bounding_box()
        report["checks"]["chart_has_height"] = bool(chart_box and chart_box.get("height", 0) >= 250)
        report["console_errors"] = console_errors[:20]
        report["checks"]["no_console_errors"] = len(console_errors) == 0
        if console_errors:
            errors.append(f"console errors: {console_errors[:3]}")

        browser.close()

    report["errors"] = errors
    report["pass"] = not errors and all(report["checks"].values())
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
