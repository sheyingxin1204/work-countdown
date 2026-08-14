import json
import ctypes
import os
import sys
import threading
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


if getattr(sys, "frozen", False):
    # Keep user configuration beside the packaged EXE instead of inside the
    # temporary extraction directory used by one-file PyInstaller builds.
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
APP_NAME = "班时钟"
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
    with CONFIG_PATH.open("w", encoding="utf-8") as config_file:
        json.dump(config, config_file, ensure_ascii=False, indent=2)


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

    def state(self, now, calendar):
        today = now.date()

        if not calendar.is_workday(today):
            next_day = calendar.next_workday(today + timedelta(days=1))
            return {
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
                "status": "未上班",
                "countdown_name": "距离上班",
                "countdown_at": morning_start,
            }
        if now < lunch_start:
            return {
                "status": "上午上班",
                "countdown_name": "距离午休",
                "countdown_at": lunch_start,
            }
        if now < afternoon_start:
            return {
                "status": "午休中",
                "countdown_name": "下午上班",
                "countdown_at": afternoon_start,
            }
        if now < off_work:
            return {
                "status": "下午上班",
                "countdown_name": "距离下班",
                "countdown_at": off_work,
            }

        next_day = calendar.next_workday(today + timedelta(days=1))
        return {
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

        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", bool(self.config["window"]["always_on_top"]))
        self.root.attributes("-alpha", float(self.config["window"]["alpha"]))
        self.root.configure(bg=self.config["style"]["background"])
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)

        self.frame = tk.Frame(
            self.root,
            bg=self.config["style"]["background"],
            padx=18,
            pady=14,
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

        self.status_label.grid(row=1, column=0, sticky="w", pady=3)
        self.status_value.grid(row=1, column=1, sticky="e", padx=(18, 0), pady=3)
        self.countdown_label.grid(row=2, column=0, sticky="w", pady=3)
        self.countdown_value.grid(row=2, column=1, sticky="e", padx=(18, 0), pady=3)
        self.morning_label.grid(row=3, column=0, sticky="w", pady=(12, 3))
        self.morning_value.grid(row=3, column=1, sticky="e", padx=(18, 0), pady=(12, 3))
        self.afternoon_label.grid(row=4, column=0, sticky="w", pady=3)
        self.afternoon_value.grid(row=4, column=1, sticky="e", padx=(18, 0), pady=3)
        self.clock_label.grid(row=5, column=0, columnspan=2, sticky="e", pady=(8, 0))

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="打开设置中心", command=self.open_schedule_settings)
        self.menu.add_command(label="重新加载配置", command=self.reload_config)
        self.menu.add_separator()
        self.menu.add_command(label="隐藏到系统托盘", command=self.hide_window)
        self.menu.add_command(label="退出班时钟", command=self.quit)

        for widget in (
            self.root,
            self.frame,
            self.title_label,
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
        dialog.title(f"{APP_NAME} · 设置中心")
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
        self.place_window()
        self.update_display()

    def reload_config(self):
        try:
            self.apply_config(load_config())
        except (KeyError, TypeError, ValueError) as error:
            messagebox.showerror("配置无效", str(error), parent=self.root)

    def update(self):
        self.update_display()
        self.root.after(1000, self.update)

    def update_display(self):
        now = datetime.now()
        state = self.schedule.state(now, self.calendar)

        self.status_value.configure(text=state["status"])
        self.countdown_label.configure(text=state["countdown_name"])
        self.countdown_value.configure(text=format_remaining(state["countdown_at"] - now))
        self.clock_label.configure(text=now.strftime("%Y-%m-%d %H:%M:%S"))

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
