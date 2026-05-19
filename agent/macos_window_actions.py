"""macOS local window actions executed through Accessibility."""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class MacWindowRect:
    x: float
    y: float
    width: float
    height: float


class ActiveApplicationLike(Protocol):
    pid: int | None


def run_window_action(
    action: str,
    active_application: ActiveApplicationLike,
    application_services,
    ns_screen,
) -> bool:
    window = frontmost_window(active_application, application_services)
    if window is None:
        print("[typer] macOS window action skipped: no frontmost window")
        return False
    if is_fullscreen_window(window, application_services):
        if not exit_fullscreen_window(window, application_services):
            print("[typer] macOS window action skipped: full screen window cannot exit")
            return False
        regular = wait_for_regular_window(
            active_application,
            window,
            application_services,
        )
        if regular is None:
            print("[typer] macOS window action skipped: full screen exit did not finish")
            return False
        window, current = regular
    else:
        current = window_rect(window, application_services)
    if current is None:
        print("[typer] macOS window action skipped: cannot read window frame")
        return False
    screen = screen_for_window(current, ns_screen)
    if screen is None:
        print("[typer] macOS window action skipped: cannot find screen")
        return False
    target = target_window_rect(action, current, screen)
    if target is None:
        return False
    raise_window(window, application_services)
    return set_window_rect(window, target, application_services, current_rect=current)


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


def window_rect(window, application_services) -> MacWindowRect | None:
    try:
        err, position_value = application_services.AXUIElementCopyAttributeValue(
            window,
            "AXPosition",
            None,
        )
        if err != 0 or position_value is None:
            return None
        err, size_value = application_services.AXUIElementCopyAttributeValue(
            window,
            "AXSize",
            None,
        )
        if err != 0 or size_value is None:
            return None
        point = ax_value_get(position_value, application_services.kAXValueCGPointType, application_services)
        size = ax_value_get(size_value, application_services.kAXValueCGSizeType, application_services)
        if point is None or size is None:
            return None
        point_x, point_y = point_xy(point)
        size_width, size_height = size_wh(size)
        return MacWindowRect(
            float(point_x),
            float(point_y),
            float(size_width),
            float(size_height),
        )
    except Exception as e:
        print(f"[typer] macOS window frame read failed: {e}")
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


def exit_fullscreen_window(window, application_services) -> bool:
    try:
        value = False
        if hasattr(application_services, "kCFBooleanFalse"):
            value = application_services.kCFBooleanFalse
        err = application_services.AXUIElementSetAttributeValue(
            window,
            "AXFullScreen",
            value,
        )
        if err == 0:
            return True
        print(f"[typer] macOS full screen exit failed: err={_ax_error_name(int(err))}")
        return False
    except Exception as e:
        print(f"[typer] macOS full screen exit failed: {e}")
        return False


def wait_for_regular_window(
    active_application: ActiveApplicationLike,
    previous_window,
    application_services,
    *,
    timeout: float = 2.0,
    interval: float = 0.1,
) -> tuple[object, MacWindowRect] | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        window = frontmost_window(active_application, application_services)
        if window is None:
            time.sleep(interval)
            continue
        if is_fullscreen_window(window, application_services):
            time.sleep(interval)
            continue
        rect = window_rect(window, application_services)
        if rect is not None:
            return window, rect
        time.sleep(interval)
    if is_fullscreen_window(previous_window, application_services):
        return None
    rect = window_rect(previous_window, application_services)
    if rect is None:
        return None
    return previous_window, rect


def raise_window(window, application_services) -> bool:
    try:
        perform = getattr(application_services, "AXUIElementPerformAction", None)
        if perform is None:
            return False
        return int(perform(window, "AXRaise")) == 0
    except Exception:
        return False


def set_window_rect(
    window,
    rect: MacWindowRect,
    application_services,
    *,
    current_rect: MacWindowRect | None = None,
) -> bool:
    try:
        if current_rect is not None and (
            current_rect.width < rect.width or current_rect.height < rect.height
        ):
            return expand_window_rect_from_target_origin(
                window,
                rect,
                application_services,
            )
        return shrink_or_move_window_rect(window, rect, application_services)
    except Exception as e:
        print(f"[typer] macOS window frame set failed: {e}")
        return False


def expand_window_rect_from_target_origin(window, rect: MacWindowRect, application_services) -> bool:
    position_err = set_window_position(window, rect.x, rect.y, application_services)
    if position_err != 0:
        return False
    time.sleep(0.05)
    size_err = set_window_size(window, rect.width, rect.height, application_services)
    if size_err != 0:
        return False
    time.sleep(0.05)
    position_err = set_window_position(window, rect.x, rect.y, application_services)
    if position_err != 0:
        return False
    return verify_or_reapply_window_rect(window, rect, application_services)


def shrink_or_move_window_rect(window, rect: MacWindowRect, application_services) -> bool:
    size_err = set_window_size(window, rect.width, rect.height, application_services)
    if size_err != 0:
        fallback_position_err = set_window_position(window, rect.x, rect.y, application_services)
        if fallback_position_err != 0:
            print(
                "[typer] macOS window frame set failed: "
                f"size={_ax_error_name(size_err)} "
                f"fallback_position={_ax_error_name(fallback_position_err)}"
            )
            return False
    time.sleep(0.05)
    position_err = set_window_position(window, rect.x, rect.y, application_services)
    if position_err != 0:
        fallback_size_err = set_window_size(window, rect.width, rect.height, application_services)
        if fallback_size_err != 0:
            print(
                "[typer] macOS window frame set failed: "
                f"position={_ax_error_name(position_err)} "
                f"fallback_size={_ax_error_name(fallback_size_err)}"
            )
            return False
    return verify_or_reapply_window_rect(window, rect, application_services)


def verify_or_reapply_window_rect(
    window,
    rect: MacWindowRect,
    application_services,
) -> bool:
    time.sleep(0.05)
    current = window_rect(window, application_services)
    if rects_close(current, rect) or rect_satisfies_window_action(current, rect):
        return True
    size_err = set_window_size(window, rect.width, rect.height, application_services)
    if size_err != 0:
        print(
            "[typer] macOS window frame verification skipped after visible move: "
            f"size={_ax_error_name(size_err)}"
        )
        return False
    time.sleep(0.05)
    position_err = set_window_position(window, rect.x, rect.y, application_services)
    if position_err != 0:
        print(
            "[typer] macOS window frame verification skipped after visible move: "
            f"position={_ax_error_name(position_err)}"
        )
        return False
    time.sleep(0.05)
    current = window_rect(window, application_services)
    if current is not None and not rects_close(current, rect) and not rect_satisfies_window_action(current, rect):
        print(f"[typer] macOS window frame readback differs: target={rect} current={current}")
    return True


def rects_close(
    current: MacWindowRect | None,
    target: MacWindowRect,
    *,
    tolerance: float = 4.0,
) -> bool:
    if current is None:
        return False
    return (
        abs(current.x - target.x) <= tolerance
        and abs(current.y - target.y) <= tolerance
        and abs(current.width - target.width) <= tolerance
        and abs(current.height - target.height) <= tolerance
    )


def rect_satisfies_window_action(
    current: MacWindowRect | None,
    target: MacWindowRect,
    *,
    tolerance: float = 12.0,
) -> bool:
    if current is None:
        return False
    width_ok = current.width + tolerance >= target.width
    left_ok = abs(current.x - target.x) <= tolerance
    right_ok = abs((current.x + current.width) - (target.x + target.width)) <= tolerance
    vertical_overlap = min(
        current.y + current.height,
        target.y + target.height,
    ) - max(current.y, target.y)
    vertical_ok = vertical_overlap >= min(current.height, target.height) * 0.75
    return width_ok and (left_ok or right_ok) and vertical_ok


def set_window_size(window, width: float, height: float, application_services) -> int:
    value = application_services.AXValueCreate(
        application_services.kAXValueCGSizeType,
        application_services.CGSizeMake(width, height),
    )
    return int(application_services.AXUIElementSetAttributeValue(window, "AXSize", value))


def set_window_position(window, x: float, y: float, application_services) -> int:
    value = application_services.AXValueCreate(
        application_services.kAXValueCGPointType,
        application_services.CGPointMake(x, y),
    )
    return int(application_services.AXUIElementSetAttributeValue(window, "AXPosition", value))


def _ax_error_name(code: int) -> str:
    names = {
        0: "success",
        -25200: "kAXErrorFailure",
        -25201: "kAXErrorIllegalArgument",
        -25202: "kAXErrorInvalidUIElement",
        -25204: "kAXErrorCannotComplete",
        -25205: "kAXErrorAttributeUnsupported",
        -25211: "kAXErrorAPIDisabled",
        -25212: "kAXErrorNoValue",
    }
    return f"{names.get(code, 'kAXErrorUnknown')}({code})"


def screen_for_window(window: MacWindowRect, ns_screen) -> MacWindowRect | None:
    screens = visible_screens(ns_screen)
    if not screens:
        return None
    center_x = window.x + window.width / 2
    center_y = window.y + window.height / 2
    for screen in screens:
        if (
            screen.x <= center_x <= screen.x + screen.width
            and screen.y <= center_y <= screen.y + screen.height
        ):
            return screen
    return screens[0]


def visible_screens(ns_screen) -> list[MacWindowRect]:
    try:
        screens = ns_screen.screens() or []
    except Exception:
        screens = []
    reference_top = ax_reference_top(ns_screen, screens)
    out: list[MacWindowRect] = []
    for screen in screens:
        try:
            visible = screen.visibleFrame()
            ax_y = reference_top - float(visible.origin.y) - float(visible.size.height)
            out.append(MacWindowRect(
                float(visible.origin.x),
                ax_y,
                float(visible.size.width),
                float(visible.size.height),
            ))
        except Exception:
            continue
    return out


def ax_reference_top(ns_screen, screens) -> float:
    screen = primary_screen_for_ax_coordinates(screens)
    if screen is None:
        return 0.0
    frame = screen.frame()
    return float(frame.origin.y) + float(frame.size.height)


def primary_screen_for_ax_coordinates(screens):
    for screen in screens:
        try:
            frame = screen.frame()
            if float(frame.origin.x) == 0.0 and float(frame.origin.y) == 0.0:
                return screen
        except Exception:
            continue
    return screens[0] if screens else None


def target_window_rect(
    action: str,
    current: MacWindowRect,
    screen: MacWindowRect,
) -> MacWindowRect | None:
    if action == "left_half":
        return MacWindowRect(screen.x, screen.y, screen.width / 2, screen.height)
    if action == "right_half":
        return MacWindowRect(
            screen.x + screen.width / 2,
            screen.y,
            screen.width / 2,
            screen.height,
        )
    if action == "maximize":
        return MacWindowRect(screen.x, screen.y, screen.width, screen.height)
    if action == "center":
        width = min(max(current.width, 480), screen.width)
        height = min(max(current.height, 320), screen.height)
        return MacWindowRect(
            screen.x + (screen.width - width) / 2,
            screen.y + (screen.height - height) / 2,
            width,
            height,
        )
    return None


def ax_value_get(value, value_type, application_services):
    result = application_services.AXValueGetValue(value, value_type, None)
    if isinstance(result, tuple):
        if len(result) < 2:
            return None
        ok, out = result[0], result[1]
        return out if ok else None
    return None


def point_xy(point) -> tuple[float, float]:
    if hasattr(point, "x") and hasattr(point, "y"):
        return float(point.x), float(point.y)
    if isinstance(point, (tuple, list)) and len(point) >= 2:
        return float(point[0]), float(point[1])
    raise ValueError(f"unexpected CGPoint value {point!r}")


def size_wh(size) -> tuple[float, float]:
    if hasattr(size, "width") and hasattr(size, "height"):
        return float(size.width), float(size.height)
    if isinstance(size, (tuple, list)) and len(size) >= 2:
        return float(size[0]), float(size[1])
    raise ValueError(f"unexpected CGSize value {size!r}")
