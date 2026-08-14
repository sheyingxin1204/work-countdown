import ctypes
import json
import os
import re
import shutil
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from copy import deepcopy
from datetime import date, datetime, time, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import messagebox

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
APP_VERSION = "1.1.0"
GITHUB_REPOSITORY = "sheyingxin1204/work-countdown"
LEGACY_CONFIG_PATH = APP_DIR / "config.json"
if os.name == "nt":
    _appdata_root = Path(os.environ.get("APPDATA") or APP_DIR)
else:
    _appdata_root = APP_DIR
USER_CONFIG_DIR = _appdata_root / "BanClock"
CONFIG_PATH = USER_CONFIG_DIR / "config.json"
ICON_RELATIVE_PATH = Path("assets") / "ban-clock-icon.png"
SINGLE_INSTANCE_MUTEX = None


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
    },
    "display": {
        "compact": False,
        "show_seconds": True,
        "show_schedule": True,
    },
    "style": {
        "background": "#101418",
        "foreground": "#F3F7FA",
        "muted": "#9BA7B0",
        "accent": "#39A0ED",
    },
}


def deep_merge(base, override):
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


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
    except (json.JSONDecodeError, OSError):
        messagebox.showwarning("Work Countdown", "配置文件读取失败，将使用默认配置。")
        return deepcopy(DEFAULT_CONFIG)

    return deep_merge(DEFAULT_CONFIG, migrate_legacy_config(config))


def migrate_legacy_config(config):
    if "schedule" in config:
        return config

    migrated = deepcopy(config)
    migrated["schedule"] = {
        "morning_start": "10:30",
        "lunch_start": config.get("lunch_time", "13:30"),
        "afternoon_start": "15:30",
        "off_work": config.get("off_work_time", "19:30"),
    }
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


class WorkCalendar:
    def __init__(self, config):
        calendar = config["calendar"]
        self.weekend_rest = bool(calendar["weekend_rest"])
        self.holiday_dates = {parse_date(value) for value in parse_date_list(calendar["holiday_dates"])}
        self.workday_overrides = {parse_date(value) for value in parse_date_list(calendar["workday_overrides"])}

    def is_workday(self, target_date):
        if target_date in self.workday_overrides:
            return True
        if target_date in self.holiday_dates:
            return False
        if self.weekend_rest and target_date.weekday() >= 5:
            return False
        return True

    def next_workday(self, start_date):
        target_date = start_date
        for _ in range(370):
            if self.is_workday(target_date):
                return target_date
            target_date += timedelta(days=1)
        raise RuntimeError("找不到下一个工作日，请检查节假日配置。")


class WorkSchedule:
    def __init__(self, config):
        schedule = config["schedule"]
        self.morning_start = parse_clock(schedule["morning_start"])
        self.lunch_start = parse_clock(schedule["lunch_start"])
        self.afternoon_start = parse_clock(schedule["afternoon_start"])
        self.off_work = parse_clock(schedule["off_work"])
        if not (
            self.morning_start < self.lunch_start < self.afternoon_start < self.off_work
        ):
            raise ValueError("上下班时间必须依次递增，请检查时间设置。")

    def at(self, target_date, target_time):
        return datetime.combine(target_date, target_time)

    def morning_range_text(self):
        return f"{format_clock(self.morning_start)} - {format_clock(self.lunch_start)}"

    def afternoon_range_text(self):
        return f"{format_clock(self.afternoon_start)} - {format_clock(self.off_work)}"

    def progress(self, now, calendar):
        """Return the elapsed fraction of the workday, clamped to 0..1."""
        if not calendar.is_workday(now.date()):
            return 0.0
        start = self.at(now.date(), self.morning_start)
        end = self.at(now.date(), self.off_work)
        total_seconds = (end - start).total_seconds()
        if total_seconds <= 0:
            return 0.0
        elapsed_seconds = (now - start).total_seconds()
        return max(0.0, min(1.0, elapsed_seconds / total_seconds))

    def state(self, now, calendar):
        today = now.date()

        if not calendar.is_workday(today):
            next_day = calendar.next_workday(today + timedelta(days=1))
            return {
                "kind": "rest",
                "status": "休息日",
                "countdown_name": "下个上班",
                "countdown_at": self.at(next_day, self.morning_start),
            }

        morning_start = self.at(today, self.morning_start)
        lunch_start = self.at(today, self.lunch_start)
        afternoon_start = self.at(today, self.afternoon_start)
        off_work = self.at(today, self.off_work)

        if now < morning_start:
            return {
                "kind": "before_work",
                "status": "未上班",
                "countdown_name": "距离上班",
                "countdown_at": morning_start,
            }
        if now < lunch_start:
            return {
                "kind": "morning",
                "status": "上午上班",
                "countdown_name": "距离午休",
                "countdown_at": lunch_start,
            }
        if now < afternoon_start:
            return {
                "kind": "lunch",
                "status": "午休中",
                "countdown_name": "下午上班",
                "countdown_at": afternoon_start,
            }
        if now < off_work:
            return {
                "kind": "afternoon",
                "status": "下午上班",
                "countdown_name": "距离下班",
                "countdown_at": off_work,
            }

        next_day = calendar.next_workday(today + timedelta(days=1))
        return {
            "kind": "off_work",
            "status": "已下班",
            "countdown_name": "下个上班",
            "countdown_at": self.at(next_day, self.morning_start),
        }


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

        schedule_frame = tk.LabelFrame(
            shell,
            text="工作时间",
            bg=background,
            fg=foreground,
            font=("Microsoft YaHei UI", 10, "bold"),
            padx=12,
            pady=8,
        )
        schedule_frame.pack(fill="x", pady=(0, 12))
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

        calendar_frame = tk.LabelFrame(
            shell,
            text="工作日历",
            bg=background,
            fg=foreground,
            font=("Microsoft YaHei UI", 10, "bold"),
            padx=12,
            pady=8,
        )
        calendar_frame.pack(fill="x", pady=(0, 12))
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

        display_frame = tk.LabelFrame(
            shell,
            text="悬浮窗",
            bg=background,
            fg=foreground,
            font=("Microsoft YaHei UI", 10, "bold"),
            padx=12,
            pady=8,
        )
        display_frame.pack(fill="x", pady=(0, 14))
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
            shell,
            text="提醒",
            bg=background,
            fg=foreground,
            font=("Microsoft YaHei UI", 10, "bold"),
            padx=12,
            pady=8,
        )
        notification_frame.pack(fill="x", pady=(0, 14))
        notifications = self.config.get("notifications", {})
        notifications_enabled_var = tk.BooleanVar(value=bool(notifications.get("enabled", True)))
        lunch_notification_var = tk.BooleanVar(value=bool(notifications.get("lunch", True)))
        off_work_notification_var = tk.BooleanVar(value=bool(notifications.get("off_work", True)))
        sound_notification_var = tk.BooleanVar(value=bool(notifications.get("sound", False)))
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
                candidate["schedule"] = {key: value.get().strip() for key, value in schedule_values.items()}
                candidate["calendar"]["weekend_rest"] = bool(weekend_var.get())
                candidate["calendar"]["holiday_dates"] = parse_date_list(holiday_text.get("1.0", "end"))
                candidate["calendar"]["workday_overrides"] = parse_date_list(workday_text.get("1.0", "end"))
                candidate["window"]["alpha"] = round(float(alpha_var.get()), 2)
                candidate["window"]["always_on_top"] = bool(topmost_var.get())
                candidate["window"]["margin"] = max(8, min(64, int(margin_var.get())))
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
                is_newer = version_tuple(latest_tag) > version_tuple(APP_VERSION)
                self.call_on_ui(lambda: self.show_update_result(latest_tag, release_url, is_newer))
            except Exception as error:
                error_message = str(error)
                self.call_on_ui(
                    lambda message=error_message: messagebox.showerror(
                        "检查更新失败", message, parent=self.root
                    )
                )

        self.update_thread = threading.Thread(target=worker, name="BanClockUpdateCheck", daemon=True)
        self.update_thread.start()

    def show_update_result(self, latest_tag, release_url, is_newer):
        self.update_thread = None
        if is_newer:
            should_open = messagebox.askyesno(
                "发现新版本",
                f"当前版本：v{APP_VERSION}\n最新版本：{latest_tag}\n\n是否打开下载页面？",
                parent=self.root,
            )
            if should_open:
                webbrowser.open(release_url)
        else:
            messagebox.showinfo("检查更新", f"当前已是最新版本（v{APP_VERSION}）。", parent=self.root)

    def update(self):
        self.update_display()
        self.root.after(1000, self.update)

    def maybe_notify(self, state, now):
        """Notify once when the widget enters a configured workday state."""
        current_date = now.date()
        if self.last_state_date != current_date:
            self.last_state_date = current_date
            self.last_state_kind = None

        previous_kind = self.last_state_kind
        current_kind = state.get("kind")
        self.last_state_kind = current_kind
        if previous_kind is None or previous_kind == current_kind:
            return

        notifications = self.config.get("notifications", {})
        if not bool(notifications.get("enabled", True)):
            return

        if current_kind == "lunch" and bool(notifications.get("lunch", True)):
            self.notify_user("午休提醒", "午休开始了，休息一下吧。", notifications)
        elif current_kind == "off_work" and bool(notifications.get("off_work", True)):
            self.notify_user("下班提醒", "下班时间到了，今天辛苦了。", notifications)

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
            "afternoon": self.config["style"]["accent"],
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
    if not acquire_single_instance():
        return
    try:
        CountdownWidget().run()
    except Exception as error:
        messagebox.showerror(APP_NAME, str(error))
        sys.exit(1)


if __name__ == "__main__":
    main()
