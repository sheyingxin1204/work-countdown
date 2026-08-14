import unittest
from copy import deepcopy
from datetime import datetime, date
from pathlib import Path
from tempfile import TemporaryDirectory

import work_countdown as app


class WorkCountdownTests(unittest.TestCase):
    def setUp(self):
        self.config = deepcopy(app.DEFAULT_CONFIG)
        self.config["calendar"]["weekend_rest"] = False
        self.calendar = app.WorkCalendar(self.config)
        self.schedule = app.WorkSchedule(self.config)
        self.workday = date(2026, 8, 14)

    def test_parse_clock_and_format_remaining(self):
        self.assertEqual(app.parse_clock("09:30").hour, 9)
        self.assertEqual(app.format_remaining(datetime(2026, 8, 14, 10, 0) - datetime(2026, 8, 14, 9, 1, 2)), "00:58:58")
        with self.assertRaises(ValueError):
            app.parse_clock("25:00")

    def test_date_list_is_normalized(self):
        self.assertEqual(
            app.parse_date_list("2026-10-01,\n2026-10-01\n2026-10-02"),
            ["2026-10-01", "2026-10-02"],
        )

    def test_calendar_conflict_is_rejected(self):
        with self.assertRaises(ValueError):
            app.normalize_calendar_dates(["2026-10-01"], ["2026-10-01"])

    def test_calendar_json_round_trip(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "calendar.json"
            app.write_calendar_file(
                path,
                ["2026-10-01", "2026-10-02"],
                ["2026-10-10"],
                2026,
            )
            loaded = app.read_calendar_file(path)
            self.assertEqual(loaded["year"], 2026)
            self.assertEqual(loaded["holiday_dates"], ["2026-10-01", "2026-10-02"])
            self.assertEqual(loaded["workday_overrides"], ["2026-10-10"])

    def test_calendar_holiday_and_workday_override(self):
        saturday = date(2026, 8, 15)
        self.config["calendar"]["weekend_rest"] = True
        self.config["calendar"]["holiday_dates"] = ["2026-08-14"]
        self.config["calendar"]["workday_overrides"] = ["2026-08-15"]
        calendar = app.WorkCalendar(self.config)
        self.assertFalse(calendar.is_workday(self.workday))
        self.assertTrue(calendar.is_workday(saturday))

    def test_schedule_state_boundaries(self):
        cases = (
            ("before_work", datetime(2026, 8, 14, 8, 59)),
            ("morning", datetime(2026, 8, 14, 9, 0)),
            ("lunch", datetime(2026, 8, 14, 12, 0)),
            ("afternoon", datetime(2026, 8, 14, 13, 30)),
            ("off_work", datetime(2026, 8, 14, 18, 0)),
        )
        for expected_kind, moment in cases:
            with self.subTest(expected_kind=expected_kind):
                self.assertEqual(self.schedule.state(moment, self.calendar)["kind"], expected_kind)

    def test_flexible_segments_and_overtime(self):
        config = deepcopy(self.config)
        config["schedule"]["work_segments"] = [
            {"start": "08:30", "end": "11:30"},
            {"start": "12:30", "end": "15:00"},
            {"start": "16:00", "end": "18:00"},
        ]
        config["schedule"]["overtime_end"] = "20:00"
        schedule = app.WorkSchedule(config)
        self.assertEqual(schedule.state(datetime(2026, 8, 14, 12, 0), self.calendar)["kind"], "lunch")
        self.assertEqual(schedule.state(datetime(2026, 8, 14, 15, 30), self.calendar)["kind"], "break")
        self.assertEqual(schedule.state(datetime(2026, 8, 14, 19, 0), self.calendar)["kind"], "overtime")

    def test_notification_lead_time_and_deduplication(self):
        widget = app.CountdownWidget.__new__(app.CountdownWidget)
        widget.last_state_kind = None
        widget.last_state_date = None
        widget.sent_alerts = set()
        widget.config = {"notifications": {
            "enabled": True,
            "lunch": True,
            "off_work": True,
            "sound": False,
            "lead_minutes": 10,
            "quiet_hours": {"enabled": False, "start": "22:00", "end": "08:00"},
        }}
        widget.schedule = self.schedule
        widget.calendar = self.calendar
        calls = []
        widget.notify_user = lambda title, message, notifications: calls.append(title)
        widget.maybe_notify({"kind": "morning"}, datetime(2026, 8, 14, 11, 50))
        widget.maybe_notify({"kind": "lunch"}, datetime(2026, 8, 14, 12, 0))
        widget.maybe_notify({"kind": "lunch"}, datetime(2026, 8, 14, 12, 1))
        self.assertEqual(calls, ["午休提醒", "午休提醒"])

    def test_quiet_hours_supports_cross_midnight_window(self):
        widget = app.CountdownWidget.__new__(app.CountdownWidget)
        widget.config = {"notifications": {
            "quiet_hours": {"enabled": True, "start": "22:00", "end": "08:00"},
        }}
        self.assertTrue(widget.is_quiet_hours(datetime(2026, 8, 14, 23, 0)))
        self.assertTrue(widget.is_quiet_hours(datetime(2026, 8, 14, 7, 59)))
        self.assertFalse(widget.is_quiet_hours(datetime(2026, 8, 14, 12, 0)))

    def test_legacy_schedule_still_works(self):
        config = deepcopy(self.config)
        config["schedule"].pop("work_segments", None)
        schedule = app.WorkSchedule(config)
        self.assertEqual(schedule.morning_range_text(), "09:00 - 12:00")

    def test_progress_is_clamped(self):
        self.assertEqual(self.schedule.progress(datetime(2026, 8, 14, 8, 0), self.calendar), 0.0)
        self.assertAlmostEqual(self.schedule.progress(datetime(2026, 8, 14, 13, 30), self.calendar), 0.5)
        self.assertEqual(self.schedule.progress(datetime(2026, 8, 14, 20, 0), self.calendar), 1.0)

    def test_legacy_config_migration_and_deep_merge(self):
        legacy = {"lunch_time": "12:30", "off_work_time": "18:30"}
        migrated = app.migrate_legacy_config(legacy)
        self.assertEqual(migrated["schedule"]["lunch_start"], "12:30")
        self.assertEqual(migrated["schedule"]["work_segments"][0]["start"], "10:30")
        modern_classic = {"schedule": {
            "morning_start": "10:00",
            "lunch_start": "12:00",
            "afternoon_start": "13:00",
            "off_work": "18:00",
        }}
        self.assertEqual(
            app.migrate_legacy_config(modern_classic)["schedule"]["work_segments"][0]["start"],
            "10:00",
        )
        merged = app.deep_merge(app.DEFAULT_CONFIG, {"display": {"compact": True}})
        self.assertTrue(merged["display"]["compact"])
        self.assertTrue(merged["display"]["show_seconds"])

    def test_version_comparison(self):
        self.assertEqual(app.version_tuple("v1.2.3"), (1, 2, 3))
        self.assertGreater(app.version_tuple("1.10.0"), app.version_tuple("1.9.9"))

    def test_corrupt_config_is_backed_up_and_restored(self):
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            original_user_dir = app.USER_CONFIG_DIR
            original_config_path = app.CONFIG_PATH
            original_legacy_path = app.LEGACY_CONFIG_PATH
            try:
                app.USER_CONFIG_DIR = temp_path
                app.CONFIG_PATH = temp_path / "config.json"
                app.LEGACY_CONFIG_PATH = temp_path / "legacy-config.json"
                app.CONFIG_PATH.write_text("{not-json", encoding="utf-8")
                config = app.load_config()
                self.assertEqual(config["schedule"]["morning_start"], "09:00")
                self.assertTrue(list(temp_path.glob("config.broken.*.json")))
                self.assertTrue(app.CONFIG_PATH.exists())
            finally:
                app.USER_CONFIG_DIR = original_user_dir
                app.CONFIG_PATH = original_config_path
                app.LEGACY_CONFIG_PATH = original_legacy_path


if __name__ == "__main__":
    unittest.main()
