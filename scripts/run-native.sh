#!/usr/bin/env bash
set -euo pipefail
source /etc/n4hai-geodetector-native.env
cd /opt/n4hai-geodetector
args=(--framebuffer "$FB_DEVICE" --port "$GPS_DEVICE" --rate "$GPS_RATE" --boundary "$BOUNDARY_FILE" --history-port "${HISTORY_PORT:-8081}")
[[ "${FLIP_SCREEN:-false}" == true ]] && args+=(--flip-screen)
exec /opt/n4hai-geodetector/.venv/bin/python -u displaygeo.py "${args[@]}"
