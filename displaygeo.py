#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
Created on 5/22/2026
@author: Thomas Foy N4HAI
         n4hai@arrl.net
"""


from PIL import Image, ImageDraw, ImageFont
import signal
import subprocess
import sys
import threading
import time
from optparse import OptionParser

from arGeoDetector import geoBase, geoMsg

WIDTH = 480
HEIGHT = 320


def find_font(paths):
    for path in paths:
        try:
            ImageFont.truetype(path, 12)
            return path
        except OSError:
            pass
    return None


FONT_BOLD = find_font([
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
])
FONT_REGULAR = find_font([
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
])


def load_font(font_path, size):
    if font_path:
        return ImageFont.truetype(font_path, size)
    return ImageFont.load_default()


font_med = load_font(FONT_REGULAR, 32)

font_small = load_font(FONT_REGULAR, 24)


class GeoDisplay(geoBase):
    def __init__(self, opts):
        self.lock = threading.Lock()
        self.county = "Unknown"
        self.county_abbr = "UNK"
        self.grid = "------"
        self.status = ""
        self.detector_thread = None
        super().__init__(opts, self.geoCB)

        bnd = self.config.get('BOUNDARY','file', fallback=None)
        if bnd:
            self.geoDet.loadBoundaries(bnd)

    def geoCB(self, msg):
        msg_type, value = msg
        with self.lock:
            if msg_type == geoMsg.GRID:
                self.grid = value
            elif msg_type == geoMsg.CNTY:
                self.county, self.county_abbr = value
            elif msg_type == geoMsg.STAT:
                self.status = value

    def get_county_grid(self):
        with self.lock:
            county = self.county
            if self.county_abbr and self.county_abbr != "UNK":
                county = f"{county} ({self.county_abbr})"
            return county, self.grid

    def start_detector(self):
        if self.mode == 1:
            self.detector_thread = threading.Thread(
                target=self.geoDet.replayFile,
                args=(self.replayFile, 0.001),
                daemon=True
            )
            self.detector_thread.start()
            return

        try:
            self.serial.port = self.config.get('SERIAL','port')
            self.serial.baudrate = int(self.config.get('SERIAL','rate', fallback=4800))
        except Exception:
            print("Error: Serial port parameters not provided! Pass --port parameter.", file=sys.stderr)
            sys.exit(1)

        self.geoDet.mode = 1
        self.geoDet.state = 1
        self.geoDet.start()
        self.detector_thread = self.geoDet

    def stop_detector(self):
        self.geoDet.stop()
        if self.detector_thread and self.detector_thread.is_alive():
            self.detector_thread.join(timeout=5)
        self.writeSettings()


def cmd(c):
    try:
        return subprocess.check_output(
            c,
            shell=True,
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=2
        ).strip()
    except Exception:
        return "n/a"


def write_fb(img, device="/dev/fb0"):
    img = img.convert("RGB")
    pixels = img.load()

    buf = bytearray()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            r, g, b = pixels[x, y]
            rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)

            # Framebuffer pixels are native-endian words (little-endian on Pi).
            buf.extend(rgb565.to_bytes(2, byteorder=sys.byteorder))

    with open(device, "wb") as fb:
        fb.write(buf)


def fit_text(draw, text, font_path, start_size, max_width):
    size = start_size
    while size > 12:
        font = load_font(font_path, size)
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return font
        size -= 2
    return load_font(font_path, size)


def generateLCDImage(geo_display):
    # Create black background
    img = Image.new("RGB", (WIDTH, HEIGHT), "black")
    draw = ImageDraw.Draw(img)

    # Get County and grid
    county, grid = geo_display.get_county_grid()


    # Get system info
    utc_datetime = cmd("date -u '+%d %b %Y %H:%M:%S'")
    ip_addr = cmd("hostname -I | awk '{print $1}'")
    raw_temp = cmd("cat /sys/class/thermal/thermal_zone0/temp")

    try:
        cpu_temp = f"{int(raw_temp)/1000:.1f} C"
    except:
        cpu_temp = "n/a"

    county_font = fit_text(
        draw,
        county,
        FONT_BOLD,
        72,
        WIDTH - 40
    )
    county_bbox = draw.textbbox((0, 0), county, font=county_font)
    county_x = max(20, (WIDTH - (county_bbox[2] - county_bbox[0])) // 2)

    grid_bbox = draw.textbbox((0, 0), grid, font=font_med)
    grid_x = max(20, (WIDTH - (grid_bbox[2] - grid_bbox[0])) // 2)

    # Draw text
    draw.text((county_x, 40), county, fill="white", font=county_font)
    draw.text((grid_x, 135), grid, fill="white", font=font_med)
    draw.text((80, 180), utc_datetime, fill="white", font=font_small)
    draw.text((20, 260), f"IP: {ip_addr}", fill="white", font=font_small)
    draw.text((320, 260), cpu_temp, fill="white", font=font_small)
    return img

def main():
    parser = OptionParser()
    parser.add_option("-p", "--port", dest="port",
                    help="GPS serial port")
    parser.add_option("-r", "--rate", dest="rate",type="int",
                    help="GPS serial rate")
    parser.add_option("-n", "--nmea", dest="nmeaFile",
                    help="NMEA data file for replay processing")
    parser.add_option("-b", "--boundary", dest="bndfile",
                    help="Boundary KML file or directory (default: ./boundaries)")
    opts, _args = parser.parse_args()

    geo_display = GeoDisplay(opts)
    geo_display.start_detector()

    def sigint(_sig, _frame):
        geo_display.stop_detector()
        sys.exit(0)

    signal.signal(signal.SIGINT, sigint)
    signal.signal(signal.SIGTERM, sigint)

    try:
        while True:
            if (geo_display.mode == 0 and geo_display.detector_thread
                    and not geo_display.detector_thread.is_alive()):
                raise RuntimeError("GPS detector stopped; restarting the container is required")
            img = generateLCDImage(geo_display)
            write_fb(img)
            time.sleep(0.2)
    finally:
        geo_display.stop_detector()


if __name__ == "__main__":
    main()
