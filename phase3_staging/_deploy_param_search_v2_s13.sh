#!/bin/bash
set -euo pipefail
COMMIT="${1:?usage: _deploy_param_search_v2_s13.sh <commit_sha>}"
LOCAL_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519_codex_worker}"
SSH_TARGET="${SSH_TARGET:-sergey@10.8.0.13}"
S13_WS=/var/tmp/traiding_pilot_ui_workspace
SRC="$LOCAL_ROOT/phase3_staging/crypto_trading_bot/research_v2/indicator_parameter_search"
DST="$S13_WS/phase3_staging/crypto_trading_bot/research_v2/indicator_parameter_search"
ART="$S13_WS/artifacts/MULTITF-INDICATOR-PARAMETER-SEARCH-1"
LOCAL_ART="$LOCAL_ROOT/artifacts/MULTITF-INDICATOR-PARAMETER-SEARCH-1"

echo "[deploy] commit=$COMMIT"
scp -i "$SSH_KEY" -r "$SRC"/*.py "$SSH_TARGET:$DST/"
scp -i "$SSH_KEY" \
  "$LOCAL_ART/search_spec_v2.json" \
  "$LOCAL_ART/search_spec_v2.md" \
  "$LOCAL_ART/candidate_registry_snapshot_v2.csv" \
  "$LOCAL_ART/search_spec_v1_superseded_manifest.json" \
  "$LOCAL_ART/discovery_run_1813764_authority_v1.json" \
  "$SSH_TARGET:$ART/"

ssh -i "$SSH_KEY" "$SSH_TARGET" "cd $S13_WS/phase3_staging && PYTHONPATH=. /var/tmp/traiding_pilot_ui_workspace/.venv/bin/python -m pytest tests/indicator_parameter_search/test_search_spec_v2_integrity.py tests/indicator_parameter_search/test_discovery_isolation.py -q --noconftest"

echo "[deploy] stopping prior discovery"
ssh -i "$SSH_KEY" "$SSH_TARGET" "pkill -f 'indicator_parameter_search.run_search' || true; sleep 2"

echo "[deploy] restart discovery-only from candidate 0"
ssh -i "$SSH_KEY" "$SSH_TARGET" "bash $S13_WS/phase3_staging/_run_parameter_search_s13.sh discovery-only"

echo "[deploy] done commit=$COMMIT"
