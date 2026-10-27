"""Read local GPSD TPV/SKY reports without opening the receiver's serial port.

GPSD remains the sole hardware reader; Chrony and cgps can remain connected.
"""
import datetime
import json
import logging
import math
import socket
import threading
import time

from arGeoDetector import geoMsg

LOG = logging.getLogger("gpsd")


def gps_utc(value):
    """Return a timezone-aware UTC datetime from a GPSD ISO8601 timestamp."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
            datetime.timezone.utc
        )
    except ValueError:
        return None


class GPSDReader(threading.Thread):
    def __init__(self, detector, callback, host="127.0.0.1", port=2947):
        super().__init__(daemon=True, name="GPSDReader")
        self.detector = detector
        self.callback = callback
        self.host = host
        self.port = int(port)
        self._stop_event = threading.Event()
        self._socket = None
        self._satellites = None
        self._last_fix = None

    def stop(self):
        self._stop_event.set()
        if self._socket is not None:
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._socket.close()
            except OSError:
                pass

    def run(self):
        while not self._stop_event.is_set():
            try:
                LOG.info("Connecting to GPSD at %s:%s", self.host, self.port)
                with socket.create_connection((self.host, self.port), timeout=5) as sock:
                    self._socket = sock
                    sock.settimeout(5)
                    sock.sendall(b'?WATCH={"enable":true,"json":true};\n')
                    buffer = b""
                    while not self._stop_event.is_set():
                        try:
                            data = sock.recv(16384)
                        except socket.timeout:
                            continue
                        if not data:
                            raise ConnectionError("GPSD closed the connection")
                        buffer += data
                        if len(buffer) > 1048576:
                            raise ValueError("GPSD message buffer exceeded 1 MiB")
                        while b"\n" in buffer:
                            line, buffer = buffer.split(b"\n", 1)
                            try:
                                report = json.loads(line.decode("utf-8"))
                                self._handle(report)
                            except (ValueError, UnicodeError, TypeError) as exc:
                                LOG.warning("Ignoring malformed GPSD report: %s", exc)
            except (OSError, ConnectionError, ValueError) as exc:
                if not self._stop_event.is_set():
                    LOG.warning("GPSD unavailable: %s; retrying", exc)
            finally:
                self._socket = None
            self._stop_event.wait(3)

    def _handle(self, report):
        kind = report.get("class")
        if kind == "SKY":
            used = report.get("uSat")
            if used is None:
                used = sum(bool(s.get("used")) for s in report.get("satellites", []))
            self._satellites = used
            if self._last_fix is not None:
                self.callback((geoMsg.GPS_STATUS, (self._last_fix, used)))
            return
        if kind != "TPV":
            return
        mode = int(report.get("mode") or 0)
        self._last_fix = 1 if mode >= 2 else 0
        self.callback((geoMsg.GPS_STATUS, (self._last_fix, self._satellites)))
        if mode < 2:
            return
        lat, lon = report.get("lat"), report.get("lon")
        if not all(isinstance(v, (float, int)) and math.isfinite(v) for v in (lat, lon)):
            return
        timestamp = gps_utc(report.get("time"))
        if timestamp is None:
            return  # Do not label a county entry with an unverified system timestamp.
        self.detector.gps_datetime = timestamp
        self.detector.gps_lock = True
        self.callback((geoMsg.TIME, timestamp))
        xy = (float(lon), float(lat))
        grid = self.detector.calcGridSquare(xy)
        county = self.detector.findCAIC(xy)
        if county is None:
            return
        self.callback((geoMsg.GRID, grid))
        self.callback((geoMsg.CNTY, (county.name, county.abbr, county.state_abbr)))
        changed = 0
        if self.detector.last_grid != grid:
            self.detector.last_grid = grid
            changed |= 1
        identity = (county.state_abbr, county.abbr, county.name)
        if self.detector.last_qth != identity:
            self.detector.last_qth = identity
            changed |= 2
        if changed:
            self.callback((geoMsg.NOTIF, changed))
            LOG.info("%s %s(%s) GPS UTC %s", grid, county.name, county.abbr,
                     timestamp.isoformat())
