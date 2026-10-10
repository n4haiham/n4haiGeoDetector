"""Read-only browser view of the last 24 hours of county entries."""

import argparse
import csv
import datetime
import html
from io import StringIO
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from urllib.parse import urlsplit

CSV_FIELDS = ("datetime_gmt", "grid_square", "county", "county_abbr", "state_abbr")


def render_csv(entries):
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(entries)
    return output.getvalue()


def recent_entries(log_path, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(hours=24)
    entries = []
    try:
        with open(log_path, newline="", encoding="utf-8") as source:
            for row in csv.DictReader(source):
                if row.get("event") != "county_entered":
                    continue
                try:
                    timestamp = datetime.datetime.strptime(
                        row["datetime_gmt"], "%Y-%m-%d %H:%M:%S GMT"
                    ).replace(tzinfo=datetime.timezone.utc)
                except (KeyError, ValueError, TypeError):
                    continue
                if cutoff <= timestamp <= now:
                    entries.append((timestamp, row))
    except FileNotFoundError:
        pass
    entries.sort(key=lambda entry: entry[0], reverse=True)
    return [row for _timestamp, row in entries]


def render_page(entries):
    fields = CSV_FIELDS
    rows = "".join("<tr>" + "".join(
        f"<td>{html.escape(row.get(field) or '')}</td>" for field in fields
    ) + "</tr>" for row in entries)
    if not rows:
        rows = '<tr><td colspan="5">No county changes in the last 24 hours.</td></tr>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="15">
<title>County changes</title>
<style>
body {{font-family:system-ui,sans-serif;margin:24px;background:#151719;color:#eee}}
.table {{overflow-x:auto}} table {{border-collapse:collapse;width:100%}}
th,td {{text-align:left;padding:12px;border-bottom:1px solid #444}}
th {{background:#292d31}} tbody tr:nth-child(even) {{background:#202427}}
p {{color:#bfc6ce}}
.download {{display:inline-block;padding:10px 16px;margin-bottom:18px;
background:#eee;color:#151719;border-radius:6px;text-decoration:none;font-weight:600}}
</style></head><body><h1>County changes</h1>
<p>Last 24 hours · newest first · times in GMT · refreshes every 15 seconds</p>
<a class="download" href="/counties.csv" download>Download CSV</a>
<div class="table"><table><thead><tr><th scope="col">Date/time (GMT)</th>
<th scope="col">Grid square</th><th scope="col">County</th>
<th scope="col">County abbreviation</th><th scope="col">State</th></tr></thead>
<tbody>{rows}</tbody></table></div></body></html>"""


def make_server(log_path, host, port, lock=None):
    lock = lock or threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlsplit(self.path).path
            if path not in ("/", "/counties", "/counties.csv"):
                self.send_error(404)
                return
            try:
                with lock:
                    entries = recent_entries(log_path)
            except OSError:
                self.send_error(500, "Unable to read county history")
                return
            download = path == "/counties.csv"
            body = (render_csv(entries) if download else render_page(entries)).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8" if download
                             else "text/html; charset=utf-8")
            if download:
                self.send_header("Content-Disposition", 'attachment; filename="county_changes_24h.csv"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", required=True, help="Path to county_entries.csv")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args()
    server = make_server(args.log, args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
