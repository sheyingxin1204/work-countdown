import json
import sys
from copy import deepcopy
from datetime import date, datetime, time, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import messagebox


APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"

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
        self.holiday_dates = {parse_date(value) for value in calendar["holiday_dates"]}
        self.workday_overrides = {parse_date(value) for value in calendar["workday_overrides"]}

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

        self.root = tk.Tk()
        self.root.title("Work Countdown")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", bool(self.config["window"]["always_on_top"]))
        self.root.attributes("-alpha", float(self.config["window"]["alpha"]))
        self.root.configure(bg=self.config["style"]["background"])

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
        self.menu.add_command(label="设置上下班时间", command=self.open_schedule_settings)
        self.menu.add_command(label="重新加载配置", command=self.reload_config)
        self.menu.add_command(label="退出", command=self.quit)

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
        max_x = max(0, self.root.winfo_screenwidth() - width)
        max_y = max(0, self.root.winfo_screenheight() - height)

        try:
            x = int(window.get("x"))
            y = int(window.get("y"))
        except (TypeError, ValueError):
            x = max_x // 2
            y = max_y // 6

        x = min(max(0, x), max_x)
        y = min(max(0, y), max_y)
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

    def open_schedule_settings(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("设置上下班时间")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.configure(bg=self.config["style"]["background"])
        dialog.grab_set()

        fields = (
            ("morning_start", "上午上班"),
            ("lunch_start", "午休开始"),
            ("afternoon_start", "下午上班"),
            ("off_work", "下午下班"),
        )
        values = {}
        for row, (key, label) in enumerate(fields):
            tk.Label(
                dialog,
                text=label,
                bg=self.config["style"]["background"],
                fg=self.config["style"]["foreground"],
                font=("Microsoft YaHei UI", 10),
            ).grid(row=row, column=0, padx=(18, 10), pady=8, sticky="w")
            value = tk.StringVar(value=self.config["schedule"][key])
            values[key] = value
            tk.Entry(dialog, textvariable=value, width=10, font=("Consolas", 11)).grid(
                row=row, column=1, padx=(0, 18), pady=8
            )

        tk.Label(
            dialog,
            text="请使用 24 小时制，例如 10:30",
            bg=self.config["style"]["background"],
            fg=self.config["style"]["muted"],
            font=("Microsoft YaHei UI", 9),
        ).grid(row=len(fields), column=0, columnspan=2, padx=18, pady=(4, 10), sticky="w")

        def save_schedule():
            schedule = {key: value.get().strip() for key, value in values.items()}
            try:
                candidate = deepcopy(self.config)
                candidate["schedule"] = schedule
                new_schedule = WorkSchedule(candidate)
            except ValueError as error:
                messagebox.showerror("时间设置无效", str(error), parent=dialog)
                return

            self.config["schedule"] = schedule
            self.schedule = new_schedule
            save_config(self.config)
            self.refresh_static_ranges()
            self.update_display()
            dialog.destroy()

        actions = tk.Frame(dialog, bg=self.config["style"]["background"])
        actions.grid(row=len(fields) + 1, column=0, columnspan=2, pady=(0, 16))
        tk.Button(actions, text="取消", command=dialog.destroy, width=9).pack(side="left", padx=5)
        tk.Button(actions, text="保存", command=save_schedule, width=9).pack(side="left", padx=5)
        dialog.bind("<Return>", lambda _event: save_schedule())
        dialog.bind("<Escape>", lambda _event: dialog.destroy())

    def reload_config(self):
        try:
            self.config = load_config()
            self.calendar = WorkCalendar(self.config)
            self.schedule = WorkSchedule(self.config)
            self.root.attributes("-alpha", float(self.config["window"]["alpha"]))
            self.root.attributes("-topmost", bool(self.config["window"]["always_on_top"]))
            self.refresh_static_ranges()
            self.place_window()
            self.update_display()
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
        self.save_position()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    try:
        CountdownWidget().run()
    except Exception as error:
        messagebox.showerror("Work Countdown", str(error))
        sys.exit(1)


if __name__ == "__main__":
    main()
