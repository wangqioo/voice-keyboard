"""Tkinter main window for the Windows tray app."""

from __future__ import annotations

import os
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import yaml

from agent.history import History
from agent.memo_store import MemoStore


_USER_DIR = Path.home() / ".voice-keyboard"
_CONFIG = _USER_DIR / "config.yaml"
_HOTKEY_OPTIONS = [
    ("shift_r", "Right Shift", "\u53f3 Shift"),
    ("alt_r", "Right Alt", "\u53f3 Alt"),
    ("alt_gr", "AltGr", "AltGr"),
    ("ctrl_r", "Right Ctrl", "\u53f3 Ctrl"),
    ("f8", "F8", "F8"),
    ("f9", "F9", "F9"),
    ("f10", "F10", "F10"),
]


def _read_config() -> dict:
    if not _CONFIG.exists():
        return {}
    try:
        return yaml.safe_load(_CONFIG.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _write_config(cfg: dict) -> None:
    _USER_DIR.mkdir(parents=True, exist_ok=True)
    _CONFIG.write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _language() -> str:
    ui = (_read_config().get("ui") or {})
    return "en" if str(ui.get("language", "zh")).lower().startswith("en") else "zh"


class WindowsMainWindow:
    def __init__(self, *, history: History, insert_text, reload_config, notify):
        self._history = history
        self._memo = MemoStore()
        self._insert_text = insert_text
        self._reload_config = reload_config
        self._notify = notify
        self._thread: threading.Thread | None = None
        self._queue: queue.Queue[str] = queue.Queue()
        self._root: tk.Tk | None = None
        self._history_rows: list[dict] = []
        self._memo_keys: list[str] = []
        self._vars: dict[str, tk.StringVar] = {}

    def show(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, daemon=True, name="WindowsMainWindow")
            self._thread.start()
            return
        self._queue.put("show")

    def stop(self) -> None:
        self._queue.put("stop")

    def _run(self) -> None:
        self._root = tk.Tk()
        self._root.title("Voice Keyboard")
        self._root.geometry("920x620")
        self._root.minsize(820, 520)
        self._root.protocol("WM_DELETE_WINDOW", self._hide)
        self._build()
        self._poll_queue()
        self._root.mainloop()

    def _poll_queue(self) -> None:
        root = self._root
        if root is None:
            return
        while True:
            try:
                msg = self._queue.get_nowait()
            except queue.Empty:
                break
            if msg == "show":
                self._show_root()
            elif msg == "stop":
                root.destroy()
                return
        root.after(150, self._poll_queue)

    def _show_root(self) -> None:
        if self._root is None:
            return
        self._root.deiconify()
        self._root.lift()
        self._root.focus_force()
        self.refresh_all()

    def _hide(self) -> None:
        if self._root is not None:
            self._root.withdraw()

    def _t(self, zh: str, en: str) -> str:
        return en if _language() == "en" else zh

    def _build(self) -> None:
        root = self._root
        if root is None:
            return
        outer = ttk.Frame(root, padding=10)
        outer.pack(fill="both", expand=True)
        self._tabs = ttk.Notebook(outer)
        self._tabs.pack(fill="both", expand=True)
        self._build_overview_tab()
        self._build_history_tab()
        self._build_memo_tab()
        self._build_hotkeys_tab()
        self._build_config_tab()
        self._build_check_tab()
        self.refresh_all()

    def _tab(self, zh: str, en: str) -> ttk.Frame:
        frame = ttk.Frame(self._tabs, padding=12)
        self._tabs.add(frame, text=self._t(zh, en))
        return frame

    def _build_overview_tab(self) -> None:
        tab = self._tab("\u6982\u89c8", "Overview")
        self._overview = tk.Text(tab, height=18, wrap="word")
        self._overview.pack(fill="both", expand=True)
        buttons = ttk.Frame(tab)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text=self._t("\u6253\u5f00\u914d\u7f6e", "Open Config"), command=self._open_config_file).pack(side="left")
        ttk.Button(buttons, text=self._t("\u6253\u5f00\u914d\u7f6e\u76ee\u5f55", "Open Config Folder"), command=self._open_config_dir).pack(side="left", padx=4)
        ttk.Button(buttons, text=self._t("\u5237\u65b0", "Refresh"), command=self.refresh_all).pack(side="right")

    def _build_history_tab(self) -> None:
        tab = self._tab("\u5386\u53f2\u8bb0\u5f55", "History")
        toolbar = ttk.Frame(tab)
        toolbar.pack(fill="x")
        self._history_search = tk.StringVar()
        ttk.Label(toolbar, text=self._t("\u641c\u7d22", "Search")).pack(side="left")
        ttk.Entry(toolbar, textvariable=self._history_search, width=28).pack(side="left", padx=6)
        ttk.Button(toolbar, text=self._t("\u5237\u65b0", "Refresh"), command=self._refresh_history).pack(side="left")
        ttk.Button(toolbar, text=self._t("\u590d\u5236", "Copy"), command=self._copy_history).pack(side="left", padx=4)
        ttk.Button(toolbar, text=self._t("\u518d\u6b21\u8f93\u5165", "Insert Again"), command=self._insert_history).pack(side="left")
        ttk.Button(toolbar, text=self._t("\u6253\u5f00\u6587\u4ef6", "Open File"), command=self._open_history_file).pack(side="right")

        cols = ("time", "mode", "status", "text")
        self._history_tree = ttk.Treeview(tab, columns=cols, show="headings", height=18)
        for col, width in (("time", 150), ("mode", 90), ("status", 90), ("text", 560)):
            self._history_tree.heading(col, text=col)
            self._history_tree.column(col, width=width, anchor="w")
        self._history_tree.pack(fill="both", expand=True, pady=(8, 0))
        self._history_tree.bind("<Double-1>", lambda _event: self._insert_history())

    def _build_memo_tab(self) -> None:
        tab = self._tab("\u8bb0\u5fc6\u5e93", "Memo Library")
        body = ttk.PanedWindow(tab, orient="horizontal")
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body)
        body.add(left, weight=1)
        ttk.Button(left, text=self._t("\u5237\u65b0", "Refresh"), command=self._refresh_memo).pack(fill="x")
        self._memo_list = tk.Listbox(left, height=20)
        self._memo_list.pack(fill="both", expand=True, pady=(8, 0))
        self._memo_list.bind("<<ListboxSelect>>", lambda _event: self._load_selected_memo())

        right = ttk.Frame(body)
        body.add(right, weight=3)
        ttk.Label(right, text=self._t("\u540d\u79f0", "Name")).pack(anchor="w")
        self._memo_key = tk.StringVar()
        ttk.Entry(right, textvariable=self._memo_key).pack(fill="x", pady=(0, 8))
        ttk.Label(right, text=self._t("\u5185\u5bb9", "Value")).pack(anchor="w")
        self._memo_text = tk.Text(right, height=18, wrap="word")
        self._memo_text.pack(fill="both", expand=True)
        buttons = ttk.Frame(right)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text=self._t("\u65b0\u5efa", "New"), command=self._new_memo).pack(side="left")
        ttk.Button(buttons, text=self._t("\u4fdd\u5b58", "Save"), command=self._save_memo).pack(side="left", padx=4)
        ttk.Button(buttons, text=self._t("\u5220\u9664", "Delete"), command=self._delete_memo).pack(side="left")
        ttk.Button(buttons, text=self._t("\u590d\u5236", "Copy"), command=self._copy_memo).pack(side="left", padx=4)
        ttk.Button(buttons, text=self._t("\u63d2\u5165", "Insert"), command=self._insert_memo).pack(side="left")
        ttk.Button(buttons, text=self._t("\u6253\u5f00\u6587\u4ef6", "Open File"), command=self._open_memo_file).pack(side="right")

    def _build_hotkeys_tab(self) -> None:
        tab = self._tab("\u5feb\u6377\u952e", "Hotkeys")
        form = ttk.Frame(tab)
        form.pack(anchor="nw")
        self._vars["ptt_key"] = tk.StringVar()
        self._vars["ai_key"] = tk.StringVar()
        self._combo_row(form, 0, self._t("\u8bed\u97f3\u8f6c\u6587\u5b57\u5feb\u6377\u952e", "Dictation hotkey"), "ptt_key")
        self._combo_row(form, 1, self._t("AI \u529f\u80fd\u5feb\u6377\u952e", "AI hotkey"), "ai_key")
        ttk.Button(form, text=self._t("\u4fdd\u5b58\u5e76\u91cd\u8f7d", "Save and Reload"), command=self._save_hotkeys).grid(row=2, column=1, sticky="w", pady=14)

    def _combo_row(self, parent, row: int, label: str, key: str) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=6)
        values = [self._hotkey_label(value) for value, _en, _zh in _HOTKEY_OPTIONS]
        box = ttk.Combobox(parent, textvariable=self._vars[key], values=values, width=24, state="readonly")
        box.grid(row=row, column=1, sticky="w", pady=6)

    def _build_config_tab(self) -> None:
        tab = self._tab("\u914d\u7f6e", "Config")
        form = ttk.Frame(tab)
        form.pack(anchor="nw", fill="x")
        fields = [
            ("ui.language", self._t("\u8bed\u8a00", "Language")),
            ("stt.provider", "STT provider"),
            ("stt.model", "STT model"),
            ("llm.provider", "LLM provider"),
            ("llm.model", "LLM model"),
            ("typing.method", self._t("\u6253\u5b57\u65b9\u5f0f", "Typing method")),
            ("audio.device", self._t("\u9ea6\u514b\u98ce\u8bbe\u5907", "Microphone")),
        ]
        for row, (path, label) in enumerate(fields):
            self._vars[path] = tk.StringVar()
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
            ttk.Entry(form, textvariable=self._vars[path], width=42).grid(row=row, column=1, sticky="ew", pady=5)
        form.columnconfigure(1, weight=1)
        ttk.Button(form, text=self._t("\u4fdd\u5b58\u5e76\u91cd\u8f7d", "Save and Reload"), command=self._save_config).grid(row=len(fields), column=1, sticky="w", pady=14)

    def _build_check_tab(self) -> None:
        tab = self._tab("\u8fd0\u884c\u81ea\u68c0", "Self Check")
        self._check = tk.Text(tab, height=20, wrap="word")
        self._check.pack(fill="both", expand=True)
        ttk.Button(tab, text=self._t("\u91cd\u65b0\u68c0\u67e5", "Run Check"), command=self._refresh_check).pack(anchor="e", pady=(8, 0))

    def refresh_all(self) -> None:
        self._refresh_overview()
        self._refresh_history()
        self._refresh_memo()
        self._load_config_fields()
        self._refresh_check()

    def _refresh_overview(self) -> None:
        cfg = _read_config()
        audio = cfg.get("audio") or {}
        stt = cfg.get("stt") or {}
        llm = cfg.get("llm") or {}
        rows = [
            "Status: running",
            f"Language: {_language()}",
            f"Dictation hotkey: {audio.get('ptt_key', '')}",
            f"AI hotkey: {audio.get('ai_key', '')}",
            f"STT: {stt.get('provider', '')} {stt.get('model', '')}",
            f"LLM: {llm.get('provider', '')} {llm.get('model', '')}",
            f"Config: {_CONFIG}",
            f"History: {self._history.path}",
            f"Memo: {_USER_DIR / 'memo.json'}",
        ]
        self._set_text(self._overview, "\n".join(rows))

    def _refresh_history(self) -> None:
        query = self._history_search.get().strip().lower() if hasattr(self, "_history_search") else ""
        rows = list(reversed(self._history.load(limit=300)))
        if query:
            rows = [row for row in rows if query in str(row.get("text") or "").lower()]
        self._history_rows = rows
        self._history_tree.delete(*self._history_tree.get_children())
        for index, row in enumerate(rows):
            ts = row.get("ts") or 0
            stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(ts))) if ts else ""
            text = " ".join(str(row.get("text") or "").split())
            self._history_tree.insert("", "end", iid=str(index), values=(stamp, row.get("mode", ""), row.get("status", ""), text))

    def _selected_history_text(self) -> str:
        selected = self._history_tree.selection()
        if not selected:
            return ""
        row = self._history_rows[int(selected[0])]
        return str(row.get("text") or "")

    def _copy_history(self) -> None:
        self._copy_text(self._selected_history_text())

    def _insert_history(self) -> None:
        text = self._selected_history_text()
        if text:
            self._insert_text(text, self._t("\u5df2\u63d2\u5165\u5386\u53f2\u8bb0\u5f55", "History inserted"))

    def _refresh_memo(self) -> None:
        self._memo = MemoStore()
        self._memo_keys = sorted(self._memo.keys())
        self._memo_list.delete(0, "end")
        for key in self._memo_keys:
            self._memo_list.insert("end", key)

    def _load_selected_memo(self) -> None:
        sel = self._memo_list.curselection()
        if not sel:
            return
        key = self._memo_keys[sel[0]]
        self._memo_key.set(key)
        self._set_text(self._memo_text, self._memo.get(key) or "")

    def _new_memo(self) -> None:
        self._memo_key.set("")
        self._set_text(self._memo_text, "")

    def _save_memo(self) -> None:
        key = self._memo_key.get().strip()
        value = self._memo_text.get("1.0", "end").strip()
        if not key:
            messagebox.showwarning("Voice Keyboard", self._t("\u8bf7\u586b\u5199\u540d\u79f0", "Name is required"))
            return
        self._memo.save(key, value)
        self._refresh_memo()
        self._notify_text(self._t("\u5df2\u4fdd\u5b58\u8bb0\u5fc6", "Memo saved"))

    def _delete_memo(self) -> None:
        key = self._memo_key.get().strip()
        if not key:
            return
        if messagebox.askyesno("Voice Keyboard", self._t("\u786e\u5b9a\u5220\u9664\u8fd9\u6761\u8bb0\u5fc6\uff1f", "Delete this memo?")):
            self._memo.delete(key)
            self._new_memo()
            self._refresh_memo()
            self._notify_text(self._t("\u5df2\u5220\u9664\u8bb0\u5fc6", "Memo deleted"))

    def _copy_memo(self) -> None:
        self._copy_text(self._memo_text.get("1.0", "end").strip())

    def _insert_memo(self) -> None:
        text = self._memo_text.get("1.0", "end").strip()
        if text:
            self._insert_text(text, self._t("\u5df2\u63d2\u5165\u8bb0\u5fc6", "Memo inserted"))

    def _load_config_fields(self) -> None:
        cfg = _read_config()
        audio = cfg.get("audio") or {}
        self._vars["ptt_key"].set(self._hotkey_label(str(audio.get("ptt_key", ""))))
        self._vars["ai_key"].set(self._hotkey_label(str(audio.get("ai_key", ""))))
        for path, var in self._vars.items():
            if path in ("ptt_key", "ai_key"):
                continue
            head, key = path.split(".", 1)
            value = (cfg.get(head) or {}).get(key, "")
            var.set(str(value))

    def _save_hotkeys(self) -> None:
        cfg = _read_config()
        audio = cfg.setdefault("audio", {})
        audio["ptt_key"] = self._hotkey_value(self._vars["ptt_key"].get())
        audio["ai_key"] = self._hotkey_value(self._vars["ai_key"].get())
        _write_config(cfg)
        self._reload_config(False)
        self._notify_text(self._t("\u5feb\u6377\u952e\u5df2\u4fdd\u5b58", "Hotkeys saved"))

    def _save_config(self) -> None:
        cfg = _read_config()
        for path, var in self._vars.items():
            if path in ("ptt_key", "ai_key"):
                continue
            head, key = path.split(".", 1)
            cfg.setdefault(head, {})
            value = var.get().strip()
            if value:
                cfg[head][key] = value
        _write_config(cfg)
        self._reload_config(False)
        self._notify_text(self._t("\u914d\u7f6e\u5df2\u4fdd\u5b58", "Config saved"))

    def _refresh_check(self) -> None:
        rows = []
        rows.append(self._check_line(_CONFIG.exists(), "config.yaml", str(_CONFIG)))
        rows.append(self._check_line(os.access(_USER_DIR, os.W_OK), "config folder writable", str(_USER_DIR)))
        rows.append(self._check_line(self._history.path.exists(), "history file", str(self._history.path)))
        rows.append(self._check_line((_USER_DIR / "memo.json").exists(), "memo file", str(_USER_DIR / "memo.json")))
        cfg = _read_config()
        stt_key = bool((cfg.get("stt") or {}).get("api_key"))
        llm_key = bool((cfg.get("llm") or {}).get("api_key"))
        rows.append(self._check_line(stt_key, "STT API key configured", "hidden"))
        rows.append(self._check_line(llm_key, "LLM API key configured", "hidden"))
        try:
            import sounddevice as sd
            count = len([d for d in sd.query_devices() if d.get("max_input_channels", 0) > 0])
            rows.append(self._check_line(count > 0, "microphones", str(count)))
        except Exception as e:
            rows.append(self._check_line(False, "microphones", str(e)))
        self._set_text(self._check, "\n".join(rows))

    @staticmethod
    def _check_line(ok: bool, name: str, detail: str) -> str:
        return f"[{'OK' if ok else '!!'}] {name}: {detail}"

    def _open_history_file(self) -> None:
        self._history.path.parent.mkdir(parents=True, exist_ok=True)
        self._history.path.touch(exist_ok=True)
        os.startfile(str(self._history.path))

    def _open_memo_file(self) -> None:
        path = _USER_DIR / "memo.json"
        _USER_DIR.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("{}", encoding="utf-8")
        os.startfile(str(path))

    def _open_config_file(self) -> None:
        _USER_DIR.mkdir(parents=True, exist_ok=True)
        if not _CONFIG.exists():
            _CONFIG.write_text("{}", encoding="utf-8")
        os.startfile(str(_CONFIG))

    def _open_config_dir(self) -> None:
        _USER_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(_USER_DIR))

    def _copy_text(self, text: str) -> None:
        if not text or self._root is None:
            return
        self._root.clipboard_clear()
        self._root.clipboard_append(text)
        self._notify_text(self._t("\u5df2\u590d\u5236", "Copied"))

    def _notify_text(self, message: str) -> None:
        self._notify(message)

    @staticmethod
    def _hotkey_label(value: str) -> str:
        for key, en, zh in _HOTKEY_OPTIONS:
            if key == value:
                return en if _language() == "en" else zh
        return value

    @staticmethod
    def _hotkey_value(label: str) -> str:
        for key, en, zh in _HOTKEY_OPTIONS:
            if label in (key, en, zh):
                return key
        return label

    @staticmethod
    def _set_text(widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
