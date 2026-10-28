#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo "Run: sudo bash install.sh" >&2; exit 1; }
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP=/opt/n4hai-geodetector
DATA=/var/lib/n4hai-geodetector
ENVFILE=/etc/n4hai-geodetector.env
SERVICE=n4hai-geodetector.service
echo "n4haiGeoDetector native Python installer (v1 preview)"
[[ -f "$ROOT/displaygeo.py" && -f "$ROOT/requirements.txt" ]] || { echo "Run from the repository checkout." >&2; exit 1; }
command -v systemctl >/dev/null || { echo "systemd is required"; exit 1; }
[[ -r /etc/os-release ]] && . /etc/os-release
[[ "${ID:-}" == "raspbian" || "${ID:-}" == "debian" ]] || echo "WARNING: Not a tested Raspberry Pi OS/Debian system."
[[ -r /proc/device-tree/model ]] && { printf 'Hardware: '; tr -d '\0' </proc/device-tree/model; echo; } || echo "WARNING: Raspberry Pi model not detected."
echo "Checking LCD framebuffer (480x320 RGB565 required)..."
mapfile -t FBS < <(find /dev -maxdepth 1 -name 'fb[0-9]*' -print | sort)
(("${#FBS[@]}" > 0)) || { echo "No framebuffer found. Configure the LCD driver first."; exit 1; }
for f in "${FBS[@]}"; do echo "  $f"; done
read -r -p "LCD framebuffer [${FBS[0]}]: " FB
FB="${FB:-${FBS[0]}}"
[[ -c "$FB" ]] || { echo "Not a framebuffer device: $FB"; exit 1; }
if command -v fbset >/dev/null; then
  fbset -fb "$FB" -i || true
fi
read -r -p "Confirm this is a 480x320 RGB565 framebuffer (y/N): " OK
[[ "${OK,,}" == y || "${OK,,}" == yes ]] || { echo "Configure/test LCD first."; exit 1; }
echo "USB serial candidates:"
find /dev/serial/by-id -maxdepth 1 -type l -print 2>/dev/null || true
ls /dev/ttyACM* /dev/ttyUSB* 2>/dev/null || true
read -r -p "GPS serial device (prefer /dev/serial/by-id/...): " GPS
[[ -c "$GPS" ]] || { echo "GPS serial device missing: $GPS"; exit 1; }
read -r -p "GPS baud rate [4800]: " RATE
RATE="${RATE:-4800}"
[[ "$RATE" =~ ^[0-9]+$ ]] || { echo "Invalid baud rate"; exit 1; }
read -r -p "Flip LCD 180 degrees? (y/N): " FLIP
[[ "${FLIP,,}" == y || "${FLIP,,}" == yes ]] && FLIP=true || FLIP=false
BOUNDARY="$ROOT/boundaries"
if ! find "$BOUNDARY" -maxdepth 1 -iname '*.kml' -print -quit 2>/dev/null | grep -q .; then
  echo "No county KML files in $BOUNDARY."
  read -r -p "Absolute path to KML file or directory: " BOUNDARY
fi
[[ -f "$BOUNDARY" || -d "$BOUNDARY" ]] || { echo "Boundary path not found"; exit 1; }
if [[ -d "$BOUNDARY" ]] && ! find "$BOUNDARY" -maxdepth 1 -iname '*.kml' -print -quit | grep -q .; then echo "No KML files"; exit 1; fi
echo "Installing dependencies..."
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv python3-pip git fonts-dejavu-core fbset iw
install -d -m 755 "$APP" "$DATA" /etc
# Preserve the old service and its configuration before replacing either.
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$DATA/backup-$STAMP"
mkdir -p "$BACKUP"
[[ -f /etc/systemd/system/$SERVICE ]] && cp -a "/etc/systemd/system/$SERVICE" "$BACKUP/" || true
[[ -f "$ENVFILE" ]] && cp -a "$ENVFILE" "$BACKUP/" || true
if systemctl is-active --quiet "$SERVICE"; then
  echo "Existing service is active (possibly Docker). It will be stopped only at cutover."
  read -r -p "Proceed with native replacement? (y/N): " CONFIRM
  [[ "${CONFIRM,,}" == y || "${CONFIRM,,}" == yes ]] || exit 1
fi
# Never delete the Docker volume or source checkout.
tar -C "$ROOT" --exclude=.git --exclude=.venv --exclude=__pycache__ --exclude='*.pyc' -cf - . | tar -C "$APP" -xf -
python3 -m venv "$APP/.venv"
"$APP/.venv/bin/python" -m pip install -r "$APP/requirements.txt"
# Store boundary data outside the source tree when provided externally.
if [[ "$BOUNDARY" != "$ROOT/boundaries" ]]; then
  mkdir -p "$DATA/boundaries"
  if [[ -d "$BOUNDARY" ]]; then cp -a "$BOUNDARY"/. "$DATA/boundaries/"; else cp -a "$BOUNDARY" "$DATA/boundaries/"; fi
  BOUNDARY="$DATA/boundaries"
else
  BOUNDARY="$APP/boundaries"
fi
# The current Python app uses HOME/.config/arGeoDetector for persistent history.
install -d -m 700 "$DATA/.config/arGeoDetector"
if [[ ! -f "$DATA/.config/arGeoDetector/county_entries.csv" ]]; then
  echo "NOTE: Existing Docker volume history is not automatically migrated; see README."
fi
# Use a separate native environment file; do not overwrite Docker settings.
NATIVE_ENV=/etc/n4hai-geodetector-native.env
printf 'GPS_DEVICE=%q\nGPS_RATE=%q\nFB_DEVICE=%q\nFLIP_SCREEN=%q\nBOUNDARY_FILE=%q\nHISTORY_PORT=8081\n' "$GPS" "$RATE" "$FB" "$FLIP" "$BOUNDARY" > "$NATIVE_ENV"
chmod 600 "$NATIVE_ENV"
install -m 755 "$ROOT/scripts/run-native.sh" /usr/local/bin/n4hai-geodetector-native
systemctl stop "$SERVICE" 2>/dev/null || true
install -m 644 "$ROOT/deploy/n4hai-geodetector-native.service" "/etc/systemd/system/$SERVICE"
systemctl daemon-reload
systemctl enable "$SERVICE"
echo "Installed. Backup: $BACKUP"
echo "LCD and GPS need physical verification. Start: sudo systemctl start $SERVICE"
echo "Logs: sudo journalctl -u $SERVICE -f"
