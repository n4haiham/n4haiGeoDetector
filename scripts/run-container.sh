#!/usr/bin/env bash
set -euo pipefail

config=${1:-/etc/n4hai-geodetector.env}
if [[ ! -r "$config" ]]; then
    echo "Configuration not readable: $config" >&2
    exit 1
fi
# This file is trusted shell configuration; the installer makes it root-owned.
source "$config"
: "${IMAGE:=n4hai-geodetector:local}"
: "${GPS_DEVICE:=/dev/ttyUSB0}"
: "${GPS_RATE:=4800}"
: "${FB_DEVICE:=/dev/fb0}"
: "${FLIP_SCREEN:=false}"
: "${HISTORY_PORT:=8081}"
: "${BOUNDARY_FILE:=}"

for device in "$GPS_DEVICE" "$FB_DEVICE"; do
    if [[ ! -c "$device" ]]; then
        echo "Waiting for character device: $device" >&2
        exit 1
    fi
done

docker_args=(run --rm --init --name n4hai-geodetector
    --network host
    --device "$GPS_DEVICE:/dev/gps"
    --device "$FB_DEVICE:/dev/fb0"
    --mount type=volume,source=n4hai-geodetector-data,target=/data
    --mount type=bind,source=/sys,target=/host-sys,readonly
    --mount type=bind,source=/proc/uptime,target=/host-uptime,readonly
    --log-opt max-size=10m --log-opt max-file=3)
app_args=(python displaygeo.py --port /dev/gps --rate "$GPS_RATE" --history-port "$HISTORY_PORT")
case "${FLIP_SCREEN,,}" in
    true|1|yes) app_args+=(--flip-screen) ;;
    false|0|no) ;;
    *) echo "FLIP_SCREEN must be true or false" >&2; exit 1 ;;
esac
echo "LCD configuration: FB_DEVICE=$FB_DEVICE FLIP_SCREEN=$FLIP_SCREEN IMAGE=$IMAGE"
if [[ -n "$BOUNDARY_FILE" ]]; then
    if [[ "$BOUNDARY_FILE" != /* || ( ! -f "$BOUNDARY_FILE" && ! -d "$BOUNDARY_FILE" ) ]]; then
        echo "BOUNDARY_FILE must be an existing absolute file or directory path" >&2
        exit 1
    fi
    docker_args+=(--mount "type=bind,source=$BOUNDARY_FILE,target=/boundary-override,readonly")
    app_args+=(--boundary /boundary-override)
else
    app_args+=(--boundary /app/boundaries)
fi
exec docker "${docker_args[@]}" "$IMAGE" "${app_args[@]}"
