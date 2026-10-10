#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
Created on 5/22/2026
@author: Thomas Foy N4HAI
         n4hai@arrl.net
"""


from PIL import Image, ImageDraw, ImageFont
import csv
import datetime
import os
import signal
import subprocess
import sys
import threading
import time
from optparse import OptionParser

from arGeoDetector import geoBase, geoMsg
from county_history_web import make_server
from pi_status import StatusCycle

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
status_cycle = StatusCycle()


class GeoDisplay(geoBase):
    def __init__(self, opts):
        self.lock = threading.Lock()
        self.county = "Unknown"
        self.county_abbr = "UNK"
        self.grid = "------"
        self.status = ""
        self.detector_thread = None
        self.state_abbr = ""
        self.entered_at = None
        self.entered_monotonic = None
        self.last_county = None
        self.county_highlight_until = 0.0
        self.grid_highlight_until = 0.0
        self.last_grid = None
        self.gps_fix = None
        self.gps_satellites = None
        self.gps_update_at = None
        super().__init__(opts, self.geoCB)
        self.county_log = os.path.join(self.appDirs.user_config_dir, "county_entries.csv")
        self.log_county_event("startup")

        bnd = self.config.get('BOUNDARY','file', fallback=None)
        if bnd:
            self.geoDet.loadBoundaries(bnd)

    def geoCB(self, msg):
        msg_type, value = msg
        with self.lock:
            if msg_type == geoMsg.GRID:
                if value not in ("", "-", "------") and value != self.last_grid:
                    self.grid_highlight_until = time.monotonic() + 1
                    self.last_grid = value
                self.grid = value
            elif msg_type == geoMsg.CNTY:
                self.county, self.county_abbr = value[:2]
                self.state_abbr = value[2] if len(value) > 2 else ""
                identity = (self.state_abbr, self.county_abbr, self.county)
                if self.county_abbr not in ("", "UNK", "-") and identity != self.last_county:
                    self.entered_at = datetime.datetime.now(datetime.timezone.utc)
                    self.entered_monotonic = time.monotonic()
                    self.county_highlight_until = self.entered_monotonic + 60
                    self.last_county = identity
                    self.log_county_event("county_entered", self.entered_at)
            elif msg_type == geoMsg.STAT:
                self.status = value
            elif msg_type == geoMsg.GPS_STATUS:
                self.gps_fix, self.gps_satellites = value
                self.gps_update_at = time.monotonic()

    def get_county_grid(self):
        with self.lock:
            return self.county, self.county_abbr, self.grid

    def get_gps_status(self, show_age=False):
        with self.lock:
            if self.gps_update_at is None:
                return 'GPS update: waiting' if show_age else 'GPS fix/sats: waiting'
            age = max(0, int(time.monotonic() - self.gps_update_at))
            if show_age:
                return f'GPS update: {age}s ago'
            fixes = {0: 'No fix', 1: 'GPS', 2: 'DGPS', 4: 'RTK', 5: 'Float RTK', 6: 'Estimated'}
            label = fixes.get(self.gps_fix, f'Quality {self.gps_fix}')
            return f"GPS: {label} / {self.gps_satellites} sats" + (' (stale)' if age > 15 else '')

    def get_entered_at(self):
        with self.lock:
            return self.entered_at.strftime("%H:%M") if self.entered_at else "--:--"

    def get_here_for(self):
        with self.lock:
            if self.entered_monotonic is None:
                return "--:--"
            minutes = max(0, int((time.monotonic() - self.entered_monotonic) // 60))
            hours, minutes = divmod(minutes, 60)
            return f"{hours:02d}:{minutes:02d}"

    def highlight_county(self):
        with self.lock:
            return (self.county_abbr not in ("", "UNK", "-")
                    and time.monotonic() < self.county_highlight_until)

    def highlight_grid(self):
        with self.lock:
            return (self.grid not in ("", "-", "------")
                    and time.monotonic() < self.grid_highlight_until)

    def log_county_event(self, event, timestamp=None):
        timestamp = timestamp or datetime.datetime.now(datetime.timezone.utc)
        with open(self.county_log, "a", newline="", encoding="utf-8") as output:
            writer = csv.writer(output)
            if output.tell() == 0:
                writer.writerow(["datetime_gmt", "event", "grid_square", "county", "county_abbr", "state_abbr"])
            writer.writerow([timestamp.strftime("%Y-%m-%d %H:%M:%S GMT"), event,
                             self.grid, self.county, self.county_abbr, self.state_abbr])

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


def write_fb(img, device="/dev/fb0", flip_screen=False):
    if flip_screen:
        img = img.transpose(Image.Transpose.ROTATE_180)
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
    county, county_abbr, grid = geo_display.get_county_grid()
    county_abbr = county_abbr or "UNK"



    abbreviation_font = fit_text(draw, county_abbr, FONT_BOLD, 72, WIDTH - 40)
    county_font = fit_text(draw, county, FONT_REGULAR, 48, WIDTH - 40)
    highlight = (geo_display.highlight_county()
                 if hasattr(geo_display, "highlight_county") else False)
    if highlight:
        draw.rectangle((10, 8, WIDTH - 11, 88), fill="white")
    grid_highlight = (geo_display.highlight_grid()
                      if hasattr(geo_display, "highlight_grid") else False)

    # Center each line using its visible bounds, including font bearings.
    for text, font, top in (
        (county_abbr, abbreviation_font, 20),
        (county, county_font, 100),
        (grid, font_med, 165),
    ):
        left, upper, right, _bottom = draw.textbbox((0, 0), text, font=font)
        x = (WIDTH - (right - left)) // 2 - left
        if grid_highlight and top == 165:
            draw.rectangle((x + left - 12, top - 5,
                            x + right + 12, top + _bottom - upper + 5), fill="white")
        fill = "black" if ((highlight and top == 20)
                           or (grid_highlight and top == 165)) else "white"
        draw.text((x, top - upper), text, fill=fill, font=font)
    entered_at = geo_display.get_entered_at() if hasattr(geo_display, "get_entered_at") else "--:--"
    entered_text = f"Entered at {entered_at}"
    bbox = draw.textbbox((0, 0), entered_text, font=font_small)
    draw.text(((WIDTH - (bbox[2] - bbox[0])) // 2, 200), entered_text,
              fill="white", font=font_small)
    here_for = geo_display.get_here_for() if hasattr(geo_display, "get_here_for") else "--:--"
    duration_text = f"Here for {here_for}"
    bbox = draw.textbbox((0, 0), duration_text, font=font_small)
    draw.text(((WIDTH - (bbox[2] - bbox[0])) // 2, 235), duration_text,
              fill="white", font=font_small)
    status_text = status_cycle.text(geo_display)
    status_font = fit_text(draw, status_text, FONT_REGULAR, 24, WIDTH - 40)
    left, upper, right, _ = draw.textbbox((0, 0), status_text, font=status_font)
    draw.text(((WIDTH - (right - left)) // 2 - left, 280 - upper),
              status_text, fill="white", font=status_font)
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
    parser.add_option("--flip-screen", action="store_true", default=False,
                    help="Rotate the LCD image 180 degrees")
    parser.add_option("--history-host", default="0.0.0.0",
                    help="County history web interface (default: 0.0.0.0)")
    parser.add_option("--history-port", type="int", default=8081,
                    help="County history HTTP port (default: 8081; 0 disables)")
    opts, _args = parser.parse_args()
    print(f"LCD orientation: {'rotated 180 degrees' if opts.flip_screen else 'normal'}", flush=True)

    geo_display = GeoDisplay(opts)
    history_server = None

    def sigint(_sig, _frame):
        geo_display.stop_detector()
        sys.exit(0)

    signal.signal(signal.SIGINT, sigint)
    signal.signal(signal.SIGTERM, sigint)

    try:
        if opts.history_port:
            history_server = make_server(geo_display.county_log, opts.history_host,
                                         opts.history_port, geo_display.lock)
            threading.Thread(target=history_server.serve_forever, daemon=True).start()
            print(f"County history available on port {opts.history_port}", flush=True)
        geo_display.start_detector()
        while True:
            if (geo_display.mode == 0 and geo_display.detector_thread
                    and not geo_display.detector_thread.is_alive()):
                raise RuntimeError("GPS detector stopped; restarting the container is required")
            img = generateLCDImage(geo_display)
            write_fb(img, flip_screen=opts.flip_screen)
            time.sleep(0.2)
    finally:
        if history_server:
            history_server.shutdown()
            history_server.server_close()
        geo_display.stop_detector()


if __name__ == "__main__":
    main()
