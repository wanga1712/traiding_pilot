#!/bin/bash
set -euo pipefail
ROOT=/var/tmp/traiding_pilot_ui_workspace
PKG="$ROOT/phase3_staging"
VENV="$ROOT/.venv"
mkdir -p "$ROOT"
rm -rf "$PKG"
mkdir -p "$PKG/crypto_trading_bot"
cp -r "$ROOT/incoming/crypto_trading_bot/research_v2" "$PKG/crypto_trading_bot/"
cp "$ROOT/incoming/requirements-visualization-v2.txt" "$PKG/"
cp "$ROOT/incoming/run_workspace_acceptance.py" "$PKG/"
if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -r "$PKG/requirements-visualization-v2.txt" dash plotly pyarrow
fi
cd "$PKG"
PYTHONPATH=. "$VENV/bin/python" run_workspace_acceptance.py
pkill -f "crypto_trading_bot.research_v2.visualization.expert_app" || true
nohup env PYTHONPATH=. "$VENV/bin/python" -m crypto_trading_bot.research_v2.visualization.expert_app \
  --host 0.0.0.0 --port 8055 --initial-end 2024-06-30 --oos-blind \
  > "$ROOT/expert_app.log" 2>&1 &
sleep 2
tail -20 "$ROOT/expert_app.log"
