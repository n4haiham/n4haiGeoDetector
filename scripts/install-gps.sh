#!/usr/bin/env bash
# N4HAI GeoDetector GPS-disciplined NTP installer
set -Eeuo pipefail

GPS_DEVICE="${GPS_DEVICE:-/dev/ttyACM0}"
NTP_ALLOW="${NTP_ALLOW:-}" # e.g. 192.168.4.0/24; empty = no remote clients
GPS_OFFSET="${GPS_OFFSET:-0.5}" # estimated NMEA message latency (seconds)
GPS_DELAY="${GPS_DELAY:-0.2}"
BACKUP_DIR="/var/backups/n4hai-gps-ntp-$(date -u +%Y%m%dT%H%M%SZ)"

log() { printf '\n[N4HAI] %s\n' "$*"; }
fail() { printf '[N4HAI] ERROR: %s\n' "$*" >&2; exit 1; }
trap 'printf "[N4HAI] Installation stopped at line %s. Backups: %s\n" "$LINENO" "$BACKUP_DIR" >&2' ERR

[[ $EUID -eq 0 ]] || fail "Run with sudo."
[[ -c "$GPS_DEVICE" ]] || fail "GPS_DEVICE=$GPS_DEVICE is not a character device. Plug in the GPS and check /dev/serial/by-id/."
[[ "$GPS_DEVICE" =~ ^/dev/[a-zA-Z0-9_./-]+$ ]] || fail "Unexpected GPS_DEVICE path"
[[ "$GPS_OFFSET" =~ ^-?[0-9]+([.][0-9]+)?$ ]] || fail "GPS_OFFSET must be numeric"
[[ "$GPS_DELAY" =~ ^[0-9]+([.][0-9]+)?$ ]] || fail "GPS_DELAY must be nonnegative"
if [[ -n "$NTP_ALLOW" ]]; then
  [[ "$NTP_ALLOW" =~ ^[0-9a-fA-F:.]+(/[0-9]{1,3})?$ ]] || fail "NTP_ALLOW must be an IPv4/IPv6 address or CIDR, e.g. 192.168.4.0/24"
fi

log "Installing GPS and NTP packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y gpsd gpsd-clients chrony

mkdir -p "$BACKUP_DIR"
cp -a /etc/default/gpsd "$BACKUP_DIR/gpsd" 2>/dev/null || true
cp -a /etc/chrony/chrony.conf "$BACKUP_DIR/chrony.conf" 2>/dev/null || true

# gpsd uses the basename of the actual serial device for its chrony socket.
# Resolve stable /dev/serial/by-id symlinks for the refclock name.
GPS_REAL_DEVICE="$(readlink -f "$GPS_DEVICE")"
GPS_BASE="$(basename "$GPS_REAL_DEVICE")"
SOCK="/run/chrony.clk.${GPS_BASE}.sock"

log "Checking for applications already reading $GPS_REAL_DEVICE"
if command -v fuser >/dev/null 2>&1; then
  if fuser "$GPS_REAL_DEVICE" >/dev/null 2>&1; then
    echo "Processes currently have the GPS serial device open:" >&2
    fuser -v "$GPS_REAL_DEVICE" >&2 || true
    fail "Stop direct serial readers (such as GeoDetector) and rerun; gpsd must own the port."
  fi
fi

log "Configuring gpsd"
cat > /etc/default/gpsd <<CFG
# Managed by N4HAI GPS NTP installer. Backup in $BACKUP_DIR
START_DAEMON="true"
USBAUTO="false"
DEVICES="$GPS_DEVICE"
GPSD_OPTIONS="-n"
CFG

log "Configuring chrony GPS reference clock"
# Put managed lines in their own drop-in if the Debian/Raspberry Pi OS chrony
# configuration loads confdir. Otherwise append an include to the main file.
mkdir -p /etc/chrony/conf.d
if ! grep -Eq '^[[:space:]]*confdir[[:space:]]+/etc/chrony/conf\.d([[:space:]]|$)' /etc/chrony/chrony.conf; then
  printf '\n# N4HAI GPS NTP installer\nconfdir /etc/chrony/conf.d\n' >> /etc/chrony/chrony.conf
fi
cat > /etc/chrony/conf.d/n4hai-gps-ntp.conf <<CFG
# GPS NMEA timing via gpsd. Offset is an estimate; calibrate if needed.
refclock SOCK $SOCK refid GPS offset $GPS_OFFSET delay $GPS_DELAY poll 4
# Step large errors on initial sync; useful after offline power cycles.
makestep 1.0 3
CFG
if [[ -n "$NTP_ALLOW" ]]; then
  printf 'allow %s\n' "$NTP_ALLOW" >> /etc/chrony/conf.d/n4hai-gps-ntp.conf
fi

# Chrony must bind its Unix datagram socket before gpsd tries to connect.
# The drop-in orders gpsd after chrony, including at boot.
mkdir -p /etc/systemd/system/gpsd.service.d
cat > /etc/systemd/system/gpsd.service.d/n4hai-chrony-order.conf <<'CFG'
[Unit]
Wants=chrony.service
After=chrony.service
CFG

log "Starting chrony first, then gpsd"
systemctl daemon-reload
systemctl unmask chrony.service gpsd.service gpsd.socket
systemctl enable --now chrony.service
systemctl restart chrony.service
systemctl enable --now gpsd.socket
systemctl restart gpsd.service

log "Installation complete. Waiting briefly for GPS timing samples."
sleep 5
printf '\nGPS device: %s (resolved: %s)\nChrony socket: %s\n' "$GPS_DEVICE" "$GPS_REAL_DEVICE" "$SOCK"
if [[ -S "$SOCK" ]]; then echo 'Chrony GPS socket: present'; else echo 'Chrony GPS socket: NOT FOUND (check logs)'; fi
printf '\nChrony sources (GPS may take a few minutes to become selectable):\n'
chronyc sources -v || true
printf '\nTime status:\n'
timedatectl status || true
printf '\nNext: cgps -s ; chronyc sources -v ; chronyc tracking\n'
if [[ -z "$NTP_ALLOW" ]]; then
  printf 'Remote NTP clients are NOT enabled. Rerun with NTP_ALLOW=192.168.4.0/24 (adjust subnet) to enable.\n'
else
  printf 'Remote NTP clients allowed from %s (subject to host/network firewall).\n' "$NTP_ALLOW"
fi
printf 'Backups: %s\n' "$BACKUP_DIR"
