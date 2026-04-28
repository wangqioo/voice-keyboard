"""
开机自启动注册/卸载，三平台统一入口。

打包后运行：直接注册可执行文件路径。
开发模式运行：注册 python -m agent.main。
"""

import platform
import subprocess
import sys
from pathlib import Path

_OS = platform.system()
_APP_NAME = "VoiceKeyboard"
_PLIST_LABEL = "com.voicekeyboard.agent"


def _launch_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "agent.main"]


# ── macOS ─────────────────────────────────────────────────────────────────────

def _install_macos():
    import plistlib

    plist_path = Path.home() / f"Library/LaunchAgents/{_PLIST_LABEL}.plist"
    log_path   = Path.home() / "Library/Logs/VoiceKeyboard.log"

    plist_path.parent.mkdir(parents=True, exist_ok=True)
    with open(plist_path, "wb") as f:
        plistlib.dump({
            "Label":              _PLIST_LABEL,
            "ProgramArguments":   _launch_command(),
            "RunAtLoad":          True,
            "KeepAlive":          True,
            "StandardOutPath":    str(log_path),
            "StandardErrorPath":  str(log_path),
        }, f)

    subprocess.run(["launchctl", "load", str(plist_path)], check=True)
    print(f"[autostart] 已注册 macOS LaunchAgent: {plist_path}")


def _uninstall_macos():
    plist_path = Path.home() / f"Library/LaunchAgents/{_PLIST_LABEL}.plist"
    if plist_path.exists():
        subprocess.run(["launchctl", "unload", str(plist_path)])
        plist_path.unlink()
        print("[autostart] 已移除 macOS LaunchAgent")
    else:
        print("[autostart] 未找到 LaunchAgent，无需移除")


# ── Windows ───────────────────────────────────────────────────────────────────

def _install_windows():
    import winreg
    cmd = " ".join(f'"{c}"' if " " in c else c for c in _launch_command())
    key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, _APP_NAME, 0, winreg.REG_SZ, cmd)
    print(f"[autostart] 已注册 Windows 注册表: {key}\\{_APP_NAME}")


def _uninstall_windows():
    import winreg
    key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, _APP_NAME)
        print("[autostart] 已移除 Windows 注册表项")
    except FileNotFoundError:
        print("[autostart] 注册表项不存在，无需移除")


# ── Linux ─────────────────────────────────────────────────────────────────────

def _install_linux():
    cmd = " ".join(_launch_command())
    desktop_path = Path.home() / ".config/autostart/voice-keyboard.desktop"
    desktop_path.parent.mkdir(parents=True, exist_ok=True)
    desktop_path.write_text(
        f"[Desktop Entry]\n"
        f"Type=Application\n"
        f"Name={_APP_NAME}\n"
        f"Exec={cmd}\n"
        f"Hidden=false\n"
        f"NoDisplay=false\n"
        f"X-GNOME-Autostart-enabled=true\n"
    )
    print(f"[autostart] 已注册 Linux autostart: {desktop_path}")


def _uninstall_linux():
    desktop_path = Path.home() / ".config/autostart/voice-keyboard.desktop"
    if desktop_path.exists():
        desktop_path.unlink()
        print("[autostart] 已移除 Linux autostart")
    else:
        print("[autostart] 未找到 autostart 文件，无需移除")


# ── 统一入口 ──────────────────────────────────────────────────────────────────

def install():
    {"Darwin": _install_macos, "Windows": _install_windows}.get(_OS, _install_linux)()


def uninstall():
    {"Darwin": _uninstall_macos, "Windows": _uninstall_windows}.get(_OS, _uninstall_linux)()
