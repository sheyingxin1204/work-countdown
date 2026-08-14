import csv
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from work_stats import StatsTracker


class WorkStatsTests(unittest.TestCase):
    def test_tick_accumulates_active_and_overtime_seconds(self):
        tracker = StatsTracker("stats.json")
        start = datetime(2026, 8, 14, 9, 0)
        tracker.tick(start, "morning")
        tracker.tick(datetime(2026, 8, 14, 9, 1), "morning")
        tracker.tick(datetime(2026, 8, 14, 12, 0), "lunch")
        overtime_start = datetime(2026, 8, 14, 18, 30)
        tracker.tick(overtime_start, "overtime")
        for minute in range(1, 30):
            tracker.tick(overtime_start + timedelta(minutes=minute), "overtime")
        tracker.tick(datetime(2026, 8, 14, 19, 0), "off_work")
        summary = tracker.summary("2026-08-14")
        self.assertEqual(summary["active_seconds"], 60.0)
        self.assertEqual(summary["overtime_seconds"], 1800.0)
        self.assertEqual(summary["sessions"], 1)

    def test_sleep_gap_is_not_counted(self):
        tracker = StatsTracker("stats.json")
        tracker.tick(datetime(2026, 8, 14, 9, 0), "morning")
        tracker.tick(datetime(2026, 8, 14, 12, 0), "morning")
        self.assertEqual(tracker.summary("2026-08-14")["total_seconds"], 0.0)

    def test_flush_load_and_export(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "stats.json"
            tracker = StatsTracker(path)
            tracker.tick(datetime(2026, 8, 14, 9, 0), "morning")
            tracker.tick(datetime(2026, 8, 14, 9, 1), "lunch")
            tracker.flush()

            loaded = StatsTracker(path)
            self.assertEqual(loaded.summary("2026-08-14")["active_seconds"], 60.0)
            csv_path = Path(temp_dir) / "stats.csv"
            loaded.export_csv(csv_path)
            with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
                rows = list(csv.reader(csv_file))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[1][0], "2026-08-14")
            self.assertEqual(rows[1][1], "0.02")


if __name__ == "__main__":
    unittest.main()
