"""Windows tray app for Voice Keyboard."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time

import yaml
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

from agent.autostart import install as install_autostart
from agent.autostart import uninstall as uninstall_autostart
from agent.config import ensure_user_config
from agent.history import History
from agent.main import list_devices
from agent.runtime_composition import RuntimeOptions, build_runtime_backend
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
        labels = self._labels()
        return pystray.Menu(
            pystray.MenuItem(labels["running"], lambda: None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(labels["open_config"], self._open_config),
            pystray.MenuItem(labels["open_config_dir"], self._open_config_dir),
            pystray.MenuItem(labels["list_devices"], self._show_devices),
            pystray.MenuItem(labels["test_status"], self._test_status),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(labels["language"], pystray.Menu(
                pystray.MenuItem(labels["language_zh"], lambda icon, item: self._set_language("zh"), checked=lambda item: self._language() == "zh", radio=True),
                pystray.MenuItem(labels["language_en"], lambda icon, item: self._set_language("en"), checked=lambda item: self._language() == "en", radio=True),
            )),
            pystray.MenuItem(labels["reload"], self._reload_backend),
            pystray.MenuItem(labels["install_autostart"], self._install_autostart),
            pystray.MenuItem(labels["uninstall_autostart"], self._uninstall_autostart),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(labels["quit"], self._quit),
        )

    def _labels(self) -> dict[str, str]:
        if self._language() == "en":
            return {
                "running": "Voice Keyboard is running",
                "open_config": "Open Config",
                "open_config_dir": "Open Config Folder",
                "list_devices": "List Microphones",
                "test_status": "Test Status Window",
                "language": "Language",
                "language_zh": "Chinese",
                "language_en": "English",
                "reload": "Reload Config",
                "install_autostart": "Enable Start on Login",
                "uninstall_autostart": "Disable Start on Login",
                "quit": "Quit",
            }
        return {
            "running": "Voice Keyboard \u6b63\u5728\u8fd0\u884c",
            "open_config": "\u6253\u5f00\u914d\u7f6e",
            "open_config_dir": "\u6253\u5f00\u914d\u7f6e\u76ee\u5f55",
            "list_devices": "\u5217\u51fa\u9ea6\u514b\u98ce\u8bbe\u5907",
            "test_status": "\u6d4b\u8bd5\u63d0\u793a\u7a97",
            "language": "\u8bed\u8a00 / Language",
            "language_zh": "\u4e2d\u6587",
            "language_en": "English",
            "reload": "\u91cd\u8f7d\u914d\u7f6e",
            "install_autostart": "\u6ce8\u518c\u5f00\u673a\u81ea\u542f",
            "uninstall_autostart": "\u53d6\u6d88\u5f00\u673a\u81ea\u542f",
            "quit": "\u9000\u51fa",
        }

    def _start_backend(self):
        with self._lock:
            self._backend = build_runtime_backend(
                RuntimeOptions(no_serial=True),
                self._buf,
                self._status,
                self._history,
            )

    def _reload_backend(self, _icon=None, _item=None):
        with self._lock:
            if self._backend is not None:
                self._backend.stop()
            self._backend = None
        self._status.set_state("recognizing")
        self._start_backend()
        self._status.set_state("idle")

    def _language(self) -> str:
        cfg = self._read_config()
        ui = cfg.get("ui") or {}
        language = str(ui.get("language", "zh")).lower()
        return "en" if language.startswith("en") else "zh"

    def _set_language(self, language: str):
        cfg = self._read_config()
        ui = cfg.setdefault("ui", {})
        ui["language"] = "en" if language == "en" else "zh"
        self._write_config(cfg)
        self._status.set_state("dictation_enabled")
        if self._icon is not None:
            self._icon.menu = self._menu()
            self._icon.update_menu()

    def _read_config(self) -> dict:
        _USER_DIR.mkdir(parents=True, exist_ok=True)
        if not _CONFIG.exists():
            ensure_user_config()
        if not _CONFIG.exists():
            return {}
        try:
            return yaml.safe_load(_CONFIG.read_text(encoding="utf-8")) or {}
        except Exception as e:
            print(f"[tray] failed to read config: {e}")
            return {}

    def _write_config(self, cfg: dict) -> None:
        _USER_DIR.mkdir(parents=True, exist_ok=True)
        _CONFIG.write_text(
            yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

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
