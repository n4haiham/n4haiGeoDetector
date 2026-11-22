#!/usr/bin/env bash
# Standalone Raspberry Pi OS installer for PiScreen-compatible ILI9486 SPI LCDs.
set -Eeuo pipefail

usage() {
    cat <<'HELP'
Usage: sudo bash install-lcd.sh [--framebuffer /dev/fb0] [--rotate 270]
Installs the built-in piscreen driver for a 480x320 ILI9486 SPI LCD.
Wiring (BCM): SPI0 CE0 display, CE1 touch, DC24, RESET25, LED22, touch IRQ17.
Rotation: 0, 90, 180, 270. Default 270 gives landscape with this driver.
After reboot, a systemd service displays "LCD is working" in white on black.
No automatic reboot. Requires Raspberry Pi OS and an internet connection.
HELP
}
fail() { echo "LCD installer: $*" >&2; exit 1; }
fb=/dev/fb0
rotation=270
mode=install
while (($#)); do
    case "$1" in
        --framebuffer) [[ $# -ge 2 ]] || fail 'Missing framebuffer'; fb=$2; shift 2 ;;
        --rotate) [[ $# -ge 2 ]] || fail 'Missing rotation'; rotation=$2; shift 2 ;;
        --display) mode=display; shift ;;
        -h|--help) usage; exit 0 ;;
        *) fail "Unknown option: $1" ;;
    esac
done
[[ $EUID -eq 0 ]] || fail 'Run with sudo.'
[[ $fb =~ ^/dev/fb[0-9]+$ ]] || fail 'Expected /dev/fb followed by a number.'
[[ $rotation =~ ^(0|90|180|270)$ ]] || fail 'Invalid rotation.'

if [[ $mode == display ]]; then
    # Wait for the boot-loaded SPI framebuffer. Do not write into an HDMI fb.
    for ((attempt=0; attempt<30; attempt++)); do
        [[ -c $fb ]] && break
        sleep 1
    done
    /usr/bin/python3 - "$fb" <<'PY'
import array
import fcntl
from pathlib import Path
import sys
from PIL import Image, ImageDraw, ImageFont

path = sys.argv[1]
info = Path('/sys/class/graphics') / Path(path).name
name = (info / 'name').read_text().strip()
if 'ili9486' not in name.lower():
    raise SystemExit(f'Refusing to draw on {path}: driver is {name!r}, expected ILI9486. '
                     'Check /sys/class/graphics/fb*/name and select --framebuffer.')
with open(path, 'r+b', buffering=0) as output:
    var = array.array('I', [0] * 40)
    fcntl.ioctl(output, 0x4600, var, True)  # FBIOGET_VSCREENINFO
    width, height, _, _, xoff, yoff, bpp = var[:7]
    if (width, height) not in ((480, 320), (320, 480)) or bpp not in (16, 24, 32):
        raise SystemExit(f'Unsupported framebuffer: {width}x{height}, {bpp} bpp')
    stride = int((info / 'stride').read_text())
    fields = [tuple(var[i:i+3]) for i in (8, 11, 14, 17)]
    if any(msb or offset + length > bpp for offset, length, msb in fields):
        raise SystemExit('Unsupported framebuffer channel layout')
    if (width, height) != (480, 320) or bpp != 16 or fields[:3] != [(11, 5, 0), (5, 6, 0), (0, 5, 0)]:
        raise SystemExit('Expected 480x320 RGB565, matching test_lcd.py; check rotation and driver.')

    # Same fit-to-screen and centering logic as test_lcd.py's callsign_image().
    WIDTH, HEIGHT = 480, 320
    image = Image.new("RGB", (WIDTH, HEIGHT), "black")
    draw = ImageDraw.Draw(image)
    text = "LCD is working"
    for size in range(HEIGHT, 0, -1):
        font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', size)
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        if right - left <= WIDTH - 20 and bottom - top <= HEIGHT - 20:
            break
    draw.text(((WIDTH - (right - left)) // 2 - left,
               (HEIGHT - (bottom - top)) // 2 - top),
              text, font=font, fill="white")

    # RGB565 packing from the write_fb() used by test_lcd.py.
    # Respect the device's row stride and visible framebuffer offset.
    pixels = image.load()
    for y in range(HEIGHT):
        row = bytearray()
        for x in range(WIDTH):
            r, g, b = pixels[x, y]
            rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            row.extend(rgb565.to_bytes(2, byteorder=sys.byteorder))
        output.seek((y + yoff) * stride + xoff * 2)
        output.write(row)
print(f'Displayed "LCD is working" on {path} ({name}).')
PY
    exit 0
fi

[[ -r /proc/device-tree/model ]] || fail 'This installer requires a Raspberry Pi.'
grep -q 'Raspberry Pi' /proc/device-tree/model || fail 'Not a Raspberry Pi.'
config=/boot/firmware/config.txt
[[ -f $config ]] || config=/boot/config.txt
[[ -f $config ]] || fail 'Cannot find boot config.txt.'
boot_dir=$(dirname "$config")
[[ -f $boot_dir/overlays/piscreen.dtbo ]] || fail 'piscreen overlay missing; update Raspberry Pi OS first.'
# Detect existing display drivers rather than stacking incompatible overlays.
if grep -Eq '^[[:space:]]*dtoverlay=.*(piscreen|waveshare|ili9486|fbtft)' "$config"; then
    if ! grep -q '^# BEGIN N4HAI LCD$' "$config"; then
        fail "Existing LCD overlay in $config. Back up and remove that LCD overlay before installing."
    fi
fi
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3-pil fonts-dejavu-core
cp -a "$config" "${config}.lcd-backup-$(date +%Y%m%dT%H%M%S)"
/usr/bin/python3 - "$config" "$rotation" <<'PY'
from pathlib import Path
import re
import sys
path = Path(sys.argv[1])
text = path.read_text()
text = re.sub(r'\n?# BEGIN N4HAI LCD\n.*?# END N4HAI LCD\n?', '\n', text, flags=re.S)
text += ('\n# BEGIN N4HAI LCD\n[all]\ndtparam=spi=on\n'
         f'dtoverlay=piscreen,speed=16000000,rotate={sys.argv[2]}\n# END N4HAI LCD\n')
path.write_text(text)
PY
source_script=$(readlink -f "${BASH_SOURCE[0]}")
installed_script=/usr/local/sbin/n4hai-lcd-install
if [[ $source_script != "$installed_script" ]]; then
    install -m 755 "$source_script" "$installed_script"
fi
cat > /etc/systemd/system/n4hai-lcd-test.service <<UNIT
[Unit]
Description=Show LCD installation test message
After=systemd-udev-trigger.service
Before=n4hai-geodetector.service

[Service]
Type=oneshot
ExecStart=$installed_script --display --framebuffer $fb
RemainAfterExit=yes
TimeoutStartSec=45

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable n4hai-lcd-test.service
printf '\nDriver configured. Reboot to load it: sudo reboot\n'
printf 'After reboot the LCD will display "LCD is working".\n'
printf 'Check: sudo journalctl -u n4hai-lcd-test.service -b --no-pager\n'
printf 'If another app writes the LCD, it may replace the message.\n'
printf 'Disable the boot test when finished: sudo systemctl disable n4hai-lcd-test.service\n'
