#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
Browser preview for displaygeo.generateLCDImage.

This serves the same 480x320 image generated for the Raspberry Pi LCD as a PNG
so it can be checked from a local web browser.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from optparse import OptionParser
import signal
import sys
import threading
import time
import urllib.parse

from displaygeo import GeoDisplay, HEIGHT, WIDTH, generateLCDImage


class MockGeoDisplay:
    def __init__(self, county, county_abbr, grid):
        self.lock = threading.Lock()
        self.county = county
        self.county_abbr = county_abbr
        self.grid = grid

    def get_county_grid(self):
        with self.lock:
            return self.county, self.county_abbr, self.grid

    def update(self, county=None, county_abbr=None, grid=None):
        with self.lock:
            if county is not None:
                self.county = county
            if county_abbr is not None:
                self.county_abbr = county_abbr
            if grid is not None:
                self.grid = grid


def make_handler(geo_display):
    class LCDPreviewHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/":
                self.send_index()
                return
            if parsed.path == "/lcd.png":
                self.send_lcd_png()
                return
            if parsed.path == "/set":
                self.update_mock(parsed.query)
                return
            self.send_error(404)

        def do_HEAD(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/":
                self.send_index(send_body=False)
                return
            if parsed.path == "/lcd.png":
                self.send_lcd_png(send_body=False)
                return
            self.send_error(404)

        def log_message(self, fmt, *args):
            print("%s - - [%s] %s" % (
                self.client_address[0],
                self.log_date_time_string(),
                fmt % args
            ), file=sys.stderr)

        def send_index(self, send_body=True):
            body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>n4haiGeoDetector LCD Preview</title>
  <style>
    html, body {{
      height: 100%;
      margin: 0;
      background: #202124;
      color: #f1f3f4;
      font: 16px system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    body {{
      display: grid;
      place-items: center;
    }}
    main {{
      width: min(100vw - 24px, {WIDTH}px);
    }}
    .screen {{
      width: 100%;
      aspect-ratio: {WIDTH} / {HEIGHT};
      image-rendering: pixelated;
      background: black;
      box-shadow: 0 16px 40px rgba(0, 0, 0, .45);
    }}
    .meta {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      margin-top: 10px;
      color: #c7c9cc;
      font-size: 13px;
    }}
    code {{
      color: #fff;
    }}
  </style>
</head>
<body>
  <main>
    <img id="lcd" class="screen" src="/lcd.png" width="{WIDTH}" height="{HEIGHT}" alt="LCD preview">
    <div class="meta">
      <span>{WIDTH}x{HEIGHT} LCD image</span>
      <span>Auto-refreshing</span>
    </div>
  </main>
  <script>
    const img = document.getElementById("lcd");
    setInterval(() => {{
      img.src = "/lcd.png?ts=" + Date.now();
    }}, 1000);
  </script>
</body>
</html>
"""
            encoded = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            if send_body:
                self.wfile.write(encoded)

        def send_lcd_png(self, send_body=True):
            img = generateLCDImage(geo_display)
            buf = BytesIO()
            img.save(buf, format="PNG")
            data = buf.getvalue()

            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if send_body:
                self.wfile.write(data)

        def update_mock(self, query):
            if not isinstance(geo_display, MockGeoDisplay):
                self.send_error(400, "The /set endpoint is only available in mock mode")
                return

            params = urllib.parse.parse_qs(query)
            geo_display.update(
                county=params.get("county", [None])[0],
                county_abbr=params.get("abbr", [None])[0],
                grid=params.get("grid", [None])[0],
            )
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()

    return LCDPreviewHandler


def make_geo_display(opts):
    if opts.mock:
        return MockGeoDisplay(opts.county, opts.abbr, opts.grid), False

    geo_display = GeoDisplay(opts)
    geo_display.start_detector()
    return geo_display, True


def main():
    parser = OptionParser()
    parser.add_option("-H", "--host", dest="host", default="127.0.0.1",
                      help="HTTP host/interface to bind, default 127.0.0.1")
    parser.add_option("-w", "--web-port", dest="web_port", type="int", default=8080,
                      help="HTTP port to bind, default 8080")
    parser.add_option("-p", "--port", dest="port",
                      help="GPS serial port")
    parser.add_option("-r", "--rate", dest="rate", type="int",
                      help="GPS serial rate")
    parser.add_option("-n", "--nmea", dest="nmeaFile",
                      help="NMEA data file for replay processing")
    parser.add_option("-b", "--boundary", dest="bndfile",
                      help="Boundary KML file or directory (default: ./boundaries)")
    parser.add_option("--live", action="store_false", dest="mock", default=True,
                      help="Use the GPS/replay GeoDisplay instead of mock values")
    parser.add_option("--county", dest="county", default="Fauquier",
                      help="Mock county/city name")
    parser.add_option("--abbr", dest="abbr", default="FAU",
                      help="Mock county/city abbreviation")
    parser.add_option("--grid", dest="grid", default="FM18aw",
                      help="Mock grid square")

    opts, _args = parser.parse_args()
    geo_display, should_stop = make_geo_display(opts)
    server = ThreadingHTTPServer((opts.host, opts.web_port), make_handler(geo_display))

    def shutdown(_sig=None, _frame=None):
        if should_stop:
            geo_display.stop_detector()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    url_host = "localhost" if opts.host in ("", "0.0.0.0", "127.0.0.1") else opts.host
    print(f"LCD preview available at http://{url_host}:{opts.web_port}/")
    try:
        server.serve_forever()
    finally:
        if should_stop:
            geo_display.stop_detector()
        server.server_close()
        time.sleep(0.1)


if __name__ == "__main__":
    main()
