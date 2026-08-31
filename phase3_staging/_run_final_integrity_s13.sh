#!/bin/bash
set -euo pipefail
pkill -f 'crypto_trading_bot.research_v2.oscillator_predictor_event_study.run_final_integrity' || true
sleep 2
cd /var/tmp/traiding_pilot_ui_workspace/phase3_staging
export OSCILLATOR_EVENT_STUDY_ARTIFACT_ROOT=/var/tmp/traiding_pilot_ui_workspace/artifacts/OSCILLATOR-PREDICTOR-HISTORICAL-EVENT-STUDY-1
export TRAIDING_PILOT_MARKET_CACHE=/var/tmp/traiding_pilot_market_cache
export TRAIDING_PILOT_SSH_KEY=/home/sergey/.ssh/id_to_nyx
export PYTHONPATH=.
LOG=$OSCILLATOR_EVENT_STUDY_ARTIFACT_ROOT/_final_integrity.log
nohup /var/tmp/traiding_pilot_ui_workspace/.venv/bin/python -u -m crypto_trading_bot.research_v2.oscillator_predictor_event_study.run_final_integrity >"$LOG" 2>&1 </dev/null &
echo "PID=$!"
sleep 3
pgrep -af 'oscillator_predictor_event_study.run_final_integrity' || true
head -30 "$LOG" || true
