import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from holiday_sync import fetch_holiday_calendar, parse_holiday_payload, read_calendar_cache, write_calendar_cache


class _Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


class HolidaySyncTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "year": 2026,
            "papers": ["https://www.gov.cn/example"],
            "days": [
                {"name": "节日", "date": "2026-10-01", "isOffDay": True},
                {"name": "调休", "date": "2026-10-10", "isOffDay": False},
            ],
        }

    def test_parse_payload(self):
        result = parse_holiday_payload(self.payload, 2026)
        self.assertEqual(result["holiday_dates"], ["2026-10-01"])
        self.assertEqual(result["workday_overrides"], ["2026-10-10"])
        self.assertEqual(result["papers"], ["https://www.gov.cn/example"])

    def test_fetch_uses_requested_year_and_normalizes_json(self):
        calls = []

        def opener(request, timeout):
            calls.append((request.full_url, timeout))
            return _Response(self.payload)

        result = fetch_holiday_calendar(2026, "https://example.test/{year}.json", opener=opener)
        self.assertEqual(calls[0][0], "https://example.test/2026.json")
        self.assertEqual(result["year"], 2026)
        self.assertTrue(result["fetched_at"])

    def test_cache_round_trip(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "holiday-cache" / "2026.json"
            calendar = parse_holiday_payload(self.payload, 2026)
            write_calendar_cache(path, calendar)
            loaded = read_calendar_cache(path, 2026)
            self.assertEqual(loaded["holiday_dates"], ["2026-10-01"])
            self.assertEqual(loaded["workday_overrides"], ["2026-10-10"])

    def test_invalid_year_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_holiday_payload(self.payload, 2025)


if __name__ == "__main__":
    unittest.main()

