#!/usr/bin/env bash
# Install durability-hardened unit: enable at boot, do NOT start compose yet.
set -eux
PKG=/var/tmp/traiding_pilot_ui_workspace/phase3_staging

sed -i 's/\r$//' \
  "$PKG/_multitf_composite_search_run.sh" \
  "$PKG/_multitf_composite_search.service" \
  "$PKG/_multitf_composite_search_sleep_hook.sh"

install -m 0755 "$PKG/_multitf_composite_search_run.sh" /usr/local/bin/multitf-composite-search-run.sh
install -m 0644 "$PKG/_multitf_composite_search.service" /etc/systemd/system/multitf-composite-search.service
install -m 0755 "$PKG/_multitf_composite_search_sleep_hook.sh" /usr/lib/systemd/system-sleep/multitf-composite-search

systemctl daemon-reload
systemctl enable multitf-composite-search.service

echo "=== VERIFY ==="
systemctl is-enabled multitf-composite-search.service
systemctl is-active multitf-composite-search.service || true
systemctl show multitf-composite-search.service \
  -p Restart -p TimeoutStopUSec -p MemoryHigh -p MemoryMax \
  -p After -p RequiresMountsFor -p FragmentPath -p UnitFileState --no-pager
systemctl cat multitf-composite-search.service --no-pager
echo INSTALL_ENABLE_OK_NO_START
