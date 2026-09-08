#!/bin/bash
# Install/refresh composite search systemd unit + sleep hook on S13.
set -eux
PKG=/var/tmp/traiding_pilot_ui_workspace/phase3_staging
ART=/var/tmp/traiding_pilot_ui_workspace/artifacts/MULTITF-COMPOSITE-SIGNAL-SEARCH-1

sed -i 's/\r$//' \
  "$PKG/_multitf_composite_search_run.sh" \
  "$PKG/_multitf_composite_search.service" \
  "$PKG/_multitf_composite_search_sleep_hook.sh"

install -m 0755 "$PKG/_multitf_composite_search_run.sh" /usr/local/bin/multitf-composite-search-run.sh
install -m 0644 "$PKG/_multitf_composite_search.service" /etc/systemd/system/multitf-composite-search.service
install -m 0755 "$PKG/_multitf_composite_search_sleep_hook.sh" /usr/lib/systemd/system-sleep/multitf-composite-search

systemctl daemon-reload

# Stop orphan nohup / old unit so we migrate cleanly onto checkpoint.
pkill -f 'crypto_trading_bot.research_v2.composite_signal_search.run_search' || true
systemctl stop multitf-composite-search.service || true
sleep 2

# Only enable/start if not already finished.
if [ -f "$ART/composite_search_DONE" ]; then
  systemctl disable multitf-composite-search.service || true
  echo "ALREADY_DONE"
  systemctl status multitf-composite-search.service --no-pager -l || true
  exit 0
fi

systemctl enable multitf-composite-search.service
systemctl restart multitf-composite-search.service
sleep 4
systemctl status multitf-composite-search.service --no-pager -l || true
echo '---progress---'
cat "$ART/atomic_replay_progress_v1.json" 2>/dev/null || true
echo '---hook---'
ls -la /usr/lib/systemd/system-sleep/multitf-composite-search
echo INSTALLED_OK
