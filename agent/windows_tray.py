"""Windows tray app for Voice Keyboard."""

from __future__ import annotations

import os
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
from agent.memo_store import MemoStore
from agent.runtime_composition import RuntimeOptions, build_runtime_backend
from agent.status_window_win import StatusWindow
from agent.text_buffer import TextBuffer
from agent.windows_main_window import WindowsMainWindow


_USER_DIR = Path.home() / ".voice-keyboard"
_CONFIG = _USER_DIR / "config.yaml"
_APP_NAME = "Voice Keyboard"
_HOTKEY_OPTIONS = [
    ("shift_r", "Right Shift", "\u53f3 Shift"),
    ("alt_r", "Right Alt", "\u53f3 Alt"),
    ("alt_gr", "AltGr", "AltGr"),
    ("ctrl_r", "Right Ctrl", "\u53f3 Ctrl"),
    ("f8", "F8", "F8"),
    ("f9", "F9", "F9"),
    ("f10", "F10", "F10"),
]



class WindowsTrayApp:
    def __init__(self):
        self._backend = None
        self._lock = threading.Lock()
        self._status = StatusWindow()
        self._buf = TextBuffer()
        self._history = History()
        self._icon: pystray.Icon | None = None
        self._main_window = WindowsMainWindow(
            history=self._history,
            insert_text=self._insert_text_after_menu_closes,
            reload_config=self._reload_backend_now,
            notify=self._notify_text,
        )

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
            pystray.MenuItem(labels["open_main_window"], self._open_main_window, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(labels["language"], pystray.Menu(
                pystray.MenuItem(labels["language_zh"], lambda icon, item: self._set_language("zh"), checked=lambda item: self._language() == "zh", radio=True),
                pystray.MenuItem(labels["language_en"], lambda icon, item: self._set_language("en"), checked=lambda item: self._language() == "en", radio=True),
            )),
            pystray.MenuItem(labels["hotkeys"], pystray.Menu(
                pystray.MenuItem(labels["dictation_hotkey"], self._hotkey_menu("ptt_key")),
                pystray.MenuItem(labels["ai_hotkey"], self._hotkey_menu("ai_key")),
            )),
            pystray.MenuItem(labels["history"], pystray.Menu(lambda: self._history_menu_items())),
            pystray.MenuItem(labels["memo"], pystray.Menu(lambda: self._memo_menu_items())),
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
                "open_main_window": "Open Main Window",
                "language": "Language",
                "language_zh": "Chinese",
                "language_en": "English",
                "hotkeys": "Hotkeys",
                "dictation_hotkey": "Dictation Hotkey",
                "ai_hotkey": "AI Hotkey",
                "history": "History",
                "memo": "Memo Library",
                "empty_history": "No history yet",
                "empty_memo": "No memos yet",
                "type_history": "History inserted",
                "type_memo": "Memo inserted",
                "reload": "Reload Config",
                "install_autostart": "Enable Start on Login",
                "uninstall_autostart": "Disable Start on Login",
                "quit": "Quit",
            }
        return {
            "running": "Voice Keyboard \u6b63\u5728\u8fd0\u884c",
            "open_main_window": "\u6253\u5f00\u4e3b\u7a97\u53e3",
            "language": "\u8bed\u8a00 / Language",
            "language_zh": "\u4e2d\u6587",
            "language_en": "English",
            "hotkeys": "\u5feb\u6377\u952e",
            "dictation_hotkey": "\u8bed\u97f3\u8f6c\u6587\u5b57\u5feb\u6377\u952e",
            "ai_hotkey": "AI \u529f\u80fd\u5feb\u6377\u952e",
            "history": "\u5386\u53f2\u8bb0\u5f55",
            "memo": "\u8bb0\u5fc6\u5e93",
            "empty_history": "\u6682\u65e0\u5386\u53f2\u8bb0\u5f55",
            "empty_memo": "\u6682\u65e0\u8bb0\u5fc6",
            "type_history": "\u5df2\u63d2\u5165\u5386\u53f2\u8bb0\u5f55",
            "type_memo": "\u5df2\u63d2\u5165\u8bb0\u5fc6",
            "reload": "\u91cd\u8f7d\u914d\u7f6e",
            "install_autostart": "\u6ce8\u518c\u5f00\u673a\u81ea\u542f",
            "uninstall_autostart": "\u53d6\u6d88\u5f00\u673a\u81ea\u542f",
            "quit": "\u9000\u51fa",
        }

    def _message(self, key: str, **values) -> str:
        en = self._language() == "en"
        messages = {
            "language_set": ("Language: {language}", "\u8bed\u8a00\uff1a{language}"),
            "hotkey_set": ("{name}: {value}", "{name}\uff1a{value}"),
            "config_reloaded": ("Config reloaded", "\u914d\u7f6e\u5df2\u91cd\u8f7d"),
            "autostart_enabled": ("Start on login enabled", "\u5df2\u5f00\u542f\u5f00\u673a\u81ea\u542f"),
            "autostart_disabled": ("Start on login disabled", "\u5df2\u53d6\u6d88\u5f00\u673a\u81ea\u542f"),
            "inserted": ("{kind}: {preview}", "{kind}\uff1a{preview}"),
            "insert_failed": ("Insert failed: {reason}", "\u63d2\u5165\u5931\u8d25\uff1a{reason}"),
        }
        template = messages[key][0 if en else 1]
        return template.format(**values)

    def _notify(self, key: str, **values) -> None:
        if hasattr(self._status, "show_message"):
            self._status.show_message(self._message(key, **values), 2.5)

    def _notify_text(self, message: str) -> None:
        if hasattr(self._status, "show_message"):
            self._status.show_message(message, 2.5)

    def _hotkey_display_name(self, key_name: str) -> str:
        labels = self._labels()
        return labels["dictation_hotkey"] if key_name == "ptt_key" else labels["ai_hotkey"]

    def _hotkey_display_value(self, value: str) -> str:
        language = self._language()
        for key, en_label, zh_label in _HOTKEY_OPTIONS:
            if key == value:
                return en_label if language == "en" else zh_label
        return value

    def _hotkey_menu(self, key_name: str):
        labels = self._labels()
        language = self._language()
        current = self._hotkey_value(key_name)
        items = []
        for value, en_label, zh_label in _HOTKEY_OPTIONS:
            label = en_label if language == "en" else zh_label
            items.append(pystray.MenuItem(
                label,
                self._hotkey_action(key_name, value),
                checked=lambda item, value=value, current=current: current == value,
                radio=True,
            ))
        return pystray.Menu(*items)

    def _hotkey_action(self, key_name: str, value: str):
        def action(_icon=None, _item=None):
            self._set_hotkey(key_name, value)
        return action

    def _history_menu_items(self):
        labels = self._labels()
        rows = [
            row for row in reversed(self._history.load(limit=30))
            if str(row.get("text") or "").strip()
        ][:8]
        items = []
        if rows:
            for row in rows:
                text = str(row.get("text") or "")
                mode = str(row.get("mode") or "")
                items.append(pystray.MenuItem(
                    self._menu_preview(text, prefix=mode),
                    self._insert_text_action(text, labels["type_history"]),
                ))
        else:
            items.append(pystray.MenuItem(labels["empty_history"], lambda: None, enabled=False))
        return tuple(items)

    def _memo_menu_items(self):
        labels = self._labels()
        store = MemoStore()
        keys = sorted(k for k in store.keys() if str(k).strip())[:12]
        items = []
        if keys:
            for key in keys:
                value = store.get(key) or ""
                items.append(pystray.MenuItem(
                    self._menu_preview(key),
                    self._insert_text_action(value, labels["type_memo"]),
                    enabled=bool(value),
                ))
        else:
            items.append(pystray.MenuItem(labels["empty_memo"], lambda: None, enabled=False))
        return tuple(items)

    def _insert_text_action(self, text: str, kind: str):
        def action(_icon=None, _item=None):
            self._insert_text_after_menu_closes(text, kind)
        return action

    def _insert_text_after_menu_closes(self, text: str, kind: str) -> None:
        def _run():
            time.sleep(0.35)
            try:
                with self._lock:
                    env = self._backend.input_environment if self._backend is not None else None
                if env is not None:
                    result = env.insert_output_text(text)
                    if not result.ok:
                        raise RuntimeError(result.failure or "insert_failed")
                else:
                    from agent import typer
                    typer.type_text(text)
                    self._buf.add(text)
                self._notify("inserted", kind=kind, preview=self._message_preview(text))
            except Exception as e:
                print(f"[tray] insert failed: {e}")
                self._notify("insert_failed", reason=str(e))
        threading.Thread(target=_run, daemon=True, name="TrayInsertText").start()

    @staticmethod
    def _menu_preview(text: str, prefix: str = "") -> str:
        clean = " ".join(str(text or "").split())
        if len(clean) > 36:
            clean = clean[:36] + "..."
        return f"{prefix}: {clean}" if prefix else clean

    @staticmethod
    def _message_preview(text: str) -> str:
        clean = " ".join(str(text or "").split())
        return clean[:28] + ("..." if len(clean) > 28 else "")

    def _hotkey_value(self, key_name: str) -> str:
        cfg = self._read_config()
        audio = cfg.get("audio") or {}
        value = audio.get(key_name)
        if isinstance(value, list):
            return str(value[0]) if value else ""
        return str(value or "")

    def _set_hotkey(self, key_name: str, value: str):
        cfg = self._read_config()
        audio = cfg.setdefault("audio", {})
        audio[key_name] = value
        self._write_config(cfg)
        self._reload_backend_now(notify=False)
        self._notify("hotkey_set", name=self._hotkey_display_name(key_name), value=self._hotkey_display_value(value))
        if self._icon is not None:
            self._icon.menu = self._menu()
            self._icon.update_menu()

    def _start_backend(self):
        with self._lock:
            self._backend = build_runtime_backend(
                RuntimeOptions(no_serial=True),
                self._buf,
                self._status,
                self._history,
            )

    def _reload_backend(self, _icon=None, _item=None):
        self._reload_backend_now(notify=True)

    def _reload_backend_now(self, notify: bool = True):
        with self._lock:
            if self._backend is not None:
                self._backend.stop()
            self._backend = None
        self._status.set_state("recognizing")
        self._start_backend()
        self._status.set_state("idle")
        if notify:
            self._notify("config_reloaded")

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
        self._notify("language_set", language="English" if language == "en" else "\u4e2d\u6587")
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
        self._main_window.stop()
        if icon is not None:
            icon.stop()

    def _open_main_window(self, _icon=None, _item=None):
        self._main_window.show()

    def _install_autostart(self, _icon=None, _item=None):
        install_autostart()
        self._notify("autostart_enabled")

    def _uninstall_autostart(self, _icon=None, _item=None):
        uninstall_autostart()
        self._notify("autostart_disabled")

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
    WindowsTrayApp().run()


if __name__ == "__main__":
    main()
