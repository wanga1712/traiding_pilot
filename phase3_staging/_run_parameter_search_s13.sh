#!/bin/bash
set -euo pipefail
PHASE="${1:-all}"
pkill -f 'crypto_trading_bot.research_v2.indicator_parameter_search.run_search' || true
sleep 2
cd /var/tmp/traiding_pilot_ui_workspace/phase3_staging
export INDICATOR_PARAM_SEARCH_ARTIFACT_ROOT=/var/tmp/traiding_pilot_ui_workspace/artifacts/MULTITF-INDICATOR-PARAMETER-SEARCH-1
export REVERSAL_EVENT_DATASET_DIR=/var/tmp/traiding_pilot_ui_workspace/reversal_event_dataset_v1
export TRAIDING_PILOT_MARKET_CACHE=/var/tmp/traiding_pilot_market_cache
export TRAIDING_PILOT_SSH_KEY=/home/sergey/.ssh/id_to_nyx
export PYTHONPATH=.
LOG="$INDICATOR_PARAM_SEARCH_ARTIFACT_ROOT/_param_search_${PHASE}.log"
nohup /var/tmp/traiding_pilot_ui_workspace/.venv/bin/python -u -m crypto_trading_bot.research_v2.indicator_parameter_search.run_search --phase "$PHASE" >"$LOG" 2>&1 </dev/null &
echo "PID=$! PHASE=$PHASE"
sleep 3
pgrep -af 'indicator_parameter_search.run_search' || true
head -30 "$LOG" || true
