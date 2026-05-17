"""Windows tray app for Voice Keyboard."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pystray
from PIL import Image, ImageDraw

from agent.autostart import install as install_autostart
from agent.autostart import uninstall as uninstall_autostart
from agent.config import ensure_user_config
from agent.history import History
from agent.main import build_backend, list_devices
from agent.status_window_win import StatusWindow
from agent.text_buffer import TextBuffer


_USER_DIR = Path.home() / ".voice-keyboard"
_CONFIG = _USER_DIR / "config.yaml"
_APP_NAME = "Voice Keyboard"


class WindowsTrayApp:
    def __init__(self):
        self._backend = None
        self._lock = threading.Lock()
        self._status = StatusWindow()
        self._buf = TextBuffer()
        self._history = History()
        self._icon: pystray.Icon | None = None

    def run(self) -> None:
        ensure_user_config()
        self._history.compact()
        threading.Thread(target=self._status.run, daemon=True, name="StatusWindow").start()
        self._start_backend()

        self._icon = pystray.Icon(
            "voice-keyboard",
            self._make_icon(),
            _APP_NAME,
            menu=self._menu(),
        )
        self._icon.run()

    def _menu(self):
        return pystray.Menu(
            pystray.MenuItem("Voice Keyboard 正在运行", lambda: None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("打开配置", self._open_config),
            pystray.MenuItem("打开配置目录", self._open_config_dir),
            pystray.MenuItem("列出麦克风设备", self._show_devices),
            pystray.MenuItem("测试提示窗", self._test_status),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("重载配置", self._reload_backend),
            pystray.MenuItem("注册开机自启", self._install_autostart),
            pystray.MenuItem("取消开机自启", self._uninstall_autostart),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._quit),
        )

    def _start_backend(self):
        args = SimpleNamespace(no_serial=True, port=None)
        with self._lock:
            self._backend = build_backend(args, self._buf, self._status, self._history)

    def _reload_backend(self, _icon=None, _item=None):
        with self._lock:
            if self._backend is not None:
                self._backend.stop()
            self._backend = None
        self._status.set_state("recognizing")
        self._start_backend()
        self._status.set_state("idle")

    def _quit(self, icon=None, item=None):
        with self._lock:
            if self._backend is not None:
                self._backend.stop()
                self._backend = None
        self._status.stop()
        if icon is not None:
            icon.stop()

    def _open_config(self, _icon=None, _item=None):
        _USER_DIR.mkdir(parents=True, exist_ok=True)
        if not _CONFIG.exists():
            ensure_user_config()
        os.startfile(str(_CONFIG))

    def _open_config_dir(self, _icon=None, _item=None):
        _USER_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(_USER_DIR))

    def _show_devices(self, _icon=None, _item=None):
        subprocess.Popen(
            [sys.executable, "-m", "agent.windows_tray", "--list-devices-console"],
            cwd=str(Path(__file__).resolve().parent.parent),
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )

    def _test_status(self, _icon=None, _item=None):
        def _run():
            for state in ("recording", "recognizing", "ai_processing", "error_stt", "idle"):
                self._status.set_state(state)
                time.sleep(1.0)
        threading.Thread(target=_run, daemon=True).start()

    def _install_autostart(self, _icon=None, _item=None):
        install_autostart()
        self._status.set_state("polish_recording")
        threading.Timer(1.0, lambda: self._status.set_state("idle")).start()

    def _uninstall_autostart(self, _icon=None, _item=None):
        uninstall_autostart()
        self._status.set_state("polish_recording")
        threading.Timer(1.0, lambda: self._status.set_state("idle")).start()

    @staticmethod
    def _make_icon() -> Image.Image:
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((10, 8, 54, 56), radius=18, fill=(37, 99, 235, 255))
        d.rounded_rectangle((24, 16, 40, 38), radius=8, fill=(255, 255, 255, 255))
        d.rectangle((29, 36, 35, 47), fill=(255, 255, 255, 255))
        d.arc((18, 28, 46, 52), 20, 160, fill=(255, 255, 255, 255), width=4)
        return img


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list-devices-console", action="store_true")
    args = parser.parse_args()
    if args.list_devices_console:
        list_devices()
        input("\n按回车关闭...")
        return
    WindowsTrayApp().run()


if __name__ == "__main__":
    main()
