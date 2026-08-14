"""Small Windows global-hotkey listener used by the desktop widget."""

from __future__ import annotations

import ctypes
import os
import threading
from ctypes import wintypes
from typing import Callable


class GlobalHotkeyListener:
    """Register Ctrl+Shift+B/S without blocking Tk's main loop."""

    _WM_HOTKEY = 0x0312
    _WM_QUIT = 0x0012
    _MOD_CONTROL = 0x0002
    _MOD_SHIFT = 0x0004
    _HOTKEYS = {1: ord("B"), 2: ord("S")}

    def __init__(self, callback: Callable[[int], None]) -> None:
        self.callback = callback
        self.thread: threading.Thread | None = None
        self.thread_id: int | None = None
        self.stop_event = threading.Event()
        self.ready_event = threading.Event()
        self.registered_ids: tuple[int, ...] = ()

    @property
    def supported(self) -> bool:
        return os.name == "nt"

    def start(self) -> bool:
        if not self.supported or (self.thread is not None and self.thread.is_alive()):
            return False
        self.stop_event.clear()
        self.ready_event.clear()
        self.registered_ids = ()
        self.thread = threading.Thread(target=self._run, name="BanClockHotkeys", daemon=True)
        self.thread.start()
        self.ready_event.wait(timeout=0.25)
        return bool(self.registered_ids)

    def _run(self) -> None:
        if not self.supported:
            return
        user32 = ctypes.windll.user32
        self.thread_id = threading.get_native_id()
        registered: list[int] = []
        modifiers = self._MOD_CONTROL | self._MOD_SHIFT
        for hotkey_id, virtual_key in self._HOTKEYS.items():
            if user32.RegisterHotKey(None, hotkey_id, modifiers, virtual_key):
                registered.append(hotkey_id)
        self.registered_ids = tuple(registered)
        self.ready_event.set()

        try:
            if not registered:
                return
            message = wintypes.MSG()
            while not self.stop_event.is_set():
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result <= 0:
                    break
                if message.message == self._WM_HOTKEY:
                    try:
                        self.callback(int(message.wParam))
                    except Exception:
                        # The UI callback is best-effort; a callback failure
                        # must not kill the listener thread or the app.
                        pass
        finally:
            for hotkey_id in registered:
                user32.UnregisterHotKey(None, hotkey_id)

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread_id is not None and self.supported:
            try:
                ctypes.windll.user32.PostThreadMessageW(self.thread_id, self._WM_QUIT, 0, 0)
            except (AttributeError, OSError):
                pass
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=1.5)
        self.thread = None
        self.thread_id = None
        self.registered_ids = ()
