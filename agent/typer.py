import platform
import time
from pynput.keyboard import Controller, Key, KeyCode

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

    _user32 = ctypes.windll.user32

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

# Windows 下替换修饰键
if _OS == "Windows":
    _SHORTCUTS["截图"] = [Key.cmd, Key.shift, KeyCode.from_char("s")]
    _SHORTCUTS["复制"] = [Key.ctrl, KeyCode.from_char("c")]
    _SHORTCUTS["粘贴"] = [Key.ctrl, KeyCode.from_char("v")]
    _SHORTCUTS["保存"] = [Key.ctrl, KeyCode.from_char("s")]
    _SHORTCUTS["撤销"] = [Key.ctrl, KeyCode.from_char("z")]
    _SHORTCUTS["全选"] = [Key.ctrl, KeyCode.from_char("a")]
    _SHORTCUTS["新标签"] = [Key.ctrl, KeyCode.from_char("t")]
    _SHORTCUTS["关闭标签"] = [Key.ctrl, KeyCode.from_char("w")]


def type_text(text: str) -> None:
    """在当前焦点输入框逐字打出任意 Unicode 文字（含汉字）"""
    if not text:
        return
    if _OS == "Darwin":
        _type_via_quartz(text)
    elif _OS == "Windows":
        _type_via_sendinput(text)
    else:
        _type_via_xtest(text)  # Linux


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
    # ctypes 内置，不需要额外装包
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


def _type_via_xtest(text: str) -> None:
    # Linux：pynput 逐字，底层走 X11 XTest，绕过 IME
    for char in text:
        _kb.type(char)
        time.sleep(0.012)


def send_shortcut(name: str) -> bool:
    """按名称触发快捷键，返回是否找到该指令"""
    keys = _SHORTCUTS.get(name)
    if not keys:
        return False
    # 同时按下所有键，再全部释放
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
