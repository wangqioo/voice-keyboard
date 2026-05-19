import platform
import subprocess
import time
from dataclasses import dataclass
from pynput.keyboard import Controller, Key, KeyCode

from agent import app_launcher
from agent import macos_window_actions
from agent.app_shortcut_presets import MACOS_APP_SHORTCUT_PRESETS
from agent.local_operation_catalog import (
    LocalOperationCandidate,
    ShortcutCatalogEntry,
    ShortcutPolicyDecision,
    build_shortcut_catalog,
    shortcut_policy_for_invocation as _catalog_policy_for_invocation,
)

_kb = Controller()
_OS = platform.system()

if _OS == "Darwin":
    import Quartz
    import ApplicationServices
    from AppKit import NSPasteboard, NSPasteboardTypeString, NSScreen, NSWorkspace

if _OS == "Windows":
    import ctypes
    import ctypes.wintypes

    _KEYEVENTF_UNICODE = 0x0004
    _KEYEVENTF_KEYUP   = 0x0002
    _INPUT_KEYBOARD    = 1

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk",         ctypes.wintypes.WORD),
            ("wScan",       ctypes.wintypes.WORD),
            ("dwFlags",     ctypes.wintypes.DWORD),
            ("time",        ctypes.wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class _INPUT(ctypes.Structure):
        _fields_ = [
            ("type",    ctypes.wintypes.DWORD),
            ("ki",      _KEYBDINPUT),
            ("padding", ctypes.c_ubyte * 8),
        ]

    _user32   = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32
    _kernel32.GlobalAlloc.restype    = ctypes.c_void_p
    _kernel32.GlobalAlloc.argtypes   = [ctypes.c_uint, ctypes.c_size_t]
    _kernel32.GlobalLock.restype     = ctypes.c_void_p
    _kernel32.GlobalLock.argtypes    = [ctypes.c_void_p]
    _kernel32.GlobalUnlock.restype   = ctypes.c_bool
    _kernel32.GlobalUnlock.argtypes  = [ctypes.c_void_p]
    _user32.SetClipboardData.restype  = ctypes.c_void_p
    _user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    _user32.GetClipboardData.restype  = ctypes.c_void_p
    _user32.GetClipboardData.argtypes = [ctypes.c_uint]

# ── erase_last 的「正在擦除」标志 ─────────────────────────────────
# keyboard_monitor 通过 is_erasing() 判断当前退格是否由我们发出，
# 避免双重扣减 TextBuffer。
# CPython GIL 保证单字节赋值是原子的，线程安全。

_erasing: bool = False
_simulating: bool = False   # 程序自己发 Cmd+C/V 等按键时置 True，让 PTT 监听忽略
_use_clipboard_mode: bool = False
_last_focus_fallback_log: tuple[str, int | None] | None = None
_BLOCKED_SHORTCUT_NAMES: set[str] = set()
_BLOCKED_SHORTCUT_KEY_SEQUENCES: set[tuple[str, ...]] = set()
_MACOS_WINDOW_ACTION_SHORTCUTS: dict[str, list] = {}
_MACOS_FULLSCREEN_TOGGLE_SHORTCUT: list = []


@dataclass(frozen=True)
class ActiveApplication:
    name: str = ""
    bundle_id: str = ""
    pid: int | None = None

    @property
    def label(self) -> str:
        if self.name and self.bundle_id:
            return f"{self.name} ({self.bundle_id})"
        return self.name or self.bundle_id or "未知活动应用"


ApplicationLaunchSpec = app_launcher.ApplicationLaunchSpec


def init(cfg: dict) -> None:
    """由 main.py 在启动时调用，根据 config.yaml 的 typing.method 配置打字方式。"""
    global _use_clipboard_mode
    _use_clipboard_mode = cfg.get("method", "unicode") == "clip"
    if _use_clipboard_mode:
        print("[typer] 剪贴板粘贴模式（适合微信等应用）")
    _load_blocked_shortcuts(cfg)
    _load_custom_shortcuts(cfg.get("shortcuts", {}))
    _APP_SHORTCUTS.clear()
    _load_app_shortcuts(_configured_app_shortcuts(cfg))
    app_launcher.load_app_launches(cfg.get("app_launches", {}))
    _load_macos_window_action_shortcuts(cfg)


def is_erasing() -> bool:
    """供 keyboard_monitor 检查：当前退格事件是否由 erase_last 发出。"""
    return _erasing

def is_simulating() -> bool:
    """供 push_to_talk 检查：当前按键事件是否由程序自身发出（如 Cmd+C）。"""
    return _simulating


# 语音指令 → 快捷键映射
_SHORTCUTS: dict[str, list] = {
    "保存":    [Key.cmd, KeyCode.from_char("s")],
    "复制":    [Key.cmd, KeyCode.from_char("c")],
    "粘贴":    [Key.cmd, KeyCode.from_char("v")],
    "撤销":    [Key.cmd, KeyCode.from_char("z")],
    "重做":    [Key.cmd, Key.shift, KeyCode.from_char("z")],
    "全选":    [Key.cmd, KeyCode.from_char("a")],
    "加粗":    [Key.cmd, KeyCode.from_char("b")],
    "斜体":    [Key.cmd, KeyCode.from_char("i")],
    "下划线":  [Key.cmd, KeyCode.from_char("u")],
    "查找":    [Key.cmd, KeyCode.from_char("f")],
    "回车":    [Key.enter],
    "删除":    [Key.backspace],
    "空格":    [Key.space],
}
_SYSTEM_ACTIONS = {
    "打开系统设置": "open_system_settings",
    "系统设置": "open_system_settings",
}
_MACOS_APP_SHORTCUT_PRESETS = MACOS_APP_SHORTCUT_PRESETS
_APP_SHORTCUTS: dict[str, dict[str, list]] = {}
_HIGH_RISK_SHORTCUT_NAMES = {
    "发送",
    "提交",
    "删除",
    "关闭标签",
}

# Windows / Linux 下替换修饰键（两者快捷键基本相同）
if _OS in ("Windows", "Linux"):
    _SHORTCUTS["复制"]    = [Key.ctrl, KeyCode.from_char("c")]
    _SHORTCUTS["粘贴"]    = [Key.ctrl, KeyCode.from_char("v")]
    _SHORTCUTS["保存"]    = [Key.ctrl, KeyCode.from_char("s")]
    _SHORTCUTS["撤销"]    = [Key.ctrl, KeyCode.from_char("z")]
    _SHORTCUTS["重做"]    = [Key.ctrl, Key.shift, KeyCode.from_char("z")]
    _SHORTCUTS["全选"]    = [Key.ctrl, KeyCode.from_char("a")]
    _SHORTCUTS["加粗"]    = [Key.ctrl, KeyCode.from_char("b")]
    _SHORTCUTS["斜体"]    = [Key.ctrl, KeyCode.from_char("i")]
    _SHORTCUTS["下划线"]  = [Key.ctrl, KeyCode.from_char("u")]
    _SHORTCUTS["查找"]    = [Key.ctrl, KeyCode.from_char("f")]


# ── 打字 ──────────────────────────────────────────────────────────

def type_text(text: str) -> None:
    """在当前焦点输入框打出任意 Unicode 文字（含汉字）"""
    if not text:
        return
    if _OS == "Darwin":
        if _use_clipboard_mode:
            replace_selection(text)
        else:
            _type_via_quartz(text)
    elif _OS == "Windows":
        if _use_clipboard_mode:
            _type_via_clipboard_win(text)
        else:
            _type_via_sendinput(text)
    else:
        _type_via_xtest(text)  # Linux


def has_focused_text_input() -> bool:
    """Best-effort focus check before emitting text."""
    global _last_focus_fallback_log
    if _OS != "Darwin":
        return True
    try:
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        pid = app.processIdentifier() if app is not None else None
        if not pid:
            print("[typer] focus check: no frontmost app")
            return False
        app_name = str(app.localizedName() or "")
        bundle_id = str(app.bundleIdentifier() or "")
        elem = ApplicationServices.AXUIElementCreateApplication(pid)
        err, focused = ApplicationServices.AXUIElementCopyAttributeValue(elem, "AXFocusedUIElement", None)
        if err != 0 or focused is None:
            if not _use_clipboard_mode and _allows_typing_without_focused_element(bundle_id, app_name):
                key = (bundle_id or app_name, pid)
                if key != _last_focus_fallback_log:
                    print(
                        f"[typer] focus check: {app_name} no focused element err={err}, "
                        "allowed by app fallback"
                    )
                    _last_focus_fallback_log = key
                return True
            _last_focus_fallback_log = None
            print(f"[typer] focus check: {app_name} no focused element err={err}")
            return False
        err, role = ApplicationServices.AXUIElementCopyAttributeValue(focused, "AXRole", None)
        if err != 0:
            print(f"[typer] focus check: {app_name} no role err={err}")
            return False
        role_name = str(role)
        subrole = _ax_string(focused, "AXSubrole")
        description = _ax_string(focused, "AXDescription")
        settable_value = _ax_settable(focused, "AXValue")
        settable_range = _ax_settable(focused, "AXSelectedTextRange")
        ok = (
            role_name in {"AXTextField", "AXTextArea", "AXTextView", "AXComboBox"}
            and (settable_value or settable_range)
            and not _looks_like_browser_document(bundle_id, role_name, subrole, description)
        )
        print(
            "[typer] focus check: "
            f"app={app_name!r} bundle={bundle_id!r} role={role_name!r} "
            f"subrole={subrole!r} desc={description!r} "
            f"value_settable={settable_value} range_settable={settable_range} ok={ok}"
        )
        _last_focus_fallback_log = None
        return ok
    except Exception as e:
        _last_focus_fallback_log = None
        print(f"[typer] focus check failed: {e}")
        return False


def _ax_string(element, attr: str) -> str:
    try:
        err, value = ApplicationServices.AXUIElementCopyAttributeValue(element, attr, None)
        return str(value) if err == 0 and value is not None else ""
    except Exception:
        return ""


def _ax_settable(element, attr: str) -> bool:
    try:
        err, value = ApplicationServices.AXUIElementIsAttributeSettable(element, attr, None)
        return err == 0 and bool(value)
    except Exception:
        return False


def _focused_accessibility_element():
    if _OS != "Darwin":
        return None
    try:
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        pid = app.processIdentifier() if app is not None else None
        if not pid:
            return None
        root = ApplicationServices.AXUIElementCreateApplication(pid)
        err, focused = ApplicationServices.AXUIElementCopyAttributeValue(root, "AXFocusedUIElement", None)
        return focused if err == 0 else None
    except Exception:
        return None


def _frontmost_app_identity() -> tuple[str, str, int | None]:
    if _OS != "Darwin":
        return "", "", None
    try:
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return "", "", None
        return (
            str(app.localizedName() or ""),
            str(app.bundleIdentifier() or ""),
            app.processIdentifier(),
        )
    except Exception:
        return "", "", None


def current_application() -> ActiveApplication:
    name, bundle_id, pid = _frontmost_app_identity()
    return ActiveApplication(name=name, bundle_id=bundle_id, pid=pid)


def _frontmost_app_is_codex() -> bool:
    app_name, bundle_id, _pid = _frontmost_app_identity()
    identity = f"{app_name} {bundle_id}".lower()
    return "codex" in identity


def _get_accessibility_selection() -> str:
    focused = _focused_accessibility_element()
    if focused is None:
        return ""
    for attr in ("AXSelectedText", "AXSelectedTextRanges"):
        try:
            err, value = ApplicationServices.AXUIElementCopyAttributeValue(focused, attr, None)
        except Exception:
            continue
        if err == 0 and value is not None:
            text = str(value)
            if text and not text.startswith("("):
                return text
    return ""


def _looks_like_browser_document(bundle_id: str, role: str, subrole: str, description: str) -> bool:
    browser_bundles = {
        "com.google.Chrome",
        "com.google.Chrome.canary",
        "com.microsoft.edgemac",
        "com.apple.Safari",
        "org.mozilla.firefox",
    }
    if bundle_id not in browser_bundles:
        return False
    text = " ".join([role, subrole, description]).lower()
    return any(marker in text for marker in ("web", "html", "document", "网页", "内容"))


def _allows_typing_without_focused_element(bundle_id: str, app_name: str) -> bool:
    bundle = bundle_id.lower()
    name = app_name.lower()
    # Only a tiny set of developer input environments are safe enough to accept
    # typed events when macOS Accessibility cannot prove a focused text element.
    # Every other app should use the explicit clipboard-copy fallback instead of
    # risking a silent "typed successfully" result with no text inserted.
    allow_markers = (
        "vscode", "cursor", "trae", "codex",
    )
    if any(marker in bundle or marker in name for marker in allow_markers):
        return True
    return False


def confirm_paste_without_focused_input(text: str) -> bool:
    preview = (text or "").replace("\n", " ")[:80]
    try:
        copy_to_clipboard(text)
        print(f"[typer] 未点击到输入框，已复制到剪贴板: {preview}")
        return True
    except Exception as e:
        print(f"[typer] 未点击到输入框，复制失败: {e}: {preview}")
        return False


def paste_text(text: str) -> None:
    replace_selection(text)


def copy_to_clipboard(text: str) -> None:
    _set_clipboard(str(text or ""))


def _osascript_quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _type_via_quartz(text: str) -> None:
    # macOS：CGEvent 逐字发送 Unicode，绕过 IME
    src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
    for char in text:
        for key_down in (True, False):
            evt = Quartz.CGEventCreateKeyboardEvent(src, 0, key_down)
            Quartz.CGEventKeyboardSetUnicodeString(evt, len(char), char)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, evt)
        time.sleep(0.012)


def _type_via_sendinput(text: str) -> None:
    # Windows：SendInput + KEYEVENTF_UNICODE 逐字发送，绕过 IME
    for char in text:
        code = ord(char)
        # BMP 以外的字符（emoji 等）拆成 UTF-16 代理对
        if code > 0xFFFF:
            code -= 0x10000
            scans = [0xD800 + (code >> 10), 0xDC00 + (code & 0x3FF)]
        else:
            scans = [code]

        for scan in scans:
            for flags in [_KEYEVENTF_UNICODE, _KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP]:
                inp = _INPUT(
                    type=_INPUT_KEYBOARD,
                    ki=_KEYBDINPUT(wVk=0, wScan=scan, dwFlags=flags),
                )
                _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))
        time.sleep(0.012)


def _type_via_clipboard_win(text: str) -> None:
    # Windows 剪贴板粘贴模式：适合微信等拦截 SendInput 的应用
    _set_clipboard_win(text)
    time.sleep(0.03)
    _kb.press(Key.ctrl)
    try:
        _press_key(KeyCode.from_char("v"))
    finally:
        _kb.release(Key.ctrl)
    time.sleep(0.03)


def _type_via_xtest(text: str) -> None:
    # Linux：pynput 逐字，底层走 X11 XTest，绕过 IME
    for char in text:
        _kb.type(char)
        time.sleep(0.012)


# ── 退格擦除 ──────────────────────────────────────────────────────

def erase_last(text: str) -> None:
    """发送退格键擦掉最近打出的文字（按 Unicode 字符数计）。"""
    global _erasing
    n = len(text)
    if n == 0:
        return
    _erasing = True
    try:
        if _OS == "Darwin":
            _erase_via_quartz(n)
        elif _OS == "Windows":
            _erase_via_sendinput(n)
        else:
            _erase_via_pynput(n)
    finally:
        _erasing = False


def _erase_via_quartz(n: int) -> None:
    src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
    for _ in range(n):
        for key_down in (True, False):
            evt = Quartz.CGEventCreateKeyboardEvent(src, 51, key_down)  # 51 = Backspace
            Quartz.CGEventSetFlags(evt, 0)  # 清空修饰键，防止 Command 按住时变成 Cmd+Backspace
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, evt)
        time.sleep(0.005)


def _erase_via_sendinput(n: int) -> None:
    VK_BACK = 0x08
    for _ in range(n):
        for flags in [0, _KEYEVENTF_KEYUP]:
            inp = _INPUT(
                type=_INPUT_KEYBOARD,
                ki=_KEYBDINPUT(wVk=VK_BACK, wScan=0, dwFlags=flags),
            )
            _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))
        time.sleep(0.005)


def _erase_via_pynput(n: int) -> None:
    for _ in range(n):
        _kb.press(Key.backspace)
        _kb.release(Key.backspace)
        time.sleep(0.005)


# ── 行选择模式（供语音编辑的剪贴板方案）─────────────────────────
#
# 鼠标点击后光标位置不可靠，语音编辑切换到此模式：
#   1. Home → 光标跳到行首
#   2. Shift+End → 选中整行
#   3. Ctrl+C / Cmd+C → 复制
#   4. 读剪贴板 → 拿到真实当前行内容作为 original
#   5. LLM 修改后：Home → Shift+End → 打新文字（替换选中内容）

def get_current_line() -> str | None:
    """
    通过 Home→Shift+End→复制 读取当前行真实内容。
    完成后恢复原剪贴板内容。
    返回 None 表示获取失败（调用方应回退到 buf.last）。
    """
    try:
        old_clip = _get_clipboard()

        # 1. 跳到行首
        _press_key(Key.home)
        time.sleep(0.05)
        # 2. Shift+End 选中当前行（try/finally 防止 Shift 卡住）
        _kb.press(Key.shift)
        try:
            _press_key(Key.end)
        finally:
            _kb.release(Key.shift)
        time.sleep(0.05)
        # 3. 复制
        _copy_selection()
        time.sleep(0.12)

        line = _get_clipboard()
        # 恢复原剪贴板
        _set_clipboard(old_clip)

        return line if line else None
    except Exception as e:
        print(f"[typer] get_current_line 失败: {e}")
        return None


_SENTINEL = "__VOICE_KEYBOARD_NO_SELECTION_SENTINEL__"


@dataclass(frozen=True)
class CaretTextWindow:
    text: str
    source: str


def get_selection() -> str:
    """
    读取当前鼠标选中的文字。
    原理：剪贴板写 sentinel → Cmd+C → 读剪贴板 → 恢复原剪贴板。
    若读到 sentinel（说明 Cmd+C 没改写剪贴板）则没有选中。
    用 sentinel 而非 old_clip 比较，避免选中内容和剪贴板原内容相同时误判为空。
    """
    try:
        ax_selected = _get_accessibility_selection()
        if ax_selected:
            print(f"[typer] AX selection: {ax_selected[:40]!r}")
            return ax_selected
        old_clip = _get_clipboard()
        _set_clipboard(_SENTINEL)
        time.sleep(0.05)
        _copy_selection()
        time.sleep(0.12)
        selected = _get_clipboard()
        # 恢复原剪贴板
        try:
            _set_clipboard(old_clip)
        except Exception:
            pass
        if selected and selected != _SENTINEL:
            return selected
        return ""
    except Exception as e:
        print(f"[typer] get_selection 失败: {e}")
        return ""


def get_caret_text_window(max_chars: int = 600) -> CaretTextWindow | None:
    """Return a small AX text window around the caret when the platform exposes it."""
    if _OS != "Darwin":
        return None
    focused = _focused_accessibility_element()
    if focused is None:
        return None
    try:
        err, value = ApplicationServices.AXUIElementCopyAttributeValue(
            focused,
            "AXValue",
            None,
        )
        if err != 0 or value is None:
            return None
        text = str(value)
        selected_range = _get_accessibility_selected_range(focused)
        if selected_range is None:
            return None
        caret = selected_range[0]
        if selected_range[1] > 0:
            caret = selected_range[0] + selected_range[1]
        caret = max(0, min(caret, len(text)))
        return _slice_caret_text_window(text, caret, max_chars=max_chars)
    except Exception as e:
        print(f"[typer] get_caret_text_window 失败: {e}")
        return None


_SENTENCE_BOUNDARIES = frozenset("。！？!?…\n")
_PARAGRAPH_BOUNDARIES = frozenset("\n\r")


def _slice_caret_text_window(
    text: str,
    caret: int,
    max_chars: int = 600,
) -> CaretTextWindow | None:
    if not text:
        return None
    if len(text) <= max_chars:
        return CaretTextWindow(text.strip(), "text_field")
    sentence = _slice_around_caret(text, caret, _SENTENCE_BOUNDARIES)
    if sentence:
        return CaretTextWindow(_limit_window(sentence, max_chars), "caret_sentence")
    paragraph = _slice_around_caret(text, caret, _PARAGRAPH_BOUNDARIES)
    if paragraph:
        return CaretTextWindow(_limit_window(paragraph, max_chars), "caret_paragraph")
    start = max(0, caret - max_chars // 2)
    end = min(len(text), start + max_chars)
    return CaretTextWindow(text[start:end].strip(), "caret_neighborhood")


def _slice_around_caret(text: str, caret: int, boundaries: frozenset[str]) -> str:
    left = caret
    while left > 0 and text[left - 1] not in boundaries:
        left -= 1
    right = caret
    while right < len(text) and text[right] not in boundaries:
        right += 1
    if right < len(text) and text[right] in _SENTENCE_BOUNDARIES:
        right += 1
    return text[left:right].strip()


def _limit_window(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].strip()


def _get_accessibility_selected_range(element):
    try:
        err, value = ApplicationServices.AXUIElementCopyAttributeValue(
            element,
            "AXSelectedTextRange",
            None,
        )
        if err != 0 or value is None:
            return None
        cf_range = _ax_value_get(value, ApplicationServices.kAXValueCFRangeType)
        if cf_range is None:
            return None
        if hasattr(cf_range, "location") and hasattr(cf_range, "length"):
            return int(cf_range.location), int(cf_range.length)
        if isinstance(cf_range, (tuple, list)) and len(cf_range) >= 2:
            return int(cf_range[0]), int(cf_range[1])
        return None
    except Exception:
        return None


def _ax_value_get(value, value_type):
    """Read AXValue outputs through PyObjC's out-parameter bridge."""
    result = ApplicationServices.AXValueGetValue(value, value_type, None)
    if isinstance(result, tuple):
        if len(result) < 2:
            return None
        ok, out = result[0], result[1]
        return out if ok else None
    return None


def _set_accessibility_selected_range(element, location: int, length: int = 0) -> bool:
    try:
        cf_range = ApplicationServices.CFRangeMake(location, length)
        value = ApplicationServices.AXValueCreate(
            ApplicationServices.kAXValueCFRangeType,
            cf_range,
        )
        err = ApplicationServices.AXUIElementSetAttributeValue(
            element,
            "AXSelectedTextRange",
            value,
        )
        return err == 0
    except Exception:
        return False


def _replace_accessibility_selection(
    text: str,
    original: str = "",
    require_original_at_caret: bool = False,
) -> bool:
    """Replace the current AX text target before falling back to paste/delete.

    Some rich input environments expose Explicit Selection through
    Accessibility but lose the OS selection before paste/delete events arrive.
    When AXValue is settable, editing it directly keeps Instruction Mode
    replacement/removal tied to the captured Explicit Selection.
    """
    if _OS != "Darwin":
        return False
    focused = _focused_accessibility_element()
    if focused is None:
        print("[typer] AX replacement skipped: no focused element")
        return False
    try:
        err, value = ApplicationServices.AXUIElementCopyAttributeValue(
            focused,
            "AXValue",
            None,
        )
        if err != 0 or value is None:
            print(f"[typer] AX replacement skipped: AXValue err={err} value={value is not None}")
            return False
        current = str(value)
        selected_range = _get_accessibility_selected_range(focused)
        if selected_range is not None:
            location, length = selected_range
            if location < 0 or length < 0 or location > len(current):
                print(
                    "[typer] AX replacement skipped: invalid range "
                    f"location={location} length={length} current_len={len(current)}"
                )
                return False
            if length == 0 and original:
                location = _find_original_location(
                    current,
                    original,
                    location,
                    allow_fallback=not require_original_at_caret,
                )
                if location < 0:
                    print("[typer] AX replacement skipped: original not found from caret")
                    return False
                length = len(original)
        elif original:
            if require_original_at_caret:
                print("[typer] AX replacement skipped: no caret range for text window")
                return False
            location = current.rfind(original)
            if location < 0:
                print("[typer] AX replacement skipped: no range and original not found")
                return False
            length = len(original)
        else:
            print("[typer] AX replacement skipped: no range and no original")
            return False
        end = min(len(current), location + length)
        updated = current[:location] + text + current[end:]
        err = ApplicationServices.AXUIElementSetAttributeValue(focused, "AXValue", updated)
        if err != 0:
            if _set_accessibility_selected_range(focused, location, length):
                print(f"[typer] AX value set failed err={err}; restored selection for paste")
                return False
            print(f"[typer] AX replacement skipped: set AXValue err={err}")
            return False
        _set_accessibility_selected_range(focused, location + len(text), 0)
        print("[typer] AX replacement applied")
        return True
    except Exception as e:
        print(f"[typer] AX replacement failed: {e}")
        return False


def _find_original_location(
    current: str,
    original: str,
    caret: int,
    allow_fallback: bool = True,
) -> int:
    if not original:
        return -1
    caret = max(0, min(caret, len(current)))
    if not allow_fallback:
        location = current.find(original)
        while location >= 0:
            end = location + len(original)
            if location <= caret <= end:
                return location
            location = current.find(original, location + 1)
        return -1
    start = caret - len(original)
    if start >= 0 and current[start:caret] == original:
        return start
    if current[caret:caret + len(original)] == original:
        return caret
    return current.rfind(original)


def replace_selection(text: str, original: str = "") -> None:
    """将 text 写入剪贴板并粘贴，替换当前选中内容（选区失效时在光标处插入）。"""
    if _replace_accessibility_selection(text, original=original):
        return
    global _simulating
    _set_clipboard(text)
    time.sleep(0.03)
    _simulating = True
    try:
        if _OS == "Darwin":
            _kb.press(Key.cmd)
            try:
                _press_key(KeyCode.from_char("v"))
            finally:
                _kb.release(Key.cmd)
        else:
            _kb.press(Key.ctrl)
            try:
                _press_key(KeyCode.from_char("v"))
            finally:
                _kb.release(Key.ctrl)
        time.sleep(0.05)  # 等 pynput 监听线程处理完这批模拟事件
    finally:
        _simulating = False
    time.sleep(0.03)


def replace_text_window(original: str, replacement: str) -> bool:
    """Replace an AX-located text window without clipboard fallback."""
    return _replace_accessibility_selection(
        replacement,
        original=original,
        require_original_at_caret=True,
    )


def delete_selection(original: str = "") -> None:
    """删除当前选中内容，只发送一次 Backspace，并让热键监听忽略该合成事件。"""
    if _replace_accessibility_selection("", original=original):
        return
    global _simulating
    _simulating = True
    try:
        if _OS == "Darwin":
            src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
            for key_down in (True, False):
                evt = Quartz.CGEventCreateKeyboardEvent(src, 51, key_down)  # 51 = Backspace
                Quartz.CGEventSetFlags(evt, 0)
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, evt)
        else:
            _press_key(Key.backspace)
        time.sleep(0.05)
    finally:
        _simulating = False


def replace_current_line(new_text: str) -> None:
    """
    Home → Shift+End 选中当前行，然后打入 new_text 替换。
    在 LLM 返回之后调用，所以需要重新选一遍（LLM 期间选区可能已失效）。
    """
    # 重新选中当前行（try/finally 防止 Shift 卡住）
    _press_key(Key.home)
    time.sleep(0.05)
    _kb.press(Key.shift)
    try:
        _press_key(Key.end)
    finally:
        _kb.release(Key.shift)
    time.sleep(0.05)
    # 直接打入新文字覆盖选中内容
    type_text(new_text)


# ── 剪贴板辅助（无额外依赖）──────────────────────────────────────

def _press_key(key) -> None:
    _kb.press(key)
    _kb.release(key)


def _copy_selection() -> None:
    """发送 Ctrl+C（Windows/Linux）或 Cmd+C（macOS）复制选中内容。"""
    global _simulating
    _simulating = True
    try:
        if _OS == "Darwin":
            _kb.press(Key.cmd)
            try:
                _press_key(KeyCode.from_char("c"))
            finally:
                _kb.release(Key.cmd)
        else:
            _kb.press(Key.ctrl)
            try:
                _press_key(KeyCode.from_char("c"))
            finally:
                _kb.release(Key.ctrl)
        time.sleep(0.05)  # 等 pynput 监听线程处理完这批模拟事件
    finally:
        _simulating = False


def _get_clipboard() -> str:
    if _OS == "Windows":
        return _get_clipboard_win()
    elif _OS == "Darwin":
        try:
            value = NSPasteboard.generalPasteboard().stringForType_(NSPasteboardTypeString)
            return str(value) if value is not None else ""
        except Exception:
            return ""
    else:
        import subprocess
        for cmd in [["xclip", "-selection", "clipboard", "-o"],
                    ["xsel", "--clipboard", "--output"]]:
            try:
                return subprocess.check_output(cmd, timeout=3).decode("utf-8", errors="replace")
            except Exception:
                continue
        return ""


def _set_clipboard(text: str) -> None:
    if _OS == "Windows":
        _set_clipboard_win(text)
    elif _OS == "Darwin":
        try:
            pb = NSPasteboard.generalPasteboard()
            pb.clearContents()
            pb.setString_forType_(str(text or ""), NSPasteboardTypeString)
        except Exception:
            pass
    else:
        import subprocess
        for cmd in [["xclip", "-selection", "clipboard"],
                    ["xsel", "--clipboard", "--input"]]:
            try:
                p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
                p.communicate(text.encode("utf-8"))
                return
            except Exception:
                continue


def _get_clipboard_win() -> str:
    CF_UNICODETEXT = 13
    try:
        _user32.OpenClipboard(0)
        h = _user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return ""
        ptr = _kernel32.GlobalLock(h)
        text = ctypes.wstring_at(ptr) if ptr else ""
        _kernel32.GlobalUnlock(h)
        return text
    except Exception:
        return ""
    finally:
        try:
            _user32.CloseClipboard()
        except Exception:
            pass


def _set_clipboard_win(text: str) -> None:
    CF_UNICODETEXT = 13
    GHND           = 0x0042
    try:
        data = text.encode("utf-16-le") + b"\x00\x00"
        h    = _kernel32.GlobalAlloc(GHND, len(data))
        if not h:
            raise RuntimeError("GlobalAlloc 失败")
        ptr  = _kernel32.GlobalLock(h)
        if not ptr:
            raise RuntimeError("GlobalLock 失败")
        ctypes.memmove(ptr, data, len(data))
        _kernel32.GlobalUnlock(h)
        _user32.OpenClipboard(0)
        _user32.EmptyClipboard()
        _user32.SetClipboardData(CF_UNICODETEXT, h)
    except Exception as e:
        print(f"[typer] 剪贴板写入失败: {e}")
    finally:
        try:
            _user32.CloseClipboard()
        except Exception:
            pass


# ── 快捷键 ────────────────────────────────────────────────────────

def send_shortcut(name: str) -> bool:
    """按名称触发快捷键，返回是否找到该指令"""
    if not shortcut_policy_for_invocation(name).allowed:
        return False
    app = current_application()
    keys = _app_shortcut(app, name)
    if keys:
        print(f"[typer] experimental app shortcut: {app.label} -> {name}")
        _press_keys(keys)
        return True
    keys = _SHORTCUTS.get(name)
    if keys:
        _press_keys(keys)
        return True
    action = _system_actions_for_platform().get(name)
    if action:
        return _run_system_action(action)
    app_launch = _app_launch(name)
    if app_launch:
        return app_launcher.launch_application(app_launch, _OS)
    return False


def _press_keys(keys: list) -> None:
    for k in keys:
        _kb.press(k)
    for k in reversed(keys):
        _kb.release(k)


def _run_system_action(action: str) -> bool:
    if action == "open_system_settings":
        if _OS == "Darwin":
            subprocess.Popen(["open", "-b", "com.apple.systempreferences"])
            return True
        if _OS == "Windows":
            subprocess.Popen(["start", "ms-settings:"], shell=True)
            return True
        subprocess.Popen(["sh", "-lc", "gnome-control-center || systemsettings5 || true"])
        return True
    if action.startswith("macos_window_"):
        return _run_macos_window_action(action.removeprefix("macos_window_"))
    return False


def _system_actions_for_platform() -> dict[str, str]:
    actions = dict(_SYSTEM_ACTIONS)
    if _OS == "Darwin":
        actions.update({
            name: f"macos_window_{action}"
            for name, action in macos_window_actions.WINDOW_ACTIONS.items()
        })
    return actions


def _run_macos_window_action(action: str) -> bool:
    if _OS != "Darwin":
        return False
    _ensure_macos_window_action_shortcuts()
    return macos_window_actions.run_window_action(
        action,
        current_application(),
        ApplicationServices,
        _press_keys,
        _MACOS_WINDOW_ACTION_SHORTCUTS,
        _MACOS_FULLSCREEN_TOGGLE_SHORTCUT,
        sleep=time.sleep,
    )


def register_shortcut(name: str, keys: list) -> None:
    """运行时注册自定义快捷键"""
    _SHORTCUTS[name] = keys


def list_shortcuts() -> list[str]:
    return [entry.name for entry in shortcut_catalog()]


def shortcut_catalog() -> list[ShortcutCatalogEntry]:
    return build_shortcut_catalog(
        _local_operation_candidates(),
        blocked_names=_BLOCKED_SHORTCUT_NAMES,
        blocked_key_signatures=_BLOCKED_SHORTCUT_KEY_SEQUENCES,
        high_risk_names=_HIGH_RISK_SHORTCUT_NAMES,
    )


def _local_operation_candidates() -> list[LocalOperationCandidate]:
    candidates: list[LocalOperationCandidate] = []
    app = current_application()
    for name, keys in _app_shortcuts_for(app).items():
        candidates.append(LocalOperationCandidate(
            name=name,
            source="application",
            kind="shortcut",
            application=app.label,
            key_signature=_shortcut_key_signature(keys),
        ))
    for name, keys in _SHORTCUTS.items():
        candidates.append(LocalOperationCandidate(
            name=name,
            source="global",
            kind="shortcut",
            key_signature=_shortcut_key_signature(keys),
        ))
    for name, action in _system_actions_for_platform().items():
        kind = "system_window_action" if action.startswith("macos_window_") else "system_action"
        candidates.append(LocalOperationCandidate(
            name=name,
            source="system",
            kind=kind,
        ))
    for name in _app_launches_for_system():
        candidates.append(LocalOperationCandidate(
            name=name,
            source="system",
            kind="app_launch",
        ))
    return candidates


def shortcut_policy_for_invocation(
    name: str,
    *,
    in_atomic_stack: bool = False,
) -> ShortcutPolicyDecision:
    return _catalog_policy_for_invocation(
        shortcut_catalog(),
        name,
        in_atomic_stack=in_atomic_stack,
    )


def _shortcut_is_blocked(name: str, keys: list | None = None) -> bool:
    return name in _BLOCKED_SHORTCUT_NAMES or _shortcut_key_signature(keys) in _BLOCKED_SHORTCUT_KEY_SEQUENCES


def _app_launch(name: str) -> ApplicationLaunchSpec | None:
    return app_launcher.app_launch(name, _OS, _BLOCKED_SHORTCUT_NAMES)


def _app_launches_for_system() -> dict[str, ApplicationLaunchSpec]:
    return app_launcher.app_launches_for_system(_OS)


def _discover_macos_app_launches() -> dict[str, ApplicationLaunchSpec]:
    return app_launcher.discover_macos_app_launches()


def _app_shortcut(app: ActiveApplication, name: str) -> list | None:
    for shortcuts in _app_shortcut_maps(app):
        keys = shortcuts.get(name)
        if keys and not _shortcut_is_blocked(name, keys):
            return keys
    return None


def _app_shortcuts_for(app: ActiveApplication) -> dict[str, list]:
    merged: dict[str, list] = {}
    for shortcuts in reversed(_app_shortcut_maps(app)):
        merged.update(shortcuts)
    return merged


def _app_shortcut_maps(app: ActiveApplication) -> list[dict[str, list]]:
    keys = []
    for value in (app.bundle_id, app.name):
        if value:
            keys.append(value)
            lowered = value.lower()
            if lowered != value:
                keys.append(lowered)
    out = []
    for key in keys:
        custom = _APP_SHORTCUTS.get(key)
        if custom is not None:
            out.append(custom)
        preset = _macos_app_shortcut_preset(key)
        if preset is not None:
            out.append(preset)
    return out


def _macos_app_shortcut_preset(app_key: str) -> dict[str, list] | None:
    if _OS != "Darwin":
        return None
    shortcuts = _MACOS_APP_SHORTCUT_PRESETS.get(app_key.lower())
    if not shortcuts:
        return None
    parsed_shortcuts: dict[str, list] = {}
    for name, keys in shortcuts.items():
        try:
            parsed_shortcuts[name] = _parse_shortcut_keys(keys)
        except ValueError as e:
            print(f"[typer] 忽略内置活动应用快捷键 {app_key!r}/{name!r}: {e}")
    return parsed_shortcuts or None


def _load_custom_shortcuts(shortcuts) -> None:
    if not isinstance(shortcuts, dict):
        return
    for name, keys in shortcuts.items():
        if not isinstance(name, str) or not name.strip():
            continue
        try:
            parsed = _parse_shortcut_keys(keys)
        except ValueError as e:
            print(f"[typer] 忽略自定义快捷键 {name!r}: {e}")
            continue
        if parsed:
            register_shortcut(name.strip(), parsed)


def _load_app_shortcuts(application_shortcuts) -> None:
    if not isinstance(application_shortcuts, dict):
        return
    for app_key, shortcuts in application_shortcuts.items():
        if not isinstance(app_key, str) or not app_key.strip():
            continue
        if not isinstance(shortcuts, dict):
            print(f"[typer] 忽略活动应用快捷键 {app_key!r}: 必须是映射")
            continue
        parsed_shortcuts: dict[str, list] = {}
        for name, keys in shortcuts.items():
            if not isinstance(name, str) or not name.strip():
                continue
            try:
                parsed = _parse_shortcut_keys(keys)
            except ValueError as e:
                print(f"[typer] 忽略活动应用快捷键 {app_key!r}/{name!r}: {e}")
                continue
            if parsed:
                parsed_shortcuts[name.strip()] = parsed
        if parsed_shortcuts:
            key = app_key.strip()
            _APP_SHORTCUTS[key] = parsed_shortcuts
            _APP_SHORTCUTS[key.lower()] = parsed_shortcuts
            print(f"[typer] 已加载活动应用快捷键: {key}")


def _load_macos_window_action_shortcuts(cfg: dict) -> None:
    global _MACOS_WINDOW_ACTION_SHORTCUTS, _MACOS_FULLSCREEN_TOGGLE_SHORTCUT
    _MACOS_WINDOW_ACTION_SHORTCUTS = {
        action: _parse_shortcut_keys(keys)
        for action, keys in macos_window_actions.DEFAULT_WINDOW_ACTION_SHORTCUTS.items()
    }
    _MACOS_FULLSCREEN_TOGGLE_SHORTCUT = _parse_shortcut_keys(
        macos_window_actions.FULLSCREEN_TOGGLE_SHORTCUT
    )
    configured = cfg.get("macos_window_shortcuts", {})
    if not isinstance(configured, dict):
        return
    for action, keys in configured.items():
        if action == "fullscreen_toggle":
            try:
                _MACOS_FULLSCREEN_TOGGLE_SHORTCUT = _parse_shortcut_keys(keys)
            except ValueError as e:
                print(f"[typer] 忽略 macOS 全屏切换快捷键 {keys!r}: {e}")
            continue
        if action not in macos_window_actions.WINDOW_ACTIONS.values():
            print(f"[typer] 忽略未知 macOS 窗口动作 {action!r}")
            continue
        try:
            _MACOS_WINDOW_ACTION_SHORTCUTS[action] = _parse_shortcut_keys(keys)
        except ValueError as e:
            print(f"[typer] 忽略 macOS 窗口动作快捷键 {action!r}: {e}")


def _ensure_macos_window_action_shortcuts() -> None:
    if not _MACOS_WINDOW_ACTION_SHORTCUTS or not _MACOS_FULLSCREEN_TOGGLE_SHORTCUT:
        _load_macos_window_action_shortcuts({})


def _configured_app_shortcuts(cfg: dict) -> dict:
    merged: dict = {}
    for key in ("app_shortcuts", "experimental_app_shortcuts", "application_shortcuts"):
        value = cfg.get(key)
        if not isinstance(value, dict):
            continue
        for app_key, shortcuts in value.items():
            if not isinstance(shortcuts, dict):
                merged[app_key] = shortcuts
                continue
            existing = merged.get(app_key)
            if isinstance(existing, dict):
                merged[app_key] = {**existing, **shortcuts}
            else:
                merged[app_key] = dict(shortcuts)
    return merged


def _load_app_launches(app_launches) -> None:
    app_launcher.load_app_launches(app_launches)


def _parse_app_launch_spec(spec) -> ApplicationLaunchSpec | None:
    return app_launcher.parse_app_launch_spec(spec)


def _string_config_value(config: dict, *keys: str) -> str:
    return app_launcher.string_config_value(config, *keys)


def _load_blocked_shortcuts(cfg: dict) -> None:
    _BLOCKED_SHORTCUT_NAMES.clear()
    _BLOCKED_SHORTCUT_KEY_SEQUENCES.clear()
    for name in cfg.get("blocked_shortcuts", []) or []:
        if isinstance(name, str) and name.strip():
            _BLOCKED_SHORTCUT_NAMES.add(name.strip())
    for keys in cfg.get("blocked_shortcut_keys", []) or []:
        try:
            parsed = _parse_shortcut_keys(keys)
        except ValueError as e:
            print(f"[typer] 忽略保留快捷键 {keys!r}: {e}")
            continue
        _BLOCKED_SHORTCUT_KEY_SEQUENCES.add(_shortcut_key_signature(parsed))


def _shortcut_key_signature(keys: list | None) -> tuple[str, ...]:
    if not keys:
        return ()
    return tuple(_shortcut_key_token(key) for key in keys)


def _shortcut_key_token(key) -> str:
    if isinstance(key, KeyCode):
        return f"char:{key.char}"
    if isinstance(key, Key):
        return f"key:{key.name}"
    return str(key)


def _parse_shortcut_keys(keys) -> list:
    if isinstance(keys, str):
        separator = "+" if "+" in keys else ","
        parts = [p.strip() for p in keys.split(separator) if p.strip()]
    elif isinstance(keys, list):
        parts = [str(p).strip() for p in keys if str(p).strip()]
    else:
        raise ValueError("keys 必须是字符串或列表")
    if not parts:
        raise ValueError("keys 不能为空")
    return [_parse_shortcut_key(part) for part in parts]


def _parse_shortcut_key(part: str):
    normalized = part.lower().replace("-", "_")
    aliases = {
        "cmd": "cmd",
        "command": "cmd",
        "win": "cmd",
        "ctrl": "ctrl",
        "control": "ctrl",
        "alt": "alt",
        "option": "alt",
        "shift": "shift",
        "enter": "enter",
        "return": "enter",
        "space": "space",
        "tab": "tab",
        "esc": "esc",
        "escape": "esc",
        "backspace": "backspace",
        "delete": "delete",
        "del": "delete",
        "up": "up",
        "down": "down",
        "left": "left",
        "right": "right",
        "home": "home",
        "end": "end",
        "page_up": "page_up",
        "page_down": "page_down",
        "print_screen": "print_screen",
    }
    key_name = aliases.get(normalized, normalized)
    if hasattr(Key, key_name):
        return getattr(Key, key_name)
    if len(part) == 1:
        return KeyCode.from_char(part)
    raise ValueError(f"未知按键 {part!r}")


def jump_to_end() -> None:
    """光标跳到文本框末尾（取消任何选中状态）。跨平台实现。"""
    if _OS == "Darwin":
        _kb.press(Key.cmd)
        try:
            _press_key(Key.down)
        finally:
            _kb.release(Key.cmd)
    else:
        # Windows / Linux：Ctrl+End
        _kb.press(Key.ctrl)
        try:
            _press_key(Key.end)
        finally:
            _kb.release(Key.ctrl)
    time.sleep(0.05)
