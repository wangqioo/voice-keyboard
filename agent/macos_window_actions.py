"""macOS local window actions executed through keyboard shortcuts."""

from __future__ import annotations

import time
from typing import Protocol


WINDOW_ACTIONS = {
    "窗口左半屏": "left_half",
    "窗口右半屏": "right_half",
    "窗口左移": "left_half",
    "窗口右移": "right_half",
    "窗口最大化": "maximize",
    "窗口居中": "center",
}

DEFAULT_WINDOW_ACTION_SHORTCUTS = {
    "left_half": "ctrl+option+left",
    "right_half": "ctrl+option+right",
    "maximize": "ctrl+option+enter",
    "center": "ctrl+option+c",
}

FULLSCREEN_TOGGLE_SHORTCUT = "ctrl+cmd+f"


class ActiveApplicationLike(Protocol):
    pid: int | None


def run_window_action(
    action: str,
    active_application: ActiveApplicationLike,
    application_services,
    press_shortcut,
    window_action_shortcuts: dict[str, list],
    fullscreen_toggle_shortcut: list,
    *,
    fullscreen_exit_delay: float = 0.8,
    sleep=None,
) -> bool:
    keys = window_action_shortcuts.get(action)
    if not keys:
        print(f"[typer] macOS window action skipped: no shortcut for {action}")
        return False
    window = frontmost_window(active_application, application_services)
    if window is not None and is_fullscreen_window(window, application_services):
        press_shortcut(fullscreen_toggle_shortcut)
        if sleep is not None:
            sleep(fullscreen_exit_delay)
    press_shortcut(keys)
    return True


def frontmost_window(active_application: ActiveApplicationLike, application_services):
    if not active_application.pid:
        return None
    try:
        ax_app = application_services.AXUIElementCreateApplication(active_application.pid)
        err, window = application_services.AXUIElementCopyAttributeValue(
            ax_app,
            "AXFocusedWindow",
            None,
        )
        if err == 0 and window is not None:
            return window
        err, windows = application_services.AXUIElementCopyAttributeValue(
            ax_app,
            "AXWindows",
            None,
        )
        if err == 0 and windows:
            return list(windows)[0]
    except Exception as e:
        print(f"[typer] macOS focused window lookup failed: {e}")
    return None


def is_fullscreen_window(window, application_services) -> bool:
    try:
        err, value = application_services.AXUIElementCopyAttributeValue(
            window,
            "AXFullScreen",
            None,
        )
        return err == 0 and bool(value)
    except Exception:
        return False
