#!/bin/bash
# Bounded-memory compose runner (no full-RAM expand). Does NOT auto-start full search
# after repair smoke — invoke explicitly with --phase compose-bounded|memory-smoke.
set -eu
ROOT=/var/tmp/traiding_pilot_ui_workspace
PKG="$ROOT/phase3_staging"
ART="$ROOT/artifacts/MULTITF-COMPOSITE-SIGNAL-SEARCH-1"
PARENT="$ROOT/artifacts/MULTITF-INDICATOR-PARAMETER-SEARCH-1"
DONE="$ART/composite_search_DONE"
PHASE="${COMPOSITE_SEARCH_PHASE:-compose-bounded}"
mkdir -p "$ART"
cd "$PKG"

if [ -f "$DONE" ]; then
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) already DONE — exit 0" >>"$ART/_composite_search_all.log"
  exit 0
fi

export COMPOSITE_SIGNAL_SEARCH_ARTIFACT_ROOT="$ART"
export INDICATOR_PARAM_SEARCH_ARTIFACT_ROOT="$PARENT"
export REVERSAL_EVENT_DATASET_DIR="$ROOT/reversal_event_dataset_v1"
export TRAIDING_PILOT_MARKET_CACHE=/var/tmp/traiding_pilot_market_cache
export TRAIDING_PILOT_SSH_KEY=/home/sergey/.ssh/id_to_nyx
export PYTHONPATH=.
export ATOMIC_REPLAY_WORKERS="${ATOMIC_REPLAY_WORKERS:-1}"
export MEMORY_GUARD_THRESHOLD_GB="${MEMORY_GUARD_THRESHOLD_GB:-9}"
LOG="$ART/_composite_search_all.log"
echo "$$" > "$ART/composite_search.pid"
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) multitf-composite-search start pid=$$ phase=$PHASE" >> "$LOG"

set +e
/var/tmp/traiding_pilot_ui_workspace/.venv/bin/python -u -m crypto_trading_bot.research_v2.composite_signal_search.run_search --phase "$PHASE" >>"$LOG" 2>&1
rc=$?
set -e

if [ "$rc" -eq 0 ] && [ "$PHASE" = "compose-bounded" ]; then
  # Full compose completion marker only for unbounded-complete bounded runs without max-candidates.
  if [ -f "$ART/composite_results_all_v1.parquet" ] || [ -f "$ART/composite_results_partial_v1.parquet" ]; then
    :
  fi
fi
exit "$rc"
