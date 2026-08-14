import ctypes
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
import urllib.error
import urllib.request
import webbrowser
from copy import deepcopy
from datetime import date, datetime, time, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from holiday_sync import (
    HOLIDAY_SOURCE_URL,
    fetch_holiday_calendar,
    read_calendar_cache,
    write_calendar_cache,
)
from work_core import WorkCalendar, WorkSchedule

try:
    import pystray
    from PIL import Image
except ImportError:  # The widget can still run without a tray dependency.
    pystray = None
    Image = None

try:
    import winsound
except ImportError:  # Available on Windows; keep source-mode tests portable.
    winsound = None


if getattr(sys, "frozen", False):
    # Keep user configuration beside the packaged EXE instead of inside the
    # temporary extraction directory used by one-file PyInstaller builds.
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent
APP_NAME = "班时钟"
APP_VERSION = "1.2.0"
GITHUB_REPOSITORY = "sheyingxin1204/work-countdown"
LEGACY_CONFIG_PATH = APP_DIR / "config.json"
if os.name == "nt":
    _appdata_root = Path(os.environ.get("APPDATA") or APP_DIR)
else:
    _appdata_root = APP_DIR
USER_CONFIG_DIR = _appdata_root / "BanClock"
CONFIG_PATH = USER_CONFIG_DIR / "config.json"
LOG_PATH = USER_CONFIG_DIR / "ban_clock.log"
ICON_RELATIVE_PATH = Path("assets") / "ban-clock-icon.png"
SINGLE_INSTANCE_MUTEX = None
LOGGER = logging.getLogger("ban_clock")


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _Rect(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("rcMonitor", _Rect), ("rcWork", _Rect), ("dwFlags", ctypes.c_uint)]


def acquire_single_instance():
    """Keep only one running instance on Windows."""
    global SINGLE_INSTANCE_MUTEX
    if os.name != "nt":
        return True

    try:
        kernel32 = ctypes.windll.kernel32
        mutex = kernel32.CreateMutexW(None, False, "Local\\BanClock.SingleInstance")
        if not mutex:
            return True
        if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(mutex)
            return False
        SINGLE_INSTANCE_MUTEX = mutex
    except (AttributeError, OSError):
        return True
    return True


def get_monitor_work_area(root, x=None, y=None):
    """Return the usable work area for the monitor containing a point."""
    if x is None:
        x = root.winfo_pointerx()
    if y is None:
        y = root.winfo_pointery()

    if os.name == "nt":
        try:
            user32 = ctypes.windll.user32
            user32.MonitorFromPoint.argtypes = [_Point, ctypes.c_uint]
            user32.MonitorFromPoint.restype = ctypes.c_void_p
            user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MonitorInfo)]
            user32.GetMonitorInfoW.restype = ctypes.c_int
            monitor = user32.MonitorFromPoint(_Point(int(x), int(y)), 2)
            info = _MonitorInfo()
            info.cbSize = ctypes.sizeof(_MonitorInfo)
            if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                work = info.rcWork
                return work.left, work.top, work.right, work.bottom
        except (AttributeError, OSError, TypeError):
            pass

    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def resource_path(relative_path):
    """Resolve an asset both from source checkout and PyInstaller bundles."""
    bundle_dir = Path(getattr(sys, "_MEIPASS", APP_DIR))
    return bundle_dir / relative_path

DEFAULT_CONFIG = {
    "schedule": {
        "morning_start": "09:00",
        "lunch_start": "12:00",
        "afternoon_start": "13:30",
        "off_work": "18:00",
        "work_segments": [
            {"start": "09:00", "end": "12:00"},
            {"start": "13:30", "end": "18:00"},
        ],
        "overtime_end": None,
    },
    "calendar": {
        "weekend_rest": True,
        "holiday_dates": [],
        "workday_overrides": [],
    },
    "window": {
        "x": None,
        "y": None,
        "margin": 18,
        "alpha": 0.88,
        "always_on_top": True,
    },
    "notifications": {
        "enabled": True,
        "lunch": True,
        "off_work": True,
        "sound": False,
        "lead_minutes": 0,
        "quiet_hours": {
            "enabled": False,
            "start": "22:00",
            "end": "08:00",
        },
    },
    "display": {
        "compact": False,
        "show_seconds": True,
        "show_schedule": True,
    },
    "style": {
        "theme": "dark",
        "background": "#101418",
        "foreground": "#F3F7FA",
        "muted": "#9BA7B0",
        "accent": "#39A0ED",
    },
}

THEME_PRESETS = {
    "dark": {
        "theme": "dark",
        "background": "#101418",
        "foreground": "#F3F7FA",
        "muted": "#9BA7B0",
        "accent": "#39A0ED",
    },
    "light": {
        "theme": "light",
        "background": "#F4F7FA",
        "foreground": "#1F2933",
        "muted": "#65727E",
        "accent": "#1479D1",
    },
    "ocean": {
        "theme": "ocean",
        "background": "#0B2333",
        "foreground": "#E8F7FF",
        "muted": "#8DB8CC",
        "accent": "#42C6E8",
    },
}
THEME_LABELS = {"dark": "深色", "light": "浅色", "ocean": "海洋蓝"}


def deep_merge(base, override):
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def setup_logging():
    if logging.getLogger().handlers:
        return
    try:
        USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            LOG_PATH,
            maxBytes=512 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        logging.basicConfig(
            level=logging.INFO,
            handlers=[handler],
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
    except OSError:
        # Logging should never prevent the countdown widget from starting.
        logging.basicConfig(level=logging.WARNING)


def load_config():
    if not CONFIG_PATH.exists() and LEGACY_CONFIG_PATH.exists() and LEGACY_CONFIG_PATH != CONFIG_PATH:
        try:
            USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(LEGACY_CONFIG_PATH, CONFIG_PATH)
        except OSError:
            # The widget can still start with defaults if the old config
            # cannot be copied (for example, on a read-only folder).
            pass

    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        return deepcopy(DEFAULT_CONFIG)

    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
            config = json.load(config_file)
        if not isinstance(config, dict):
            raise ValueError("配置文件必须是 JSON 对象")
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as error:
        broken_path = CONFIG_PATH.with_name(
            f"config.broken.{datetime.now():%Y%m%d-%H%M%S}.json"
        )
        try:
            if CONFIG_PATH.exists():
                shutil.copy2(CONFIG_PATH, broken_path)
        except OSError:
            LOGGER.exception("无法备份损坏的配置文件")
        LOGGER.warning("配置文件读取失败，将使用默认配置: %s", error)
        try:
            save_config(DEFAULT_CONFIG)
        except OSError:
            LOGGER.exception("无法写回默认配置")
        return deepcopy(DEFAULT_CONFIG)

    return deep_merge(DEFAULT_CONFIG, migrate_legacy_config(config))


def migrate_legacy_config(config):
    if "schedule" in config:
        schedule = config.get("schedule", {})
        if isinstance(schedule, dict) and "work_segments" not in schedule:
            schedule = deepcopy(schedule)
            if all(key in schedule for key in ("morning_start", "lunch_start", "afternoon_start", "off_work")):
                schedule["work_segments"] = [
                    {"start": schedule["morning_start"], "end": schedule["lunch_start"]},
                    {"start": schedule["afternoon_start"], "end": schedule["off_work"]},
                ]
            migrated = deepcopy(config)
            migrated["schedule"] = schedule
            return migrated
        return config

    migrated = deepcopy(config)
    migrated["schedule"] = {
        "morning_start": "10:30",
        "lunch_start": config.get("lunch_time", "13:30"),
        "afternoon_start": "15:30",
        "off_work": config.get("off_work_time", "19:30"),
    }
    migrated["schedule"]["work_segments"] = [
        {"start": migrated["schedule"]["morning_start"], "end": migrated["schedule"]["lunch_start"]},
        {"start": migrated["schedule"]["afternoon_start"], "end": migrated["schedule"]["off_work"]},
    ]
    migrated.pop("lunch_time", None)
    migrated.pop("off_work_time", None)
    return migrated


def save_config(config):
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    temporary_path = CONFIG_PATH.with_suffix(".tmp")
    with temporary_path.open("w", encoding="utf-8") as config_file:
        json.dump(config, config_file, ensure_ascii=False, indent=2)
        config_file.write("\n")
    os.replace(temporary_path, CONFIG_PATH)


def parse_clock(value):
    try:
        hour, minute = value.split(":", 1)
        return time(hour=int(hour), minute=int(minute))
    except ValueError as error:
        raise ValueError(f"时间格式无效: {value}") from error


def parse_date(value):
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"日期格式无效: {value}") from error


def parse_date_list(value):
    """Parse comma- or line-separated ISO dates into a normalized list."""
    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = str(value).replace(",", "\n").splitlines()
    parsed = sorted({parse_date(str(item).strip()) for item in values if str(item).strip()})
    return [item.isoformat() for item in parsed]


def format_date_list(values):
    return "\n".join(parse_date_list(values))


def normalize_calendar_dates(holiday_dates, workday_overrides):
    """Normalize calendar dates and reject contradictory overrides."""
    holidays = parse_date_list(holiday_dates)
    workdays = parse_date_list(workday_overrides)
    overlap = sorted(set(holidays) & set(workdays))
    if overlap:
        raise ValueError(f"同一日期不能同时设置为节假日和调休工作日: {', '.join(overlap)}")
    return holidays, workdays


def read_calendar_file(path):
    """Read an annual calendar JSON file used by the settings center."""
    calendar_path = Path(path)
    with calendar_path.open("r", encoding="utf-8") as calendar_file:
        payload = json.load(calendar_file)
    if isinstance(payload, dict) and isinstance(payload.get("calendar"), dict):
        payload = payload["calendar"]
    if not isinstance(payload, dict):
        raise ValueError("日历文件必须是 JSON 对象")

    holidays, workdays = normalize_calendar_dates(
        payload.get("holiday_dates", []),
        payload.get("workday_overrides", []),
    )
    year = payload.get("year")
    if year not in (None, ""):
        try:
            year = int(year)
        except (TypeError, ValueError) as error:
            raise ValueError("日历年份必须是数字") from error
        if year < 1900 or year > 2200:
            raise ValueError("日历年份必须在 1900 到 2200 之间")
    return {
        "year": year,
        "holiday_dates": holidays,
        "workday_overrides": workdays,
    }


def write_calendar_file(path, holiday_dates, workday_overrides, year=None):
    """Export normalized calendar data as a portable JSON file."""
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


def parse_work_segments(value):
    """Parse lines such as ``09:00-12:00`` into ordered time segments."""
    if isinstance(value, (list, tuple)):
        items = value
    else:
        items = [line.strip() for line in str(value).splitlines() if line.strip()]
    segments = []
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
        segments.append({"start": format_clock(start), "end": format_clock(end)})

    if not segments:
        raise ValueError("至少需要一个工作时段")
    if len(segments) > 4:
        raise ValueError("最多支持 4 个工作时段")
    for previous, current in zip(segments, segments[1:]):
        if parse_clock(previous["end"]) > parse_clock(current["start"]):
            raise ValueError("工作时段不能重叠，且必须按时间顺序填写")
    return segments


def format_work_segments(segments):
    return "\n".join(f"{item['start']} - {item['end']}" for item in parse_work_segments(segments))


def format_remaining(delta):
    seconds = max(0, int(delta.total_seconds()))
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def format_clock(value):
    return value.strftime("%H:%M")


def version_tuple(value):
    parts = re.findall(r"\d+", str(value))
    return tuple(int(part) for part in parts) or (0,)


def latest_release_url():
    return f"https://github.com/{GITHUB_REPOSITORY}/releases/latest"


def holiday_cache_path(year):
    return USER_CONFIG_DIR / "holiday-cache" / f"{int(year)}.json"


class CountdownWidget:
    def __init__(self):
        self.config = load_config()
        self.calendar = WorkCalendar(self.config)
        self.schedule = WorkSchedule(self.config)
        self.drag_offset_x = 0
        self.drag_offset_y = 0
        self.tray_icon = None
        self.tray_thread = None
        self.is_closing = False
        self.settings_dialog = None
        self.update_thread = None
        self.last_state_kind = None
        self.last_state_date = None
        self.sent_alerts = set()

        self.root = tk.Tk()
        try:
            tk_scaling = float(self.root.tk.call("tk", "scaling"))
        except (tk.TclError, TypeError, ValueError):
            tk_scaling = 1.0
        # Tk fonts follow the Windows DPI setting automatically. Use the same
        # scale for pixel-sized controls so the progress indicator and window
        # spacing remain balanced on high-DPI displays.
        self.ui_scale = max(1.0, min(2.0, tk_scaling / 1.3333))
        self.root.title(APP_NAME)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", bool(self.config["window"]["always_on_top"]))
        self.root.attributes("-alpha", float(self.config["window"]["alpha"]))
        self.root.configure(bg=self.config["style"]["background"])
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        self.root.bind_all("<Control-Shift-b>", lambda _event: self.toggle_window())
        self.root.bind_all("<Control-Shift-s>", lambda _event: self.open_schedule_settings())

        self.frame = tk.Frame(
            self.root,
            bg=self.config["style"]["background"],
            padx=round(18 * self.ui_scale),
            pady=round(14 * self.ui_scale),
            highlightthickness=1,
            highlightbackground="#26313A",
        )
        self.frame.pack()

        self.title_label = tk.Label(
            self.frame,
            text="今日状态",
            bg=self.config["style"]["background"],
            fg=self.config["style"]["muted"],
            font=("Microsoft YaHei UI", 10),
        )
        self.title_label.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        self.progress_width = round(240 * self.ui_scale)
        self.progress_height = max(6, round(8 * self.ui_scale))
        self.progress_canvas = tk.Canvas(
            self.frame,
            width=self.progress_width,
            height=self.progress_height,
            bg="#26313A",
            highlightthickness=0,
            bd=0,
        )
        self.progress_canvas.grid(row=1, column=0, columnspan=2, sticky="we", pady=(0, 8))
        self.progress_fill = self.progress_canvas.create_rectangle(
            0,
            0,
            0,
            self.progress_height,
            fill=self.config["style"]["accent"],
            outline="",
        )

        self.status_label = self.create_name_label("当前")
        self.status_value = self.create_text_value_label()
        self.countdown_label = self.create_name_label("距离午休")
        self.countdown_value = self.create_value_label()
        self.morning_label = self.create_name_label("上午上班")
        self.morning_value = self.create_range_label()
        self.afternoon_label = self.create_name_label("下午上班")
        self.afternoon_value = self.create_range_label()
        self.clock_label = tk.Label(
            self.frame,
            bg=self.config["style"]["background"],
            fg=self.config["style"]["muted"],
            font=("Microsoft YaHei UI", 9),
        )

        self.status_label.grid(row=2, column=0, sticky="w", pady=3)
        self.status_value.grid(row=2, column=1, sticky="e", padx=(18, 0), pady=3)
        self.countdown_label.grid(row=3, column=0, sticky="w", pady=3)
        self.countdown_value.grid(row=3, column=1, sticky="e", padx=(18, 0), pady=3)
        self.morning_label.grid(row=4, column=0, sticky="w", pady=(12, 3))
        self.morning_value.grid(row=4, column=1, sticky="e", padx=(18, 0), pady=(12, 3))
        self.afternoon_label.grid(row=5, column=0, sticky="w", pady=3)
        self.afternoon_value.grid(row=5, column=1, sticky="e", padx=(18, 0), pady=3)
        self.clock_label.grid(row=6, column=0, columnspan=2, sticky="e", pady=(8, 0))

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="打开设置中心", command=self.open_schedule_settings)
        self.menu.add_command(label="重新加载配置", command=self.reload_config)
        self.menu.add_command(label="检查更新", command=self.check_for_updates)
        self.menu.add_command(label="打开配置目录", command=self.open_config_folder)
        self.menu.add_command(label="恢复默认位置", command=self.reset_position)
        self.menu.add_command(label=f"关于{APP_NAME}", command=self.show_about)
        self.menu.add_separator()
        self.menu.add_command(label="隐藏到系统托盘", command=self.hide_window)
        self.menu.add_command(label="退出班时钟", command=self.quit)

        for widget in (
            self.root,
            self.frame,
            self.title_label,
            self.progress_canvas,
            self.status_label,
            self.status_value,
            self.countdown_label,
            self.countdown_value,
            self.morning_label,
            self.morning_value,
            self.afternoon_label,
            self.afternoon_value,
            self.clock_label,
        ):
            widget.bind("<ButtonPress-1>", self.start_drag)
            widget.bind("<B1-Motion>", self.drag)
            widget.bind("<ButtonRelease-1>", self.save_position)
            widget.bind("<Button-3>", self.show_menu)

        self.refresh_static_ranges()
        self.apply_display_preferences()
        self.place_window()
        self.start_tray()
        self.update()

    def create_name_label(self, text):
        return tk.Label(
            self.frame,
            text=text,
            bg=self.config["style"]["background"],
            fg=self.config["style"]["foreground"],
            font=("Microsoft YaHei UI", 11),
        )

    def create_value_label(self):
        return tk.Label(
            self.frame,
            bg=self.config["style"]["background"],
            fg=self.config["style"]["accent"],
            font=("Consolas", 18, "bold"),
            width=9,
            anchor="e",
        )

    def create_text_value_label(self):
        return tk.Label(
            self.frame,
            bg=self.config["style"]["background"],
            fg=self.config["style"]["accent"],
            font=("Microsoft YaHei UI", 12, "bold"),
            anchor="e",
        )

    def create_range_label(self):
        return tk.Label(
            self.frame,
            bg=self.config["style"]["background"],
            fg=self.config["style"]["foreground"],
            font=("Consolas", 14, "bold"),
            anchor="e",
        )

    def refresh_static_ranges(self):
        self.morning_value.configure(text=self.schedule.morning_range_text())
        self.afternoon_value.configure(text=self.schedule.afternoon_range_text())

    def apply_style(self):
        style = self.config["style"]
        background = style["background"]
        foreground = style["foreground"]
        muted = style["muted"]
        accent = style["accent"]
        self.root.configure(bg=background)
        self.frame.configure(bg=background, highlightbackground="#26313A")
        for widget in (self.title_label, self.clock_label):
            widget.configure(bg=background, fg=muted)
        for widget in (self.status_label, self.countdown_label, self.morning_label, self.afternoon_label):
            widget.configure(bg=background, fg=foreground)
        self.countdown_value.configure(bg=background, fg=accent)
        for widget in (self.morning_value, self.afternoon_value):
            widget.configure(bg=background, fg=foreground)
        self.status_value.configure(bg=background, fg=accent)
        self.progress_canvas.configure(bg="#26313A")
        self.progress_canvas.itemconfigure(self.progress_fill, fill=accent)

    def apply_display_preferences(self):
        display = self.config.get("display", {})
        show_schedule = bool(display.get("show_schedule", True)) and not bool(display.get("compact", False))
        schedule_widgets = (
            self.morning_label,
            self.morning_value,
            self.afternoon_label,
            self.afternoon_value,
        )
        for widget in schedule_widgets:
            if show_schedule:
                widget.grid()
            else:
                widget.grid_remove()

    def update_progress(self, progress):
        width = max(0, min(self.progress_width, round(self.progress_width * progress)))
        self.progress_canvas.coords(self.progress_fill, 0, 0, width, self.progress_height)

    def place_window(self):
        self.root.update_idletasks()
        window = self.config["window"]
        width = self.root.winfo_reqwidth()
        height = self.root.winfo_reqheight()
        margin = max(0, int(window.get("margin", 18)))

        try:
            x = int(window.get("x"))
            y = int(window.get("y"))
        except (TypeError, ValueError):
            x = None
            y = None

        left, top, right, bottom = get_monitor_work_area(self.root, x, y)
        min_x = left
        min_y = top
        max_x = max(min_x, right - width)
        max_y = max(min_y, bottom - height)

        if x is None or y is None:
            x = max(min_x, right - width - margin)
            y = max(min_y, bottom - height - margin)

        x = min(max(min_x, x), max_x)
        y = min(max(min_y, y), max_y)
        self.root.geometry(f"+{x}+{y}")

    def start_drag(self, event):
        self.drag_offset_x = event.x
        self.drag_offset_y = event.y

    def drag(self, event):
        x = self.root.winfo_pointerx() - self.drag_offset_x
        y = self.root.winfo_pointery() - self.drag_offset_y
        self.root.geometry(f"+{x}+{y}")

    def save_position(self, _event=None):
        self.config["window"]["x"] = self.root.winfo_x()
        self.config["window"]["y"] = self.root.winfo_y()
        save_config(self.config)

    def reset_position(self):
        self.config["window"]["x"] = None
        self.config["window"]["y"] = None
        save_config(self.config)
        self.place_window()

    def show_menu(self, event):
        self.menu.tk_popup(event.x_root, event.y_root)

    def start_tray(self):
        """Start the Windows notification-area icon on a background thread."""
        if pystray is None or Image is None:
            return

        icon_path = resource_path(ICON_RELATIVE_PATH)
        if not icon_path.exists():
            return

        try:
            image = Image.open(icon_path).convert("RGBA")
            resampling = getattr(Image, "Resampling", Image)
            image.thumbnail((64, 64), resampling.LANCZOS)
            menu = pystray.Menu(
                pystray.MenuItem(
                    "显示/隐藏窗口",
                    lambda _icon, _item: self.call_on_ui(self.toggle_window),
                    default=True,
                ),
                pystray.MenuItem(
                    "打开设置中心",
                    lambda _icon, _item: self.call_on_ui(self.open_schedule_from_tray),
                ),
                pystray.MenuItem(
                    "重新加载配置",
                    lambda _icon, _item: self.call_on_ui(self.reload_config),
                ),
                pystray.MenuItem(
                    "检查更新",
                    lambda _icon, _item: self.call_on_ui(self.check_for_updates),
                ),
                pystray.MenuItem(
                    "打开配置目录",
                    lambda _icon, _item: self.call_on_ui(self.open_config_folder),
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    "退出班时钟",
                    lambda _icon, _item: self.call_on_ui(self.quit),
                ),
            )
            self.tray_icon = pystray.Icon(
                "ban_clock",
                image,
                APP_NAME,
                menu=menu,
            )
            self.tray_thread = threading.Thread(
                target=self.tray_icon.run,
                name="班时钟系统托盘",
                daemon=True,
            )
            self.tray_thread.start()
        except Exception:
            # A missing or unsupported tray backend should not prevent the
            # countdown widget itself from opening.
            LOGGER.exception("系统托盘初始化失败")
            self.tray_icon = None
            self.tray_thread = None

    def call_on_ui(self, callback):
        """Schedule a Tk callback from a pystray worker thread."""
        if self.is_closing:
            return
        try:
            self.root.after(0, callback)
        except tk.TclError:
            pass

    def toggle_window(self):
        if self.root.state() == "withdrawn":
            self.show_window()
        else:
            self.hide_window()

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide_window(self):
        if self.tray_icon is None:
            return
        self.save_position()
        self.root.withdraw()

    def open_schedule_from_tray(self):
        self.show_window()
        self.open_schedule_settings()

    def open_schedule_settings(self):
        if self.settings_dialog is not None and self.settings_dialog.winfo_exists():
            self.settings_dialog.deiconify()
            self.settings_dialog.lift()
            return

        background = self.config["style"]["background"]
        foreground = self.config["style"]["foreground"]
        muted = self.config["style"]["muted"]
        accent = self.config["style"]["accent"]

        dialog = tk.Toplevel(self.root)
        self.settings_dialog = dialog
        dialog.title(f"{APP_NAME} v{APP_VERSION} · 设置中心")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.configure(bg=background)
        dialog.protocol("WM_DELETE_WINDOW", lambda: close_dialog())
        dialog.grab_set()

        shell = tk.Frame(dialog, bg=background, padx=22, pady=18)
        shell.pack(fill="both", expand=True)

        tk.Label(
            shell,
            text="设置中心",
            bg=background,
            fg=foreground,
            font=("Microsoft YaHei UI", 16, "bold"),
        ).pack(anchor="w")
        tk.Label(
            shell,
            text="调整工作时间、日历和悬浮窗行为，保存后立即生效。",
            bg=background,
            fg=muted,
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", pady=(4, 14))

        notebook_style = ttk.Style(dialog)
        notebook_style.configure("BanClock.TNotebook", background=background, borderwidth=0)
        notebook_style.configure("BanClock.TNotebook.Tab", padding=(12, 6))
        notebook = ttk.Notebook(shell, style="BanClock.TNotebook")
        notebook.pack(fill="both", expand=True, pady=(0, 14))
        schedule_tab = tk.Frame(notebook, bg=background, padx=4, pady=8)
        calendar_tab = tk.Frame(notebook, bg=background, padx=4, pady=8)
        display_tab = tk.Frame(notebook, bg=background, padx=4, pady=8)
        notification_tab = tk.Frame(notebook, bg=background, padx=4, pady=8)
        notebook.add(schedule_tab, text="工作时间")
        notebook.add(calendar_tab, text="工作日历")
        notebook.add(display_tab, text="显示外观")
        notebook.add(notification_tab, text="提醒")

        schedule_frame = tk.LabelFrame(
            schedule_tab,
            text="工作时间",
            bg=background,
            fg=foreground,
            font=("Microsoft YaHei UI", 10, "bold"),
            padx=12,
            pady=8,
        )
        schedule_frame.pack(fill="both", expand=True, pady=(0, 12))
        schedule_fields = (
            ("morning_start", "上午上班"),
            ("lunch_start", "午休开始"),
            ("afternoon_start", "下午上班"),
            ("off_work", "下午下班"),
        )
        schedule_values = {}
        for column, (key, label) in enumerate(schedule_fields):
            tk.Label(
                schedule_frame,
                text=label,
                bg=background,
                fg=foreground,
                font=("Microsoft YaHei UI", 9),
            ).grid(row=0, column=column, padx=5, pady=(0, 4), sticky="w")
            value = tk.StringVar(value=self.config["schedule"][key])
            schedule_values[key] = value
            tk.Entry(
                schedule_frame,
                textvariable=value,
                width=9,
                font=("Consolas", 11),
                relief="flat",
            ).grid(row=1, column=column, padx=5, pady=(0, 3), sticky="we")
        tk.Label(
            schedule_frame,
            text="使用 24 小时制，例如 09:00；四个时间必须按顺序递增。",
            bg=background,
            fg=muted,
            font=("Microsoft YaHei UI", 8),
        ).grid(row=2, column=0, columnspan=4, padx=5, pady=(3, 0), sticky="w")
        schedule_config = self.config["schedule"]
        flexible_schedule_var = tk.BooleanVar(value=bool(schedule_config.get("work_segments")))
        tk.Checkbutton(
            schedule_frame,
            text="使用自定义工作时段（每行：开始 - 结束）",
            variable=flexible_schedule_var,
            bg=background,
            fg=foreground,
            activebackground=background,
            activeforeground=foreground,
            selectcolor="#26313A",
            font=("Microsoft YaHei UI", 9),
        ).grid(row=3, column=0, columnspan=4, padx=5, pady=(8, 2), sticky="w")
        segments_text = tk.Text(
            schedule_frame,
            width=34,
            height=3,
            font=("Consolas", 9),
            relief="flat",
            wrap="none",
        )
        segments_text.grid(row=4, column=0, columnspan=4, padx=5, pady=(2, 0), sticky="we")
        segments_text.insert("1.0", format_work_segments(schedule_config.get("work_segments") or [
            {"start": schedule_config["morning_start"], "end": schedule_config["lunch_start"]},
            {"start": schedule_config["afternoon_start"], "end": schedule_config["off_work"]},
        ]))
        tk.Label(
            schedule_frame,
            text="最多支持 4 段；关闭自定义模式时使用上方四个经典时间。",
            bg=background,
            fg=muted,
            font=("Microsoft YaHei UI", 8),
        ).grid(row=5, column=0, columnspan=4, padx=5, pady=(3, 0), sticky="w")
        overtime_var = tk.StringVar(value=str(schedule_config.get("overtime_end") or ""))
        tk.Label(
            schedule_frame,
            text="加班结束",
            bg=background,
            fg=foreground,
            font=("Microsoft YaHei UI", 9),
        ).grid(row=6, column=0, padx=5, pady=(8, 0), sticky="w")
        tk.Entry(
            schedule_frame,
            textvariable=overtime_var,
            width=9,
            font=("Consolas", 11),
            relief="flat",
        ).grid(row=6, column=1, padx=5, pady=(8, 0), sticky="w")
        tk.Label(
            schedule_frame,
            text="留空表示不追踪加班时间",
            bg=background,
            fg=muted,
            font=("Microsoft YaHei UI", 8),
        ).grid(row=6, column=2, columnspan=2, padx=5, pady=(8, 0), sticky="w")

        calendar_frame = tk.LabelFrame(
            calendar_tab,
            text="工作日历",
            bg=background,
            fg=foreground,
            font=("Microsoft YaHei UI", 10, "bold"),
            padx=12,
            pady=8,
        )
        calendar_frame.pack(fill="both", expand=True, pady=(0, 12))
        weekend_var = tk.BooleanVar(value=bool(self.config["calendar"]["weekend_rest"]))
        tk.Checkbutton(
            calendar_frame,
            text="周末默认休息",
            variable=weekend_var,
            bg=background,
            fg=foreground,
            activebackground=background,
            activeforeground=foreground,
            selectcolor="#26313A",
            font=("Microsoft YaHei UI", 9),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        tk.Label(
            calendar_frame,
            text="年度",
            bg=background,
            fg=foreground,
            font=("Microsoft YaHei UI", 9),
        ).grid(row=0, column=2, padx=(12, 4), pady=(0, 6), sticky="e")
        calendar_year_var = tk.StringVar(value=str(datetime.now().year))
        tk.Entry(
            calendar_frame,
            textvariable=calendar_year_var,
            width=8,
            font=("Consolas", 10),
            relief="flat",
        ).grid(row=0, column=3, pady=(0, 6), sticky="w")

        tk.Label(
            calendar_frame,
            text="节假日（每行一个日期）",
            bg=background,
            fg=foreground,
            font=("Microsoft YaHei UI", 9),
        ).grid(row=1, column=0, padx=(0, 8), sticky="nw")
        holiday_text = tk.Text(
            calendar_frame,
            width=24,
            height=4,
            font=("Consolas", 9),
            relief="flat",
            wrap="none",
        )
        holiday_text.grid(row=2, column=0, padx=(0, 8), pady=(3, 0), sticky="we")
        holiday_text.insert("1.0", format_date_list(self.config["calendar"]["holiday_dates"]))

        tk.Label(
            calendar_frame,
            text="调休工作日（每行一个日期）",
            bg=background,
            fg=foreground,
            font=("Microsoft YaHei UI", 9),
        ).grid(row=1, column=1, padx=(8, 0), sticky="nw")
        workday_text = tk.Text(
            calendar_frame,
            width=24,
            height=4,
            font=("Consolas", 9),
            relief="flat",
            wrap="none",
        )
        workday_text.grid(row=2, column=1, padx=(8, 0), pady=(3, 0), sticky="we")
        workday_text.insert("1.0", format_date_list(self.config["calendar"]["workday_overrides"]))
        tk.Label(
            calendar_frame,
            text="日期格式：YYYY-MM-DD",
            bg=background,
            fg=muted,
            font=("Microsoft YaHei UI", 8),
        ).grid(row=3, column=0, columnspan=2, padx=0, pady=(5, 0), sticky="w")

        def import_calendar():
            path = filedialog.askopenfilename(
                parent=dialog,
                title="导入年度日历",
                filetypes=(("日历 JSON", "*.json"), ("所有文件", "*.*")),
            )
            if not path:
                return
            try:
                imported = read_calendar_file(path)
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
                messagebox.showerror("日历文件无效", str(error), parent=dialog)
                return
            holiday_text.delete("1.0", "end")
            holiday_text.insert("1.0", format_date_list(imported["holiday_dates"]))
            workday_text.delete("1.0", "end")
            workday_text.insert("1.0", format_date_list(imported["workday_overrides"]))
            if imported["year"] is not None:
                calendar_year_var.set(str(imported["year"]))

        def export_calendar():
            try:
                year_value = calendar_year_var.get().strip() or None
                if year_value is not None:
                    year_value = int(year_value)
                holidays, workdays = normalize_calendar_dates(
                    holiday_text.get("1.0", "end"),
                    workday_text.get("1.0", "end"),
                )
            except (TypeError, ValueError) as error:
                messagebox.showerror("日历设置无效", str(error), parent=dialog)
                return
            path = filedialog.asksaveasfilename(
                parent=dialog,
                title="导出年度日历",
                initialfile=f"work-calendar-{year_value or datetime.now().year}.json",
                defaultextension=".json",
                filetypes=(("日历 JSON", "*.json"), ("所有文件", "*.*")),
            )
            if not path:
                return
            try:
                write_calendar_file(path, holidays, workdays, year_value)
            except (OSError, TypeError, ValueError) as error:
                messagebox.showerror("导出日历失败", str(error), parent=dialog)
                return
            messagebox.showinfo("导出完成", f"日历已保存到：\n{path}", parent=dialog)

        def sync_calendar():
            try:
                year_value = int(calendar_year_var.get().strip() or datetime.now().year)
                if year_value < 1900 or year_value > 2200:
                    raise ValueError("日历年份必须在 1900 到 2200 之间")
            except (TypeError, ValueError) as error:
                messagebox.showerror("日历设置无效", str(error), parent=dialog)
                return

            sync_button.configure(state="disabled")

            def finish(result, used_cache=False, error=None):
                try:
                    if not dialog.winfo_exists():
                        return
                    sync_button.configure(state="normal")
                except tk.TclError:
                    return
                if error is not None:
                    messagebox.showerror("同步官方日历失败", str(error), parent=dialog)
                    return

                try:
                    current_holidays = set(parse_date_list(holiday_text.get("1.0", "end")))
                    current_workdays = set(parse_date_list(workday_text.get("1.0", "end")))
                    merged_holidays = current_holidays | set(result["holiday_dates"])
                    merged_workdays = current_workdays | set(result["workday_overrides"])
                    # A workday override is the explicit, higher-priority
                    # choice when a hand-edited date conflicts with a source
                    # holiday entry.
                    merged_holidays -= merged_workdays
                    holiday_text.delete("1.0", "end")
                    holiday_text.insert("1.0", format_date_list(merged_holidays))
                    workday_text.delete("1.0", "end")
                    workday_text.insert("1.0", format_date_list(merged_workdays))
                    calendar_year_var.set(str(result["year"]))
                except (TypeError, ValueError) as merge_error:
                    messagebox.showerror("同步日历失败", str(merge_error), parent=dialog)
                    return

                source_name = "本地缓存（网络不可用）" if used_cache else "在线数据"
                papers = result.get("papers") or []
                paper_text = f"\n公告来源：{papers[0]}" if papers else ""
                messagebox.showinfo(
                    "同步完成",
                    f"已合并 {result['year']} 年官方日历（{source_name}）。\n"
                    f"节假日 {len(result['holiday_dates'])} 天，调休工作日 {len(result['workday_overrides'])} 天。"
                    f"{paper_text}\n\n请点击“保存设置”使日历生效。",
                    parent=dialog,
                )

            def worker():
                try:
                    result = fetch_holiday_calendar(year_value, HOLIDAY_SOURCE_URL)
                    try:
                        write_calendar_cache(holiday_cache_path(year_value), result)
                    except OSError:
                        LOGGER.warning("无法写入官方日历缓存", exc_info=True)
                    self.root.after(0, lambda: finish(result))
                    return
                except Exception as network_error:  # noqa: BLE001 - fall back to a validated cache.
                    try:
                        result = read_calendar_cache(holiday_cache_path(year_value), year_value)
                    except Exception as cache_error:  # noqa: BLE001 - report both useful causes.
                        error_message = (
                            f"在线同步失败：{network_error}\n本地缓存也不可用：{cache_error}"
                        )
                        self.root.after(
                            0,
                            lambda message=error_message: finish(None, error=message),
                        )
                        return
                    self.root.after(0, lambda: finish(result, used_cache=True))

            threading.Thread(target=worker, name="holiday-sync", daemon=True).start()

        calendar_actions = tk.Frame(calendar_frame, bg=background)
        calendar_actions.grid(row=4, column=0, columnspan=4, pady=(8, 0), sticky="w")
        tk.Button(
            calendar_actions,
            text="导入年度日历",
            command=import_calendar,
            relief="flat",
            padx=8,
            pady=3,
        ).pack(side="left")
        tk.Button(
            calendar_actions,
            text="导出当前日历",
            command=export_calendar,
            relief="flat",
            padx=8,
            pady=3,
        ).pack(side="left", padx=(8, 0))
        sync_button = tk.Button(
            calendar_actions,
            text="同步官方日历",
            command=sync_calendar,
            relief="flat",
            padx=8,
            pady=3,
        )
        sync_button.pack(side="left", padx=(8, 0))
        tk.Label(
            calendar_frame,
            text="数据来自国务院公告的开源镜像；同步会合并当前手动日期，调休工作日优先。",
            bg=background,
            fg=muted,
            font=("Microsoft YaHei UI", 8),
        ).grid(row=5, column=0, columnspan=4, padx=0, pady=(5, 0), sticky="w")

        display_frame = tk.LabelFrame(
            display_tab,
            text="悬浮窗",
            bg=background,
            fg=foreground,
            font=("Microsoft YaHei UI", 10, "bold"),
            padx=12,
            pady=8,
        )
        display_frame.pack(fill="both", expand=True, pady=(0, 14))
        topmost_var = tk.BooleanVar(value=bool(self.config["window"]["always_on_top"]))
        tk.Checkbutton(
            display_frame,
            text="始终置顶",
            variable=topmost_var,
            bg=background,
            fg=foreground,
            activebackground=background,
            activeforeground=foreground,
            selectcolor="#26313A",
            font=("Microsoft YaHei UI", 9),
        ).grid(row=0, column=0, sticky="w")
        theme_key = self.config["style"].get("theme", "dark")
        theme_var = tk.StringVar(value=THEME_LABELS.get(theme_key, THEME_LABELS["dark"]))
        tk.Label(
            display_frame,
            text="主题",
            bg=background,
            fg=foreground,
            font=("Microsoft YaHei UI", 9),
        ).grid(row=0, column=1, padx=(18, 6), sticky="e")
        theme_menu = tk.OptionMenu(display_frame, theme_var, *THEME_LABELS.values())
        theme_menu.configure(relief="flat", highlightthickness=0, font=("Microsoft YaHei UI", 9))
        theme_menu.grid(row=0, column=2, sticky="w")
        tk.Label(
            display_frame,
            text="透明度",
            bg=background,
            fg=foreground,
            font=("Microsoft YaHei UI", 9),
        ).grid(row=1, column=0, pady=(8, 0), sticky="w")
        alpha_var = tk.DoubleVar(value=float(self.config["window"]["alpha"]))
        tk.Scale(
            display_frame,
            from_=0.55,
            to=1.0,
            resolution=0.05,
            orient="horizontal",
            variable=alpha_var,
            showvalue=True,
            length=250,
            bg=background,
            fg=foreground,
            troughcolor="#26313A",
            highlightthickness=0,
            activebackground=accent,
        ).grid(row=1, column=1, padx=(12, 0), pady=(5, 0), sticky="w")
        tk.Label(
            display_frame,
            text="右下角边距",
            bg=background,
            fg=foreground,
            font=("Microsoft YaHei UI", 9),
        ).grid(row=2, column=0, pady=(8, 0), sticky="w")
        margin_var = tk.IntVar(value=int(self.config["window"].get("margin", 18)))
        tk.Spinbox(
            display_frame,
            from_=8,
            to=64,
            textvariable=margin_var,
            width=6,
            font=("Consolas", 10),
            relief="flat",
        ).grid(row=2, column=1, padx=(12, 0), pady=(8, 0), sticky="w")
        tk.Button(
            display_frame,
            text="恢复默认位置",
            command=self.reset_position,
            relief="flat",
            padx=8,
            pady=3,
        ).grid(row=2, column=2, padx=(12, 0), pady=(8, 0), sticky="w")
        display = self.config.get("display", {})
        compact_var = tk.BooleanVar(value=bool(display.get("compact", False)))
        show_seconds_var = tk.BooleanVar(value=bool(display.get("show_seconds", True)))
        show_schedule_var = tk.BooleanVar(value=bool(display.get("show_schedule", True)))
        display_checks = (
            (compact_var, "紧凑模式（隐藏时间段）"),
            (show_seconds_var, "显示秒数"),
            (show_schedule_var, "显示上下班时间段"),
        )
        for row, (variable, label) in enumerate(display_checks):
            tk.Checkbutton(
                display_frame,
                text=label,
                variable=variable,
                bg=background,
                fg=foreground,
                activebackground=background,
                activeforeground=foreground,
                selectcolor="#26313A",
                font=("Microsoft YaHei UI", 9),
            ).grid(row=3 + row // 2, column=row % 2, padx=(0, 18), pady=2, sticky="w")

        notification_frame = tk.LabelFrame(
            notification_tab,
            text="提醒",
            bg=background,
            fg=foreground,
            font=("Microsoft YaHei UI", 10, "bold"),
            padx=12,
            pady=8,
        )
        notification_frame.pack(fill="both", expand=True, pady=(0, 14))
        notifications = self.config.get("notifications", {})
        notifications_enabled_var = tk.BooleanVar(value=bool(notifications.get("enabled", True)))
        lunch_notification_var = tk.BooleanVar(value=bool(notifications.get("lunch", True)))
        off_work_notification_var = tk.BooleanVar(value=bool(notifications.get("off_work", True)))
        sound_notification_var = tk.BooleanVar(value=bool(notifications.get("sound", False)))
        lead_minutes_var = tk.IntVar(value=max(0, min(120, int(notifications.get("lead_minutes", 0)))))
        quiet_hours = notifications.get("quiet_hours", {})
        quiet_hours_enabled_var = tk.BooleanVar(value=bool(quiet_hours.get("enabled", False)))
        quiet_start_var = tk.StringVar(value=str(quiet_hours.get("start", "22:00")))
        quiet_end_var = tk.StringVar(value=str(quiet_hours.get("end", "08:00")))
        notification_checks = (
            (notifications_enabled_var, "启用 Windows 提醒"),
            (lunch_notification_var, "午休开始时提醒"),
            (off_work_notification_var, "下班时提醒"),
            (sound_notification_var, "提醒时播放提示音"),
        )
        for row, (variable, label) in enumerate(notification_checks):
            tk.Checkbutton(
                notification_frame,
                text=label,
                variable=variable,
                bg=background,
                fg=foreground,
                activebackground=background,
                activeforeground=foreground,
                selectcolor="#26313A",
                font=("Microsoft YaHei UI", 9),
            ).grid(row=row // 2, column=row % 2, padx=(0, 18), pady=2, sticky="w")
        tk.Label(
            notification_frame,
            text="提前提醒分钟（0=关闭）",
            bg=background,
            fg=foreground,
            font=("Microsoft YaHei UI", 9),
        ).grid(row=2, column=0, padx=(0, 12), pady=(8, 2), sticky="w")
        tk.Spinbox(
            notification_frame,
            from_=0,
            to=120,
            textvariable=lead_minutes_var,
            width=6,
            font=("Consolas", 10),
            relief="flat",
        ).grid(row=2, column=1, padx=(0, 18), pady=(8, 2), sticky="w")
        tk.Checkbutton(
            notification_frame,
            text="启用免打扰时段",
            variable=quiet_hours_enabled_var,
            bg=background,
            fg=foreground,
            activebackground=background,
            activeforeground=foreground,
            selectcolor="#26313A",
            font=("Microsoft YaHei UI", 9),
        ).grid(row=3, column=0, padx=(0, 12), pady=2, sticky="w")
        quiet_time_frame = tk.Frame(notification_frame, bg=background)
        quiet_time_frame.grid(row=3, column=1, columnspan=2, padx=(0, 18), pady=2, sticky="w")
        tk.Label(quiet_time_frame, text="从", bg=background, fg=muted, font=("Microsoft YaHei UI", 9)).pack(side="left")
        tk.Entry(
            quiet_time_frame,
            textvariable=quiet_start_var,
            width=7,
            font=("Consolas", 10),
            relief="flat",
        ).pack(side="left", padx=(4, 8))
        tk.Label(quiet_time_frame, text="到", bg=background, fg=muted, font=("Microsoft YaHei UI", 9)).pack(side="left")
        tk.Entry(
            quiet_time_frame,
            textvariable=quiet_end_var,
            width=7,
            font=("Consolas", 10),
            relief="flat",
        ).pack(side="left", padx=(4, 0))
        tk.Button(
            notification_frame,
            text="发送测试提醒",
            command=self.test_notification,
            relief="flat",
            padx=8,
            pady=3,
        ).grid(row=4, column=0, columnspan=2, padx=0, pady=(8, 0), sticky="w")

        actions = tk.Frame(shell, bg=background)
        actions.pack(fill="x")

        def close_dialog():
            self.settings_dialog = None
            try:
                dialog.grab_release()
            except tk.TclError:
                pass
            dialog.destroy()

        def save_settings():
            try:
                candidate = deepcopy(self.config)
                schedule_candidate = {key: value.get().strip() for key, value in schedule_values.items()}
                if flexible_schedule_var.get():
                    segments = parse_work_segments(segments_text.get("1.0", "end"))
                    schedule_candidate["work_segments"] = segments
                    schedule_candidate["morning_start"] = segments[0]["start"]
                    schedule_candidate["lunch_start"] = segments[0]["end"]
                    schedule_candidate["afternoon_start"] = (
                        segments[1]["start"] if len(segments) > 1 else segments[0]["end"]
                    )
                    schedule_candidate["off_work"] = segments[-1]["end"]
                else:
                    schedule_candidate.pop("work_segments", None)
                overtime_value = overtime_var.get().strip()
                schedule_candidate["overtime_end"] = (
                    format_clock(parse_clock(overtime_value)) if overtime_value else None
                )
                candidate["schedule"] = schedule_candidate
                candidate["calendar"]["weekend_rest"] = bool(weekend_var.get())
                candidate["calendar"]["holiday_dates"] = parse_date_list(holiday_text.get("1.0", "end"))
                candidate["calendar"]["workday_overrides"] = parse_date_list(workday_text.get("1.0", "end"))
                candidate["window"]["alpha"] = round(float(alpha_var.get()), 2)
                candidate["window"]["always_on_top"] = bool(topmost_var.get())
                candidate["window"]["margin"] = max(8, min(64, int(margin_var.get())))
                selected_theme = next(
                    (key for key, label in THEME_LABELS.items() if label == theme_var.get()),
                    "dark",
                )
                candidate["style"].update(deepcopy(THEME_PRESETS[selected_theme]))
                candidate["display"] = {
                    "compact": bool(compact_var.get()),
                    "show_seconds": bool(show_seconds_var.get()),
                    "show_schedule": bool(show_schedule_var.get()),
                }
                candidate["notifications"] = {
                    "enabled": bool(notifications_enabled_var.get()),
                    "lunch": bool(lunch_notification_var.get()),
                    "off_work": bool(off_work_notification_var.get()),
                    "sound": bool(sound_notification_var.get()),
                    "lead_minutes": max(0, min(120, int(lead_minutes_var.get()))),
                    "quiet_hours": {
                        "enabled": bool(quiet_hours_enabled_var.get()),
                        "start": format_clock(parse_clock(quiet_start_var.get().strip())),
                        "end": format_clock(parse_clock(quiet_end_var.get().strip())),
                    },
                }
                WorkSchedule(candidate)
                WorkCalendar(candidate)
                save_config(candidate)
            except (TypeError, ValueError, OSError) as error:
                messagebox.showerror("设置无效", str(error), parent=dialog)
                return

            self.apply_config(candidate)
            close_dialog()

        tk.Button(
            actions,
            text="取消",
            command=close_dialog,
            width=10,
            relief="flat",
            padx=8,
            pady=5,
        ).pack(side="right", padx=(8, 0))
        tk.Button(
            actions,
            text="保存设置",
            command=save_settings,
            width=10,
            relief="flat",
            bg=accent,
            fg="#FFFFFF",
            activebackground=accent,
            activeforeground="#FFFFFF",
            padx=8,
            pady=5,
        ).pack(side="right")
        dialog.bind("<Escape>", lambda _event: close_dialog())

    def apply_config(self, config):
        self.config = config
        self.calendar = WorkCalendar(self.config)
        self.schedule = WorkSchedule(self.config)
        self.apply_style()
        self.root.attributes("-alpha", float(self.config["window"]["alpha"]))
        self.root.attributes("-topmost", bool(self.config["window"]["always_on_top"]))
        self.refresh_static_ranges()
        self.apply_display_preferences()
        self.place_window()
        self.update_display()

    def reload_config(self):
        try:
            self.apply_config(load_config())
        except (KeyError, TypeError, ValueError) as error:
            messagebox.showerror("配置无效", str(error), parent=self.root)

    def open_config_folder(self):
        try:
            USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            if hasattr(os, "startfile"):
                os.startfile(str(USER_CONFIG_DIR))
            else:
                webbrowser.open(USER_CONFIG_DIR.as_uri())
        except (OSError, webbrowser.Error) as error:
            messagebox.showerror("打开配置目录失败", str(error), parent=self.root)

    def open_updates_folder(self):
        try:
            updates_dir = USER_CONFIG_DIR / "updates"
            updates_dir.mkdir(parents=True, exist_ok=True)
            if hasattr(os, "startfile"):
                os.startfile(str(updates_dir))
            else:
                webbrowser.open(updates_dir.as_uri())
        except (OSError, webbrowser.Error) as error:
            messagebox.showerror("打开下载目录失败", str(error), parent=self.root)

    def show_about(self):
        messagebox.showinfo(
            f"关于{APP_NAME}",
            f"{APP_NAME} v{APP_VERSION}\n\n"
            "桌面上下班倒计时工具\n"
            f"配置目录：{USER_CONFIG_DIR}",
            parent=self.root,
        )

    def check_for_updates(self):
        if self.update_thread is not None and self.update_thread.is_alive():
            messagebox.showinfo("检查更新", "正在检查最新版本，请稍候。", parent=self.root)
            return

        def worker():
            api_url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"
            try:
                request = urllib.request.Request(
                    api_url,
                    headers={"Accept": "application/vnd.github+json", "User-Agent": f"{APP_NAME}/{APP_VERSION}"},
                )
                with urllib.request.urlopen(request, timeout=8) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                latest_tag = str(payload.get("tag_name", "")).strip()
                if not latest_tag:
                    raise ValueError("Release 没有可用的版本号")
                release_url = str(payload.get("html_url") or latest_release_url())
                assets = payload.get("assets") or []
                asset = next(
                    (
                        item for item in assets
                        if str(item.get("name", "")).lower().endswith(".exe")
                    ),
                    None,
                )
                release_info = {
                    "tag": latest_tag,
                    "url": release_url,
                    "asset_url": str(asset.get("browser_download_url")) if asset else None,
                    "asset_name": str(asset.get("name")) if asset else None,
                    "digest": str(asset.get("digest") or "") if asset else "",
                }
                is_newer = version_tuple(latest_tag) > version_tuple(APP_VERSION)
                self.call_on_ui(lambda: self.show_update_result(release_info, is_newer))
            except Exception as error:
                error_message = str(error)
                self.call_on_ui(
                    lambda message=error_message: self.show_update_error(message)
                )

        self.update_thread = threading.Thread(target=worker, name="BanClockUpdateCheck", daemon=True)
        self.update_thread.start()

    def show_update_error(self, message):
        self.update_thread = None
        messagebox.showerror("检查更新失败", message, parent=self.root)

    def show_update_result(self, release_info, is_newer):
        self.update_thread = None
        latest_tag = release_info["tag"]
        release_url = release_info["url"]
        if is_newer:
            should_open = messagebox.askyesno(
                "发现新版本",
                f"当前版本：v{APP_VERSION}\n最新版本：{latest_tag}\n\n是否下载并校验新版本？",
                parent=self.root,
            )
            if should_open:
                if release_info.get("asset_url"):
                    self.download_update(release_info)
                else:
                    webbrowser.open(release_url)
        else:
            messagebox.showinfo("检查更新", f"当前已是最新版本（v{APP_VERSION}）。", parent=self.root)

    def download_update(self, release_info):
        if self.update_thread is not None and self.update_thread.is_alive():
            return
        messagebox.showinfo(
            "开始下载",
            "将下载并校验新版本 EXE，完成后会打开下载目录。",
            parent=self.root,
        )

        def worker():
            update_dir = USER_CONFIG_DIR / "updates"
            temp_path = None
            try:
                update_dir.mkdir(parents=True, exist_ok=True)
                safe_tag = re.sub(r"[^A-Za-z0-9._-]+", "-", release_info["tag"])
                target_path = update_dir / f"BanClock-{safe_tag}.exe"
                with tempfile.NamedTemporaryFile(
                    mode="wb", suffix=".download", dir=update_dir, delete=False
                ) as temporary_file:
                    temp_path = Path(temporary_file.name)
                    request = urllib.request.Request(
                        release_info["asset_url"],
                        headers={
                            "Accept": "application/octet-stream",
                            "User-Agent": f"{APP_NAME}/{APP_VERSION}",
                        },
                    )
                    digest = hashlib.sha256()
                    total_size = 0
                    with urllib.request.urlopen(request, timeout=30) as response:
                        while True:
                            chunk = response.read(1024 * 1024)
                            if not chunk:
                                break
                            total_size += len(chunk)
                            if total_size > 200 * 1024 * 1024:
                                raise ValueError("更新文件超过 200 MB，已停止下载")
                            digest.update(chunk)
                            temporary_file.write(chunk)
                actual_digest = digest.hexdigest().lower()
                expected_digest = release_info.get("digest", "").replace("sha256:", "").lower()
                if expected_digest and actual_digest != expected_digest:
                    raise ValueError("下载文件校验失败，文件可能已损坏")
                os.replace(temp_path, target_path)
                temp_path = None
                self.call_on_ui(lambda: self.update_download_result(target_path, actual_digest))
            except Exception as error:
                if temp_path is not None:
                    try:
                        temp_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                error_message = str(error)
                self.call_on_ui(lambda message=error_message: self.show_update_error(message))

        self.update_thread = threading.Thread(target=worker, name="BanClockUpdateDownload", daemon=True)
        self.update_thread.start()

    def update_download_result(self, target_path, digest):
        self.update_thread = None
        can_install = bool(getattr(sys, "frozen", False) and (APP_DIR / "update_helper.ps1").exists())
        should_install = messagebox.askyesno(
            "下载完成",
            f"文件已通过 SHA-256 校验：\n{target_path}\n\n"
            + ("是否立即替换当前版本并重启？" if can_install else "当前为开发模式，请打开下载目录手动运行新版本。"),
            parent=self.root,
        )
        if should_install and can_install:
            self.start_update_helper(target_path)
        elif should_install:
            self.open_updates_folder()

    def start_update_helper(self, package_path):
        helper_path = APP_DIR / "update_helper.ps1"
        if not helper_path.exists() or not getattr(sys, "frozen", False):
            self.open_updates_folder()
            return
        target_path = Path(sys.executable).resolve()
        backup_path = target_path.with_suffix(target_path.suffix + ".previous")
        try:
            subprocess.Popen(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(helper_path),
                    "-Target",
                    str(target_path),
                    "-Package",
                    str(package_path),
                    "-ProcessId",
                    str(os.getpid()),
                    "-Backup",
                    str(backup_path),
                ],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                close_fds=True,
            )
            self.quit()
        except OSError as error:
            messagebox.showerror("启动更新失败", str(error), parent=self.root)

    def update(self):
        self.update_display()
        self.root.after(1000, self.update)

    def maybe_notify(self, state, now):
        """Send transition and optional lead-time notifications once per day."""
        current_date = now.date()
        if self.last_state_date != current_date:
            self.last_state_date = current_date
            self.last_state_kind = None
            self.sent_alerts.clear()

        previous_kind = self.last_state_kind
        current_kind = state.get("kind")
        self.last_state_kind = current_kind

        notifications = self.config.get("notifications", {})
        if not bool(notifications.get("enabled", True)) or self.is_quiet_hours(now):
            return

        lead_minutes = max(0, min(120, int(notifications.get("lead_minutes", 0))))
        if lead_minutes:
            lead_delta = timedelta(minutes=lead_minutes)
            for event_key, event_at, title, message in self.schedule.notification_events(now.date(), self.calendar):
                if event_at - lead_delta <= now < event_at:
                    enabled = (
                        notifications.get("lunch", True)
                        if event_key == "lunch"
                        else notifications.get("off_work", True)
                    )
                    if enabled:
                        self.send_notification_once(
                            ("lead", event_key),
                            f"{title}提醒",
                            f"{lead_minutes} 分钟后{message.rstrip('。')}。",
                            notifications,
                        )

        if previous_kind is None or previous_kind == current_kind:
            return
        if current_kind == "lunch" and bool(notifications.get("lunch", True)):
            self.send_notification_once(
                ("transition", "lunch"), "午休提醒", "午休开始了，休息一下吧。", notifications
            )
        elif current_kind in ("off_work", "overtime") and previous_kind in ("afternoon", "morning"):
            if bool(notifications.get("off_work", True)):
                self.send_notification_once(
                    ("transition", "off_work"), "下班提醒", "下班时间到了，今天辛苦了。", notifications
                )

    def is_quiet_hours(self, now):
        quiet_hours = self.config.get("notifications", {}).get("quiet_hours", {})
        if not bool(quiet_hours.get("enabled", False)):
            return False
        try:
            start = parse_clock(str(quiet_hours.get("start", "22:00")))
            end = parse_clock(str(quiet_hours.get("end", "08:00")))
        except (TypeError, ValueError):
            return False
        current = now.time()
        if start == end:
            return False
        if start < end:
            return start <= current < end
        return current >= start or current < end

    def send_notification_once(self, key, title, message, notifications):
        if key in self.sent_alerts:
            return
        self.notify_user(title, message, notifications)
        self.sent_alerts.add(key)

    def test_notification(self):
        notifications = self.config.get("notifications", {})
        self.notify_user("提醒测试", "班时钟提醒功能正常。", notifications)

    def notify_user(self, title, message, notifications):
        """Send a tray notification and optionally play the Windows sound."""
        if self.tray_icon is not None:
            try:
                self.tray_icon.notify(message, title)
            except Exception:
                # Some tray backends do not implement notifications. The
                # optional sound still provides feedback in that case.
                pass

        if bool(notifications.get("sound", False)) and winsound is not None:
            try:
                winsound.MessageBeep(winsound.MB_ICONINFORMATION)
            except Exception:
                pass

    def update_display(self):
        now = datetime.now()
        state = self.schedule.state(now, self.calendar)
        self.maybe_notify(state, now)

        status_colors = {
            "rest": self.config["style"]["muted"],
            "before_work": self.config["style"]["accent"],
            "morning": "#51D88A",
            "lunch": "#F5B84B",
            "break": "#F5B84B",
            "afternoon": self.config["style"]["accent"],
            "overtime": "#F97316",
            "off_work": "#A78BFA",
        }
        self.status_value.configure(
            text=state["status"],
            fg=status_colors.get(state.get("kind"), self.config["style"]["accent"]),
        )
        self.countdown_label.configure(text=state["countdown_name"])
        self.countdown_value.configure(text=format_remaining(state["countdown_at"] - now))
        self.update_progress(self.schedule.progress(now, self.calendar))
        show_seconds = bool(self.config.get("display", {}).get("show_seconds", True))
        clock_format = "%Y-%m-%d %H:%M:%S" if show_seconds else "%Y-%m-%d %H:%M"
        self.clock_label.configure(text=now.strftime(clock_format))

    def quit(self):
        if self.is_closing:
            return
        self.is_closing = True
        if self.settings_dialog is not None:
            try:
                self.settings_dialog.destroy()
            except tk.TclError:
                pass
        self.save_position()
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    setup_logging()
    LOGGER.info("启动 %s v%s", APP_NAME, APP_VERSION)
    if not acquire_single_instance():
        LOGGER.info("检测到已有实例，退出当前进程")
        return
    try:
        CountdownWidget().run()
    except Exception as error:
        LOGGER.exception("程序运行失败")
        try:
            messagebox.showerror(APP_NAME, str(error))
        except tk.TclError:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
