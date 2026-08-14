"""Persistent work-time tracking for 班时钟.

The tracker deliberately records only the time the countdown reports as an
active work segment (morning/afternoon) or overtime.  Breaks, lunch, weekends
and time while the computer is suspended are not counted.
"""

from __future__ import annotations

import csv
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

ACTIVE_KINDS = frozenset({"morning", "afternoon"})
OVERTIME_KINDS = frozenset({"overtime"})
MAX_INTERVAL_SECONDS = 120.0


def _date_key(value: date | datetime | str) -> str:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(str(value)).isoformat()


class StatsTracker:
    """Accumulate work seconds and periodically persist them as JSON."""

    def __init__(self, path: str | Path, flush_interval_seconds: float = 60.0) -> None:
        self.path = Path(path)
        self.flush_interval_seconds = max(1.0, float(flush_interval_seconds))
        self.days: dict[str, dict[str, Any]] = {}
        self.last_at: datetime | None = None
        self.last_kind: str | None = None
        self.last_flush_at: datetime | None = None
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as stats_file:
                payload = json.load(stats_file)
            raw_days = payload.get("days", {}) if isinstance(payload, dict) else {}
            if not isinstance(raw_days, dict):
                return
            for key, value in raw_days.items():
                try:
                    normalized_key = _date_key(str(key))
                except ValueError:
                    continue
                if not isinstance(value, dict):
                    continue
                self.days[normalized_key] = {
                    "active_seconds": max(0.0, float(value.get("active_seconds", 0.0))),
                    "overtime_seconds": max(0.0, float(value.get("overtime_seconds", 0.0))),
                    "sessions": max(0, int(value.get("sessions", 0))),
                }
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            # Stats are an enhancement; a damaged history must never block the
            # countdown from starting.  The next flush will replace it.
            self.days = {}

    def _day(self, target_date: date | datetime | str) -> dict[str, Any]:
        key = _date_key(target_date)
        return self.days.setdefault(
            key,
            {"active_seconds": 0.0, "overtime_seconds": 0.0, "sessions": 0},
        )

    def tick(self, now: datetime, kind: str | None) -> float:
        """Record the interval since the previous tick and return its size."""

        if self.last_at is None:
            self.last_at = now
            self.last_kind = kind
            if kind in ACTIVE_KINDS:
                self._day(now)["sessions"] += 1
            return 0.0
        interval = (now - self.last_at).total_seconds()
        previous_at = self.last_at
        previous_kind = self.last_kind
        self.last_at = now
        self.last_kind = kind
        if interval <= 0 or interval > MAX_INTERVAL_SECONDS:
            return 0.0

        if previous_kind in ACTIVE_KINDS:
            self._day(previous_at)["active_seconds"] += interval
        elif previous_kind in OVERTIME_KINDS:
            self._day(previous_at)["overtime_seconds"] += interval

        if kind in ACTIVE_KINDS and previous_kind not in ACTIVE_KINDS:
            self._day(now)["sessions"] += 1
        return interval

    def flush_if_due(self, now: datetime | None = None) -> bool:
        current = now or datetime.now()
        if self.last_flush_at is not None:
            elapsed = (current - self.last_flush_at).total_seconds()
            if elapsed < self.flush_interval_seconds:
                return False
        self.flush()
        self.last_flush_at = current
        return True

    def flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "days": self.days}
        temporary_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with temporary_path.open("w", encoding="utf-8") as stats_file:
            json.dump(payload, stats_file, ensure_ascii=False, indent=2)
            stats_file.write("\n")
        os.replace(temporary_path, self.path)

    def summary(self, start: date | str, end: date | str | None = None) -> dict[str, float | int]:
        """Return totals for the inclusive date range ``start..end``."""

        start_date = date.fromisoformat(_date_key(start))
        end_date = date.fromisoformat(_date_key(end or start_date))
        if end_date < start_date:
            raise ValueError("统计结束日期不能早于开始日期")
        active = overtime = 0.0
        sessions = 0
        days = 0
        current = start_date
        while current <= end_date:
            item = self.days.get(current.isoformat())
            if item:
                days += 1
                active += float(item.get("active_seconds", 0.0))
                overtime += float(item.get("overtime_seconds", 0.0))
                sessions += int(item.get("sessions", 0))
            current += timedelta(days=1)
        return {
            "active_seconds": active,
            "overtime_seconds": overtime,
            "total_seconds": active + overtime,
            "sessions": sessions,
            "days": days,
        }

    def export_csv(self, path: str | Path) -> None:
        """Export all recorded days in a spreadsheet-friendly format."""

        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(["日期", "工作时长（小时）", "加班时长（小时）", "总时长（小时）", "工作会话数"])
            for key in sorted(self.days):
                item = self.days[key]
                active = float(item.get("active_seconds", 0.0)) / 3600
                overtime = float(item.get("overtime_seconds", 0.0)) / 3600
                writer.writerow(
                    [
                        key,
                        f"{active:.2f}",
                        f"{overtime:.2f}",
                        f"{active + overtime:.2f}",
                        int(item.get("sessions", 0)),
                    ]
                )
