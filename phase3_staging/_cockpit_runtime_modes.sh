#!/bin/bash
set -euo pipefail
WS=/var/tmp/traiding_pilot_ui_workspace
PKG="$WS/phase3_staging"
STORE="$PKG/artifacts/TRADING-RESEARCH-COCKPIT-FOUNDATION-1/trading_runs_store"
MODE="${1:-production}"

restart() {
  pkill -f "crypto_trading_bot.research_v2.visualization.expert_app" || true
  sleep 2
  cd "$PKG"
  nohup env "$@" PYTHONPATH=. "$WS/.venv/bin/python" -m crypto_trading_bot.research_v2.visualization.expert_app \
    --host 0.0.0.0 --port 8055 --initial-end 2024-06-30 --oos-blind \
    > "$WS/expert_app.log" 2>&1 &
  sleep 6
  curl -s -o /dev/null -w "http=%{http_code}\n" http://127.0.0.1:8055/
}

case "$MODE" in
  empty)
    cp "$STORE/manifest.json" "$STORE/manifest.json.bak" 2>/dev/null || true
    printf '%s\n' '{"run_ids":[]}' > "$STORE/manifest.json"
    restart
    curl -s http://127.0.0.1:8055/api/trading-runs
    echo
    ;;
  fixtures)
    if [ -f "$STORE/manifest.json.bak" ]; then
      mv "$STORE/manifest.json.bak" "$STORE/manifest.json"
    fi
    restart TRADING_RUN_INCLUDE_FIXTURES=1
    curl -s http://127.0.0.1:8055/api/trading-runs | python3 -c "import sys,json; r=json.load(sys.stdin)['runs']; print('count',len(r)); print([x['run_id'] for x in r[:5]])"
    curl -s http://127.0.0.1:8055/api/trading-runs/FIXTURE_COMPLETED_REALISTIC_V1/summary | python3 -c "import sys,json; d=json.load(sys.stdin); print('final',d.get('capital',{}).get('final_equity'))"
    curl -s http://127.0.0.1:8055/api/trading-runs/FIXTURE_RUNNING_V1/summary | python3 -c "import sys,json; d=json.load(sys.stdin); print('status',d.get('run_status'))"
    curl -s http://127.0.0.1:8055/api/trading-runs/FIXTURE_RECON_FAIL_V1 | python3 -c "import sys,json; d=json.load(sys.stdin); print('recon',d.get('reconciliation',{}).get('ECONOMIC_RECONCILIATION_STATUS'))"
    curl -s http://127.0.0.1:8055/api/trading-runs/FIXTURE_ZERO_LIQ_V1/liquidations
    echo
    curl -s http://127.0.0.1:8055/api/trading-runs/FIXTURE_UNKNOWN_LIQ_V1/summary | python3 -c "import sys,json; d=json.load(sys.stdin); print('liq', (d.get('performance') or {}).get('liquidation_count'))"
    ;;
  production)
    if [ -f "$STORE/manifest.json.bak" ]; then
      rm -f "$STORE/manifest.json.bak"
    fi
    restart
    curl -s http://127.0.0.1:8055/api/trading-runs
    echo
    ;;
  *)
    echo "usage: $0 {empty|fixtures|production}"
    exit 1
    ;;
esac
ss -tlnp | grep 8055 || true
