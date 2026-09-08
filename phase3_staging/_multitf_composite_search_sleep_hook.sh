#!/bin/bash
# systemd-sleep hook: after resume from suspend, start composite search if not DONE.
# Installed as /usr/lib/systemd/system-sleep/multitf-composite-search
set -eu
phase="${1:-}"
if [ "$phase" != "post" ]; then
  exit 0
fi
DONE=/var/tmp/traiding_pilot_ui_workspace/artifacts/MULTITF-COMPOSITE-SIGNAL-SEARCH-1/composite_search_DONE
if [ -f "$DONE" ]; then
  exit 0
fi
systemctl start multitf-composite-search.service || true
