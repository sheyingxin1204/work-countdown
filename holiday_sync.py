"""Fetch and cache Chinese public-holiday calendar data.

The upstream project mirrors holiday arrangements announced by the State
Council.  The application keeps the result as a local cache and still lets
users edit/import the dates manually, so a temporary network failure never
prevents the countdown from starting.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen

HOLIDAY_SOURCE_URL = "https://raw.githubusercontent.com/NateScarlet/holiday-cn/master/{year}.json"
DEFAULT_TIMEOUT_SECONDS = 15


def _parse_year(value: Any) -> int:
    try:
        year = int(str(value))
    except (TypeError, ValueError) as error:
        raise ValueError("日历年份必须是数字") from error
    if year < 1900 or year > 2200:
        raise ValueError("日历年份必须在 1900 到 2200 之间")
    return year


def _parse_date(value: Any) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as error:
        raise ValueError(f"官方日历日期无效: {value}") from error


def parse_holiday_payload(payload: Any, expected_year: int | str | None = None) -> dict[str, Any]:
    """Normalize the upstream JSON into the app's calendar shape.

    ``isOffDay`` entries become holidays.  Entries marked ``false`` are the
    statutory make-up workdays (including weekend make-up days).  The source
    may contain the surrounding weekend days explicitly, which is harmless
    when the app's weekend-rest option is enabled.
    """

    if not isinstance(payload, dict):
        raise ValueError("官方日历响应必须是 JSON 对象")
    year = _parse_year(payload.get("year", expected_year))
    if expected_year not in (None, "") and year != _parse_year(expected_year):
        raise ValueError(f"官方日历年份不匹配: 期望 {_parse_year(expected_year)}，得到 {year}")
    days = payload.get("days")
    if not isinstance(days, list):
        raise ValueError("官方日历缺少 days 列表")

    holidays: set[str] = set()
    workdays: set[str] = set()
    for item in days:
        if not isinstance(item, dict) or "date" not in item:
            raise ValueError("官方日历包含无效日期条目")
        target = _parse_date(item["date"])
        if target.year != year:
            raise ValueError(f"官方日历包含其他年份日期: {target.isoformat()}")
        normalized = target.isoformat()
        if bool(item.get("isOffDay")):
            holidays.add(normalized)
        else:
            workdays.add(normalized)

    overlap = holidays & workdays
    if overlap:
        raise ValueError(f"官方日历存在冲突日期: {', '.join(sorted(overlap))}")
    papers = [str(item) for item in payload.get("papers", []) if str(item).strip()]
    return {
        "year": year,
        "holiday_dates": sorted(holidays),
        "workday_overrides": sorted(workdays),
        "papers": papers,
        "source": str(payload.get("$id") or ""),
    }


def fetch_holiday_calendar(
    year: int | str,
    url_template: str = HOLIDAY_SOURCE_URL,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Download and normalize a year's holiday calendar."""

    normalized_year = _parse_year(year)
    url = url_template.format(year=normalized_year)
    request = Request(url, headers={"User-Agent": "BanClock/1.3"})
    open_url = opener or urlopen
    with open_url(request, timeout=timeout) as response:
        raw = response.read()
    try:
        payload = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    except (UnicodeDecodeError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("官方日历响应不是有效 JSON") from error
    result = parse_holiday_payload(payload, normalized_year)
    result["url"] = url
    result["fetched_at"] = datetime.now(timezone.utc).isoformat()
    return result


def write_calendar_cache(path: str | Path, calendar: dict[str, Any]) -> None:
    """Atomically write a normalized calendar cache file."""

    normalized = parse_holiday_payload(
        {
            "year": calendar.get("year"),
            "days": [
                *[{"date": value, "isOffDay": True} for value in calendar.get("holiday_dates", [])],
                *[{"date": value, "isOffDay": False} for value in calendar.get("workday_overrides", [])],
            ],
        },
        calendar.get("year"),
    )
    normalized.update(
        {
            "papers": list(calendar.get("papers", [])),
            "source": str(calendar.get("source", "")),
            "url": str(calendar.get("url", "")),
            "fetched_at": str(calendar.get("fetched_at") or datetime.now(timezone.utc).isoformat()),
        }
    )
    cache_path = Path(path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as cache_file:
        json.dump(normalized, cache_file, ensure_ascii=False, indent=2)
        cache_file.write("\n")
    temporary_path.replace(cache_path)


def read_calendar_cache(path: str | Path, expected_year: int | str | None = None) -> dict[str, Any]:
    """Read and validate a previously downloaded calendar cache."""

    cache_path = Path(path)
    with cache_path.open("r", encoding="utf-8") as cache_file:
        payload = json.load(cache_file)
    result = parse_holiday_payload(
        {
            "year": payload.get("year"),
            "days": [
                *[{"date": value, "isOffDay": True} for value in payload.get("holiday_dates", [])],
                *[{"date": value, "isOffDay": False} for value in payload.get("workday_overrides", [])],
            ],
        },
        expected_year,
    )
    result.update(
        {
            "papers": list(payload.get("papers", [])),
            "source": str(payload.get("source", "")),
            "url": str(payload.get("url", "")),
            "fetched_at": str(payload.get("fetched_at", "")),
        }
    )
    return result
