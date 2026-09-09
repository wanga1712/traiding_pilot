#!/usr/bin/env bash
# Deploy durability sources to S13 with LF normalization; enable unit; run unit+integration tests.
set -euxo pipefail
ROOT=/var/tmp/traiding_pilot_ui_workspace
PKG="$ROOT/phase3_staging"
ART="$ROOT/artifacts/MULTITF-COMPOSITE-SIGNAL-SEARCH-1"
VENV="$ROOT/.venv/bin/python"
export PYTHONPATH="$PKG"

# LF-normalize deployed Python/service files
find "$PKG/crypto_trading_bot/research_v2/composite_signal_search" -name '*.py' -print0 | xargs -0 sed -i 's/\r$//'
find "$PKG/tests/composite_signal_search" -name 'test_durability*.py' -print0 | xargs -0 sed -i 's/\r$//'
sed -i 's/\r$//' \
  "$PKG/_multitf_composite_search.service" \
  "$PKG/_multitf_composite_search_run.sh" \
  "$PKG/_multitf_composite_search_sleep_hook.sh" \
  "$PKG/_install_durability_unit_enable_only.sh" \
  "$PKG/_run_durability_preflight_tests.py" \
  "$ART/_s13_inspect_and_stop.sh" 2>/dev/null || true

# Ensure service stays stopped during preflight tests
systemctl stop multitf-composite-search.service || true
sudo bash "$PKG/_install_durability_unit_enable_only.sh"

# Unit tests
cd "$PKG"
"$VENV" -m pytest tests/composite_signal_search/test_durability_atomic_io.py -q --tb=short

# Integration durability tests (300 cand resume + crash) — long
"$VENV" "$PKG/_run_durability_preflight_tests.py" | tee "$ART/boot_resume_durability_tests_v1.log"

echo DEPLOY_AND_TEST_DONE
