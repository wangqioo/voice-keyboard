import platform
import threading
import time
from pynput.keyboard import Controller, Key, KeyCode

_LOG = r"C:\Users\10990\voice-keyboard\typer_debug.log"

def _dbg(msg: str) -> None:
    import datetime
    line = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}\n"
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass

_kb = Controller()
_OS = platform.system()

if _OS == "Darwin":
    import Quartz

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
    _user32.PostMessageW.restype  = ctypes.wintypes.BOOL
    _user32.PostMessageW.argtypes = [ctypes.wintypes.HWND, ctypes.c_uint,
                                     ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM]
    _user32.GetForegroundWindow.restype  = ctypes.wintypes.HWND
    _user32.GetForegroundWindow.argtypes = []
    _user32.GetWindowThreadProcessId.restype  = ctypes.wintypes.DWORD
    _user32.GetWindowThreadProcessId.argtypes = [ctypes.wintypes.HWND,
                                                  ctypes.POINTER(ctypes.wintypes.DWORD)]
    _user32.EnumChildWindows.restype  = ctypes.wintypes.BOOL
    _user32.EnumChildWindows.argtypes = [ctypes.wintypes.HWND, ctypes.c_void_p,
                                          ctypes.wintypes.LPARAM]
    _user32.GetClassNameW.restype  = ctypes.c_int
    _user32.GetClassNameW.argtypes = [ctypes.wintypes.HWND, ctypes.c_wchar_p, ctypes.c_int]
    _kernel32.OpenProcess.restype  = ctypes.c_void_p
    _kernel32.OpenProcess.argtypes = [ctypes.wintypes.DWORD, ctypes.wintypes.BOOL,
                                       ctypes.wintypes.DWORD]
    _kernel32.CloseHandle.restype  = ctypes.wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    _kernel32.QueryFullProcessImageNameW.restype  = ctypes.wintypes.BOOL
    _kernel32.QueryFullProcessImageNameW.argtypes = [
        ctypes.c_void_p, ctypes.wintypes.DWORD,
        ctypes.c_wchar_p, ctypes.POINTER(ctypes.wintypes.DWORD),
    ]

# ── 原子标志：供 keyboard_monitor / push_to_talk 过滤自身产生的事件 ──────
# _erasing   : erase_last() 正在发退格，避免 keyboard_monitor 双重扣减
# _simulating: type_text() / clipboard paste 正在模拟按键（含 Ctrl+V）
#              push_to_talk 的 _on_press 检查此标志，防止 Ctrl 被误识别为录音热键
# CPython GIL 保证 bool 赋值原子，无需额外 Lock。

_erasing: bool = False
_simulating: bool = False   # 程序自己发 Cmd+C/V 等按键时置 True，让 PTT 监听忽略

_use_clipboard_mode: bool = False
# 需要用 PostMessage(WM_CHAR) 注入的进程名（小写）
# 这些 Chromium 应用会把 KEYEVENTF_UNICODE 的 WM_KEYDOWN+WM_CHAR 都当字符处理，导致逗号重复
_postmessage_apps: list[str] = ["wechat.exe", "weixin.exe"]


def init(cfg: dict) -> None:
    """由 main.py 在启动时调用，根据 config.yaml 的 typing.method 配置打字方式。"""
    global _use_clipboard_mode, _postmessage_apps
    _use_clipboard_mode = cfg.get("method", "unicode") == "clip"
    apps = cfg.get("postmessage_apps", ["wechat.exe", "weixin.exe"])
    _postmessage_apps = [a.lower() for a in apps]
    if _use_clipboard_mode:
        print("[typer] 剪贴板粘贴模式（适合微信等应用）")


def is_erasing() -> bool:
    """供 keyboard_monitor 检查：当前退格事件是否由 erase_last 发出。"""
    return _erasing

def is_simulating() -> bool:
    """供 push_to_talk / keyboard_monitor 检查：当前是否由程序自身在模拟按键（如 Cmd+C/V）。"""
    return _simulating


# 语音指令 → 快捷键映射
_SHORTCUTS: dict[str, list] = {
    "截图":    [Key.cmd, Key.shift, KeyCode.from_char("4")],  # macOS 截图
    "保存":    [Key.cmd, KeyCode.from_char("s")],
    "复制":    [Key.cmd, KeyCode.from_char("c")],
    "粘贴":    [Key.cmd, KeyCode.from_char("v")],
    "撤销":    [Key.cmd, KeyCode.from_char("z")],
    "全选":    [Key.cmd, KeyCode.from_char("a")],
    "新标签":  [Key.cmd, KeyCode.from_char("t")],
    "关闭标签":[Key.cmd, KeyCode.from_char("w")],
    "回车":    [Key.enter],
    "删除":    [Key.backspace],
    "空格":    [Key.space],
}

# Windows / Linux 下替换修饰键（两者快捷键基本相同）
if _OS in ("Windows", "Linux"):
    _SHORTCUTS["复制"]    = [Key.ctrl, KeyCode.from_char("c")]
    _SHORTCUTS["粘贴"]    = [Key.ctrl, KeyCode.from_char("v")]
    _SHORTCUTS["保存"]    = [Key.ctrl, KeyCode.from_char("s")]
    _SHORTCUTS["撤销"]    = [Key.ctrl, KeyCode.from_char("z")]
    _SHORTCUTS["全选"]    = [Key.ctrl, KeyCode.from_char("a")]
    _SHORTCUTS["新标签"]  = [Key.ctrl, KeyCode.from_char("t")]
    _SHORTCUTS["关闭标签"]= [Key.ctrl, KeyCode.from_char("w")]

if _OS == "Windows":
    _SHORTCUTS["截图"] = [Key.cmd, Key.shift, KeyCode.from_char("s")]  # Win+Shift+S
elif _OS == "Linux":
    _SHORTCUTS["截图"] = [Key.print_screen]  # 大多数桌面环境


# ── 打字 ──────────────────────────────────────────────────────────

def _foreground_exe_win() -> str:
    """返回当前前台窗口的进程文件名（小写），失败返回空串。"""
    try:
        hwnd = _user32.GetForegroundWindow()
        pid  = ctypes.wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        h = _kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ""
        buf  = ctypes.create_unicode_buffer(512)
        size = ctypes.wintypes.DWORD(512)
        _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
        _kernel32.CloseHandle(h)
        return buf.value.split("\\")[-1].lower()
    except Exception:
        return ""


def _find_render_widget_win(parent: int) -> int:
    """在子窗口中找 Chromium 渲染层窗口（Chrome_RenderWidgetHostHWND），找不到返回 parent。"""
    found = ctypes.wintypes.HWND(0)

    WndEnumProc = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL,
                                      ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

    def _cb(hwnd, _lp):
        buf = ctypes.create_unicode_buffer(64)
        _user32.GetClassNameW(hwnd, buf, 64)
        if buf.value == "Chrome_RenderWidgetHostHWND":
            found.value = hwnd
            return False  # 停止枚举
        return True

    _user32.EnumChildWindows(parent, WndEnumProc(_cb), 0)
    return found.value or parent


def _type_via_postmessage_win(text: str) -> None:
    """用 PostMessage(WM_CHAR) 注入文字，专用于微信等 Chromium 应用。

    只发 WM_CHAR，不发 WM_KEYDOWN/WM_KEYUP，Chromium 不会双重处理逗号。
    PostMessage 不经过全局键盘钩子，无需设 _simulating 标志。
    """
    WM_CHAR = 0x0102
    parent = _user32.GetForegroundWindow()
    hwnd   = _find_render_widget_win(parent)
    _dbg(f"PostMessage: parent={hex(parent)} target={hex(hwnd)} found_widget={hwnd != parent}")

    for char in text:
        code = ord(char)
        if code > 0xFFFF:
            code -= 0x10000
            high = 0xD800 + (code >> 10)
            low  = 0xDC00 + (code & 0x3FF)
            _user32.PostMessageW(hwnd, WM_CHAR, high, 1)
            _user32.PostMessageW(hwnd, WM_CHAR, low,  1)
        else:
            _user32.PostMessageW(hwnd, WM_CHAR, code, 1)
        time.sleep(0.012)


def type_text(text: str) -> None:
    """在当前焦点输入框打出任意 Unicode 文字（含汉字）"""
    if not text:
        return
    if _OS == "Darwin":
        _type_via_quartz(text)
    elif _OS == "Windows":
        if _use_clipboard_mode:
            _type_via_clipboard_win(text)
        elif bool(_postmessage_apps) and _foreground_exe_win() in _postmessage_apps:
            _dbg("检测到微信，切换 PostMessage 模式")
            _type_via_postmessage_win(text)
        else:
            _dbg(f"SendInput 模式: exe={_foreground_exe_win()!r}")
            _type_via_sendinput(text)
    else:
        _type_via_xtest(text)  # Linux


def _type_via_quartz(text: str) -> None:
    global _simulating
    _simulating = True
    try:
        src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
        for char in text:
            for key_down in (True, False):
                evt = Quartz.CGEventCreateKeyboardEvent(src, 0, key_down)
                Quartz.CGEventKeyboardSetUnicodeString(evt, len(char), char)
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, evt)
            time.sleep(0.012)
    finally:
        _simulating = False


def _type_via_sendinput(text: str) -> None:
    global _simulating
    _simulating = True
    try:
        for char in text:
            code = ord(char)
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
    finally:
        _simulating = False


def _type_via_clipboard_win(text: str) -> None:
    # Windows 剪贴板粘贴模式：适合微信等拦截 SendInput 的应用
    # _simulating=True 防止 Ctrl 键被 push_to_talk 监听器误识别为录音热键
    global _simulating
    _simulating = True
    try:
        _set_clipboard_win(text)
        time.sleep(0.03)
        _kb.press(Key.ctrl)
        try:
            _press_key(KeyCode.from_char("v"))
        finally:
            _kb.release(Key.ctrl)
        time.sleep(0.03)
    finally:
        _simulating = False


def _type_via_xtest(text: str) -> None:
    global _simulating
    _simulating = True
    try:
        for char in text:
            _kb.type(char)
            time.sleep(0.012)
    finally:
        _simulating = False


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


_SENTINEL = "\x00__VK_NO_SELECTION__\x00"


def get_selection() -> str:
    """
    读取当前鼠标选中的文字。
    原理：剪贴板写 sentinel → Cmd+C → 读剪贴板 → 恢复原剪贴板。
    若读到 sentinel（说明 Cmd+C 没改写剪贴板）则没有选中。
    用 sentinel 而非 old_clip 比较，避免选中内容和剪贴板原内容相同时误判为空。
    """
    try:
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


def replace_selection(text: str) -> None:
    """将 text 写入剪贴板并粘贴，替换当前选中内容（选区失效时在光标处插入）。"""
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
        import subprocess
        try:
            return subprocess.check_output(
                ["pbpaste"], timeout=3
            ).decode("utf-8", errors="replace")
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
        import subprocess
        try:
            p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            p.communicate(text.encode("utf-8"))
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
    keys = _SHORTCUTS.get(name)
    if not keys:
        return False
    for k in keys:
        _kb.press(k)
    for k in reversed(keys):
        _kb.release(k)
    return True


def register_shortcut(name: str, keys: list) -> None:
    """运行时注册自定义快捷键"""
    _SHORTCUTS[name] = keys


def list_shortcuts() -> list[str]:
    return list(_SHORTCUTS.keys())


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
