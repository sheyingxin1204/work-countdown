"""Pure calendar and schedule logic for 班时钟.

This module intentionally has no Tkinter, tray, filesystem, or network
dependencies so it can be tested on its own and reused by another front end.
"""

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any


def parse_clock(value: str) -> time:
    try:
        hour, minute = value.split(":", 1)
        return time(hour=int(hour), minute=int(minute))
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError(f"时间格式无效: {value}") from error


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError(f"日期格式无效: {value}") from error


def parse_date_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = str(value).replace(",", "\n").splitlines()
    parsed = sorted({parse_date(str(item).strip()) for item in values if str(item).strip()})
    return [item.isoformat() for item in parsed]


def format_date_list(values: Any) -> str:
    return "\n".join(parse_date_list(values))


def normalize_calendar_dates(holiday_dates: Any, workday_overrides: Any) -> tuple[list[str], list[str]]:
    holidays = parse_date_list(holiday_dates)
    workdays = parse_date_list(workday_overrides)
    overlap = sorted(set(holidays) & set(workdays))
    if overlap:
        raise ValueError(f"同一日期不能同时设置为节假日和调休工作日: {', '.join(overlap)}")
    return holidays, workdays


def read_calendar_file(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as calendar_file:
        payload = json.load(calendar_file)
    if isinstance(payload, dict) and isinstance(payload.get("calendar"), dict):
        payload = payload["calendar"]
    if not isinstance(payload, dict):
        raise ValueError("日历文件必须是 JSON 对象")
    holidays, workdays = normalize_calendar_dates(
        payload.get("holiday_dates", []), payload.get("workday_overrides", [])
    )
    year = payload.get("year")
    if year not in (None, ""):
        try:
            year = int(str(year))
        except (TypeError, ValueError) as error:
            raise ValueError("日历年份必须是数字") from error
        if year < 1900 or year > 2200:
            raise ValueError("日历年份必须在 1900 到 2200 之间")
    return {"year": year, "holiday_dates": holidays, "workday_overrides": workdays}


def write_calendar_file(
    path: str | Path,
    holiday_dates: Any,
    workday_overrides: Any,
    year: int | str | None = None,
) -> None:
    holidays, workdays = normalize_calendar_dates(holiday_dates, workday_overrides)
    if year in (None, ""):
        all_dates = [parse_date(item) for item in holidays + workdays]
        years = {item.year for item in all_dates}
        year = next(iter(years)) if len(years) == 1 else None
    payload = {
        "version": 1,
        "year": year,
        "holiday_dates": holidays,
        "workday_overrides": workdays,
    }
    calendar_path = Path(path)
    calendar_path.parent.mkdir(parents=True, exist_ok=True)
    with calendar_path.open("w", encoding="utf-8") as calendar_file:
        json.dump(payload, calendar_file, ensure_ascii=False, indent=2)
        calendar_file.write("\n")


def parse_work_segments(value: Any) -> list[dict[str, str]]:
    if isinstance(value, (list, tuple)):
        items = value
    else:
        items = [line.strip() for line in str(value).splitlines() if line.strip()]
    segments: list[dict[str, str]] = []
    for item in items:
        if isinstance(item, dict):
            start_value = item.get("start")
            end_value = item.get("end")
        else:
            text = str(item).replace("至", "-").replace("~", "-")
            if "-" not in text:
                raise ValueError(f"工作时段格式无效: {item}")
            start_value, end_value = (part.strip() for part in text.split("-", 1))
        start = parse_clock(str(start_value).strip())
        end = parse_clock(str(end_value).strip())
        if start >= end:
            raise ValueError(f"工作时段必须是开始时间早于结束时间: {item}")
        segments.append({"start": start.strftime("%H:%M"), "end": end.strftime("%H:%M")})
    if not segments:
        raise ValueError("至少需要一个工作时段")
    if len(segments) > 4:
        raise ValueError("最多支持 4 个工作时段")
    for previous, current in zip(segments, segments[1:]):
        if parse_clock(previous["end"]) > parse_clock(current["start"]):
            raise ValueError("工作时段不能重叠，且必须按时间顺序填写")
    return segments


def format_work_segments(segments: Any) -> str:
    return "\n".join(f"{item['start']} - {item['end']}" for item in parse_work_segments(segments))


class WorkCalendar:
    def __init__(self, config: dict[str, Any]) -> None:
        calendar = config["calendar"]
        self.weekend_rest = bool(calendar["weekend_rest"])
        holiday_dates, workday_overrides = normalize_calendar_dates(
            calendar["holiday_dates"], calendar["workday_overrides"]
        )
        self.holiday_dates = {parse_date(value) for value in holiday_dates}
        self.workday_overrides = {parse_date(value) for value in workday_overrides}

    def is_workday(self, target_date: date) -> bool:
        if target_date in self.workday_overrides:
            return True
        if target_date in self.holiday_dates:
            return False
        if self.weekend_rest and target_date.weekday() >= 5:
            return False
        return True

    def next_workday(self, start_date: date) -> date:
        target_date = start_date
        for _ in range(370):
            if self.is_workday(target_date):
                return target_date
            target_date += timedelta(days=1)
        raise RuntimeError("找不到下一个工作日，请检查节假日配置。")


class WorkSchedule:
    def __init__(self, config: dict[str, Any]) -> None:
        schedule = config["schedule"]
        raw_segments = schedule.get("work_segments")
        if raw_segments:
            segment_values = parse_work_segments(raw_segments)
        else:
            segment_values = parse_work_segments([
                {"start": schedule["morning_start"], "end": schedule["lunch_start"]},
                {"start": schedule["afternoon_start"], "end": schedule["off_work"]},
            ])
        self.work_segments = [
            (parse_clock(item["start"]), parse_clock(item["end"]))
            for item in segment_values
        ]
        self.morning_start = self.work_segments[0][0]
        self.lunch_start = self.work_segments[0][1]
        self.afternoon_start = self.work_segments[1][0] if len(self.work_segments) > 1 else self.work_segments[0][1]
        self.off_work = self.work_segments[-1][1]
        overtime_value = schedule.get("overtime_end")
        self.overtime_end = parse_clock(overtime_value) if overtime_value not in (None, "") else None
        if self.overtime_end is not None and self.overtime_end <= self.off_work:
            raise ValueError("加班结束时间必须晚于正常下班时间")

    def at(self, target_date: date, target_time: time) -> datetime:
        return datetime.combine(target_date, target_time)

    def morning_range_text(self) -> str:
        start, end = self.work_segments[0]
        return f"{start.strftime('%H:%M')} - {end.strftime('%H:%M')}"

    def afternoon_range_text(self) -> str:
        if len(self.work_segments) < 2:
            return "-"
        start, end = self.work_segments[1]
        return f"{start.strftime('%H:%M')} - {end.strftime('%H:%M')}"

    def notification_events(self, target_date: date, calendar: WorkCalendar) -> list[tuple[str, datetime, str, str]]:
        if not calendar.is_workday(target_date):
            return []
        events: list[tuple[str, datetime, str, str]] = []
        if len(self.work_segments) > 1:
            events.append(("lunch", self.at(target_date, self.work_segments[0][1]), "午休", "午休开始了，休息一下吧。"))
        events.append(("off_work", self.at(target_date, self.off_work), "下班", "下班时间到了，今天辛苦了。"))
        return events

    def progress(self, now: datetime, calendar: WorkCalendar, mode: str = "wall_clock") -> float:
        if not calendar.is_workday(now.date()):
            return 0.0
        if mode == "active_work":
            total_seconds = sum(
                (
                    self.at(now.date(), end) - self.at(now.date(), start)
                ).total_seconds()
                for start, end in self.work_segments
            )
            if total_seconds <= 0:
                return 0.0
            elapsed_seconds = 0.0
            for start, end in self.work_segments:
                segment_start = self.at(now.date(), start)
                segment_end = self.at(now.date(), end)
                elapsed_seconds += max(
                    0.0,
                    min(
                        (now - segment_start).total_seconds(),
                        (segment_end - segment_start).total_seconds(),
                    ),
                )
            return max(0.0, min(1.0, elapsed_seconds / total_seconds))

        start = self.at(now.date(), self.morning_start)
        end = self.at(now.date(), self.off_work)
        total_seconds = (end - start).total_seconds()
        if total_seconds <= 0:
            return 0.0
        elapsed_seconds = (now - start).total_seconds()
        return max(0.0, min(1.0, elapsed_seconds / total_seconds))

    def state(self, now: datetime, calendar: WorkCalendar) -> dict[str, Any]:
        today = now.date()
        if not calendar.is_workday(today):
            next_day = calendar.next_workday(today + timedelta(days=1))
            return {
                "kind": "rest",
                "status": "休息日",
                "countdown_name": "下个上班",
                "countdown_at": self.at(next_day, self.morning_start),
            }

        segments = [(self.at(today, start), self.at(today, end)) for start, end in self.work_segments]
        if now < segments[0][0]:
            return {
                "kind": "before_work",
                "status": "未上班",
                "countdown_name": "距离上班",
                "countdown_at": segments[0][0],
            }
        for index, (start, end) in enumerate(segments):
            if now < start:
                is_lunch = index == 1
                return {
                    "kind": "lunch" if is_lunch else "break",
                    "status": "午休中" if is_lunch else "休息中",
                    "countdown_name": "下午上班" if is_lunch else "下一段工作",
                    "countdown_at": start,
                }
            if now < end:
                is_first = index == 0
                countdown_at = segments[index + 1][0] if index + 1 < len(segments) else end
                return {
                    "kind": "morning" if is_first else "afternoon",
                    "status": "上午上班" if is_first else "下午上班",
                    "countdown_name": "距离午休" if index == 0 and len(segments) > 1 else "距离下班",
                    "countdown_at": countdown_at,
                }
        if self.overtime_end is not None:
            overtime_end = self.at(today, self.overtime_end)
            if now < overtime_end:
                return {
                    "kind": "overtime",
                    "status": "加班中",
                    "countdown_name": "距离加班结束",
                    "countdown_at": overtime_end,
                }
        next_day = calendar.next_workday(today + timedelta(days=1))
        return {
            "kind": "off_work",
            "status": "已下班",
            "countdown_name": "下个上班",
            "countdown_at": self.at(next_day, self.morning_start),
        }
