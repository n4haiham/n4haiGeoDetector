"""Regression tests for GPSD TPV parsing (run with: python -m unittest discover -s tests)."""
import datetime
import unittest

from arGeoDetector import geoMsg
from gpsd_reader import GPSDReader, gps_utc


class FakeDetector:
    def __init__(self):
        self.last_grid = ""
        self.last_qth = ""
        self.gps_datetime = None
        self.gps_lock = False

    def calcGridSquare(self, xy):
        assert xy == (-83.0, 40.0)
        return "EN80aa"

    def findCAIC(self, xy):
        class County:
            name = "Franklin"
            abbr = "FRAN"
            state_abbr = "OH"
        return County()


class GPSDTests(unittest.TestCase):
    def setUp(self):
        self.detector = FakeDetector()
        self.messages = []
        self.reader = GPSDReader(self.detector, self.messages.append)

    def test_valid_position_uses_gps_utc(self):
        self.reader._handle({"class": "TPV", "mode": 3,
                             "lat": 40.0, "lon": -83.0,
                             "time": "2026-10-27T00:30:00.250Z"})
        self.assertEqual(self.detector.gps_datetime,
                         datetime.datetime(2026, 10, 27, 0, 30, 0, 250000,
                                           tzinfo=datetime.timezone.utc))
        self.assertIn((geoMsg.CNTY, ("Franklin", "FRAN", "OH")), self.messages)
        self.assertTrue(any(msg[0] == geoMsg.TIME for msg in self.messages))

    def test_missing_gps_time_does_not_register_county(self):
        self.reader._handle({"class": "TPV", "mode": 3, "lat": 40.0, "lon": -83.0})
        self.assertFalse(any(msg[0] == geoMsg.CNTY for msg in self.messages))

    def test_no_fix_is_not_a_position(self):
        self.reader._handle({"class": "TPV", "mode": 1,
                             "lat": 40.0, "lon": -83.0,
                             "time": "2026-10-27T00:30:00Z"})
        self.assertFalse(any(msg[0] == geoMsg.CNTY for msg in self.messages))

    def test_sky_satellites(self):
        self.reader._handle({"class": "SKY", "uSat": 9})
        self.reader._handle({"class": "TPV", "mode": 2,
                             "lat": 40.0, "lon": -83.0,
                             "time": "2026-10-27T00:30:00Z"})
        self.assertIn((geoMsg.GPS_STATUS, (1, 9)), self.messages)

    def test_bad_timestamp(self):
        self.assertIsNone(gps_utc("not-a-time"))


if __name__ == "__main__":
    unittest.main()
