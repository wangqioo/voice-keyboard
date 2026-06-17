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
from agent.intent_diagnostics import format_evaluation_mismatches, save_diagnostics_review, summarize_diagnostics
from agent.intent_evaluation import evaluate_reviewed_samples
from agent.intent_loop import run_training_loop
from agent.intent_model_ui import get_model_status, rollback_model_for_ui, train_local_model_for_ui
from agent.intent_sync import sync_local_corrected_intents
from agent.intent_training import load_samples
from agent.memo import MemoRecord
from agent.memo_store import MemoStore


_USER_DIR = Path.home() / ".voice-keyboard"
_CONFIG = _USER_DIR / "config.yaml"
_INTENT_OVERRIDES = _USER_DIR / "intent_overrides.jsonl"
_INTENT_MODEL_REGISTRY = _USER_DIR / "intent_models"
_INTENT_MODEL_REPORTS = _USER_DIR / "intent_eval_reports"
_HOTKEY_OPTIONS = [
    ("shift_r", "Right Shift", "\u53f3 Shift"),
    ("alt_r", "Right Alt", "\u53f3 Alt"),
    ("alt_gr", "AltGr", "AltGr"),
    ("ctrl_r", "Right Ctrl", "\u53f3 Ctrl"),
    ("f8", "F8", "F8"),
    ("f9", "F9", "F9"),
    ("f10", "F10", "F10"),
]
_CORRECTED_INTENT_TYPES = (
    "",
    "shortcut",
    "undo",
    "delete",
    "edit",
    "write",
    "memo_save",
    "memo_recall",
    "memo_delete",
    "memo_list",
    "chat",
)


_REVIEW_LABEL_DISPLAY = {
    "": "未标记",
    "correct": "判断正确",
    "wrong_intent": "操作类型错了",
    "wrong_target": "操作对象错了",
    "unsafe_should_confirm": "应该先确认",
    "missing_shortcut": "缺少快捷键",
    "unclear": "说法不清楚",
}
_REVIEW_DISPLAY_TO_LABEL = {label: value for value, label in _REVIEW_LABEL_DISPLAY.items()}
_INTENT_TYPE_DISPLAY = {
    "": "不填写纠正",
    "shortcut": "执行快捷键/菜单操作",
    "undo": "撤销",
    "delete": "删除文字",
    "edit": "编辑文字",
    "write": "输入文字",
    "memo_save": "保存到记忆库",
    "memo_recall": "读取记忆库",
    "memo_delete": "删除记忆",
    "memo_list": "列出记忆",
    "chat": "只聊天回答",
}
_INTENT_DISPLAY_TO_TYPE = {label: value for value, label in _INTENT_TYPE_DISPLAY.items()}

def build_corrected_intent(intent_type: str, value: str = "", extra: str = "") -> dict | None:
    intent_type = str(intent_type or "").strip()
    if not intent_type:
        return None
    value = str(value or "").strip()
    extra = str(extra or "").strip()
    out = {"type": intent_type}
    if intent_type == "shortcut":
        out["name"] = value
    elif intent_type in {"memo_save", "memo_recall", "memo_delete"}:
        out["key"] = value
        if intent_type == "memo_save" and extra:
            out["value"] = extra
    elif intent_type == "chat":
        out["reply"] = value
    return out


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


def _split_words(raw: str) -> list[str]:
    text = str(raw or "")
    for sep in ("\uff0c", "\u3001", "\n", "\t"):
        text = text.replace(sep, ",")
    return [item.strip() for item in text.split(",") if item.strip()]


def _memo_alias_text(record: MemoRecord | None) -> str:
    if record is None:
        return ""
    return ", ".join(record.aliases)


def _language() -> str:
    ui = (_read_config().get("ui") or {})
    return "en" if str(ui.get("language", "zh")).lower().startswith("en") else "zh"



def intent_training_server_config() -> dict:
    training = ((_read_config().get("instruction_mode") or {}).get("intent_training") or {})
    return {
        "server": str(training.get("server") or os.getenv("INTENT_TRAINING_SERVER", "")).strip(),
        "token": str(training.get("token") or os.getenv("INTENT_TRAINING_UPLOAD_TOKEN", "")).strip(),
    }


def save_intent_training_server_config(server: str, token: str) -> None:
    cfg = _read_config()
    training = cfg.setdefault("instruction_mode", {}).setdefault("intent_training", {})
    training["server"] = str(server or "").strip()
    training["token"] = str(token or "").strip()
    _write_config(cfg)


def format_sync_evaluation_message(*, sync: dict, evaluation: dict, remote: bool = False, upload: dict | None = None) -> str:
    prefix = "Remote sync" if remote else "Local sync"
    inserted = f" inserted={(upload or {}).get('inserted', 0)}" if remote else ""
    return (
        f"{prefix} complete{inserted} synced={sync.get('synced', 0)} "
        f"skipped={sync.get('skipped', 0)} compacted={sync.get('compacted', 0)} "
        f"accuracy={evaluation.get('accuracy_label', '0.0%')} "
        f"wrong={evaluation.get('wrong', 0)} total={evaluation.get('total', 0)}"
    )

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
        self._intent_rows: list[tuple[int, dict]] = []
        self._memo_keys: list[str] = []
        self._memo_snapshot: dict[str, tuple[str, str]] = {}
        self._memo_poll_after_id = None
        self._vars: dict[str, tk.StringVar] = {}
        self._history.add_listener(lambda _entry: self._queue.put("history"))

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
        self._root.geometry("1180x760")
        self._root.minsize(980, 640)
        self._root.protocol("WM_DELETE_WINDOW", self._hide)
        self._configure_style()
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
            elif msg == "history" and hasattr(self, "_history_tree"):
                self._refresh_history()
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

    def _configure_style(self) -> None:
        style = ttk.Style(self._root)
        for theme in ("vista", "xpnative", "winnative"):
            if theme in style.theme_names():
                try:
                    style.theme_use(theme)
                    break
                except tk.TclError:
                    pass
        style.configure("TNotebook", tabmargins=(6, 6, 6, 0))
        style.configure("TNotebook.Tab", padding=(16, 8), font=("Segoe UI", 10))
        style.map("TNotebook.Tab", font=[("selected", ("Segoe UI", 10, "bold"))])

    def _build(self) -> None:
        root = self._root
        if root is None:
            return
        outer = ttk.Frame(root, padding=(12, 10, 12, 12))
        outer.pack(fill="both", expand=True)
        self._tabs = ttk.Notebook(outer)
        self._tabs.pack(fill="both", expand=True)
        self._build_overview_tab()
        self._build_history_tab()
        self._build_intent_diagnostics_tab()
        self._build_memo_tab()
        self._build_hotkeys_tab()
        self._build_config_tab()
        self._build_check_tab()
        self.refresh_all()

    def _tab(self, zh: str, en: str) -> ttk.Frame:
        frame = ttk.Frame(self._tabs, padding=(14, 16, 14, 14))
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
        ttk.Label(toolbar, text=self._t("\u641c\u7d22\u8bf4\u8fc7\u7684\u8bdd", "Search text")).pack(side="left")
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

    def _build_intent_diagnostics_tab(self) -> None:
        tab = self._tab("AI \u6307\u4ee4\u7ea0\u9519", "AI Command Review")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(4, weight=1)

        filters = ttk.LabelFrame(tab, text=self._t("\u67e5\u627e\u8bb0\u5f55", "Find Records"), padding=(10, 8))
        filters.grid(row=0, column=0, sticky="ew")
        filters.columnconfigure(1, weight=1)
        self._intent_search = tk.StringVar()
        ttk.Label(filters, text=self._t("\u641c\u7d22\u8bf4\u8fc7\u7684\u8bdd", "Search text")).grid(row=0, column=0, sticky="w")
        ttk.Entry(filters, textvariable=self._intent_search).grid(row=0, column=1, sticky="ew", padx=(6, 14))
        self._intent_type_filter = tk.StringVar()
        ttk.Label(filters, text=self._t("\u7cfb\u7edf\u5224\u65ad\u4e3a", "Detected as")).grid(row=0, column=2, sticky="w")
        ttk.Combobox(
            filters,
            textvariable=self._intent_type_filter,
            values=("", "shortcut", "delete", "chat", "memo_save", "memo_recall", "edit", "write"),
            width=16,
        ).grid(row=0, column=3, sticky="w", padx=(6, 14))
        self._intent_review_filter = tk.StringVar(value="all")
        ttk.Label(filters, text=self._t("\u662f\u5426\u770b\u8fc7", "Review status")).grid(row=0, column=4, sticky="w")
        ttk.Combobox(
            filters,
            textvariable=self._intent_review_filter,
            values=("all", "reviewed", "unreviewed"),
            width=14,
            state="readonly",
        ).grid(row=0, column=5, sticky="w", padx=(6, 14))
        ttk.Button(filters, text=self._t("\u5237\u65b0", "Refresh"), command=self._refresh_intent_samples).grid(row=0, column=6, sticky="e")
        ttk.Button(filters, text=self._t("\u6253\u5f00\u6587\u4ef6", "Open File"), command=self._open_intent_samples_file).grid(row=0, column=7, sticky="e", padx=(6, 0))

        actions = ttk.LabelFrame(tab, text=self._t("\u7ea0\u9519\u548c\u8bad\u7ec3", "Fix and Train"), padding=(10, 8))
        actions.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        for col in range(8):
            actions.columnconfigure(col, weight=1 if col in (4, 6) else 0)
        ttk.Button(actions, text=self._t("\u66f4\u65b0\u7ea0\u9519\u5e76\u770b\u51c6\u786e\u7387", "Update fixes + accuracy"), command=self._sync_and_evaluate_intents).grid(row=0, column=0, sticky="w")
        ttk.Button(actions, text=self._t("\u770b\u8fd8\u5224\u9519\u7684\u8bdd", "Show remaining mistakes"), command=self._show_intent_mismatches).grid(row=0, column=1, sticky="w", padx=(6, 0))
        ttk.Button(actions, text=self._t("\u7528\u7ea0\u9519\u8bad\u7ec3", "Train from fixes"), command=self._train_intent_model).grid(row=0, column=2, sticky="w", padx=(14, 0))
        ttk.Button(actions, text=self._t("\u64a4\u56de\u4e0a\u6b21\u8bad\u7ec3", "Undo last training"), command=self._rollback_intent_model).grid(row=0, column=3, sticky="w", padx=(6, 0))
        ttk.Label(actions, text=self._t("\u8bad\u7ec3\u670d\u52a1\u5668", "Training server")).grid(row=0, column=4, sticky="e", padx=(14, 4))
        self._intent_server = tk.StringVar()
        ttk.Entry(actions, textvariable=self._intent_server).grid(row=0, column=5, sticky="ew")
        ttk.Label(actions, text=self._t("\u5bc6\u94a5", "Token")).grid(row=0, column=6, sticky="e", padx=(8, 4))
        self._intent_token = tk.StringVar()
        ttk.Entry(actions, textvariable=self._intent_token, show="*").grid(row=0, column=7, sticky="ew")
        ttk.Button(actions, text=self._t("\u4fdd\u5b58\u8bad\u7ec3\u670d\u52a1\u5668", "Save training server"), command=self._save_intent_server_config).grid(row=0, column=8, sticky="e", padx=(6, 0))

        status = ttk.Frame(tab)
        status.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        status.columnconfigure(0, weight=1)
        self._intent_summary = tk.StringVar()
        ttk.Label(status, textvariable=self._intent_summary, anchor="w").grid(row=0, column=0, sticky="ew")
        self._intent_model_status = tk.StringVar()
        ttk.Label(status, textvariable=self._intent_model_status, anchor="w").grid(row=1, column=0, sticky="ew", pady=(2, 0))

        body = ttk.PanedWindow(tab, orient="vertical")
        body.grid(row=4, column=0, sticky="nsew", pady=(8, 0))

        list_frame = ttk.Frame(body)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        body.add(list_frame, weight=3)
        cols = ("time", "type", "source", "confidence", "status", "review", "text")
        self._intent_tree = ttk.Treeview(list_frame, columns=cols, show="headings", height=13)
        widths = (
            ("time", 150), ("type", 110), ("source", 95), ("confidence", 95),
            ("status", 90), ("review", 150), ("text", 520),
        )
        for col, width in widths:
            self._intent_tree.heading(col, text=col)
            self._intent_tree.column(col, width=width, anchor="w", stretch=(col == "text"))
        self._intent_tree.grid(row=0, column=0, sticky="nsew")
        intent_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self._intent_tree.yview)
        intent_scroll.grid(row=0, column=1, sticky="ns")
        self._intent_tree.configure(yscrollcommand=intent_scroll.set)
        self._intent_tree.bind("<<TreeviewSelect>>", lambda _event: self._load_selected_intent_sample())

        detail = ttk.Frame(body)
        detail.columnconfigure(0, weight=1)
        detail.columnconfigure(1, weight=2)
        detail.rowconfigure(1, weight=1)
        body.add(detail, weight=2)

        form = ttk.LabelFrame(detail, text=self._t("\u8fd9\u53e5\u8bdd\u5e94\u8be5\u600e\u4e48\u505a", "What should this command do?"), padding=(10, 8))
        form.grid(row=0, column=0, columnspan=2, sticky="ew")
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)
        ttk.Label(form, text=self._t("\u5224\u65ad\u5bf9\u4e0d\u5bf9", "Was it right?")).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        self._intent_review_label = tk.StringVar()
        self._intent_review_box = ttk.Combobox(
            form,
            textvariable=self._intent_review_label,
            values=tuple(_REVIEW_LABEL_DISPLAY.values()),
            width=26,
            state="readonly",
        )
        self._intent_review_box.grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Label(form, text=self._t("\u6b63\u786e\u64cd\u4f5c\u7c7b\u578b", "Correct action type")).grid(row=0, column=2, sticky="w", padx=(14, 8), pady=4)
        self._intent_corrected_type = tk.StringVar()
        self._intent_corrected_box = ttk.Combobox(
            form,
            textvariable=self._intent_corrected_type,
            values=tuple(_INTENT_TYPE_DISPLAY.values()),
            width=22,
            state="readonly",
        )
        self._intent_corrected_box.grid(row=0, column=3, sticky="ew", pady=4)
        ttk.Label(form, text=self._t("\u64cd\u4f5c\u540d / \u8bb0\u5fc6\u540d / \u56de\u590d\u5185\u5bb9", "Action / memory / reply")).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        self._intent_corrected_value = tk.StringVar()
        ttk.Entry(form, textvariable=self._intent_corrected_value).grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Label(form, text=self._t("\u8981\u8bb0\u4f4f\u7684\u5185\u5bb9", "Memory value")).grid(row=1, column=2, sticky="w", padx=(14, 8), pady=4)
        self._intent_corrected_extra = tk.StringVar()
        ttk.Entry(form, textvariable=self._intent_corrected_extra).grid(row=1, column=3, sticky="ew", pady=4)
        ttk.Button(form, text=self._t("\u4fdd\u5b58\u8fd9\u6761\u7ea0\u9519", "Save this fix"), command=self._save_intent_review).grid(row=0, column=4, sticky="ew", padx=(12, 0), pady=4)
        ttk.Button(form, text=self._t("\u590d\u5236\u8fd9\u53e5\u8bdd", "Copy command"), command=self._copy_intent_text).grid(row=1, column=4, sticky="ew", padx=(12, 0), pady=4)

        note_frame = ttk.LabelFrame(detail, text=self._t("\u5907\u6ce8\uff08\u53ef\u9009\uff09", "Note (optional)"), padding=(8, 6))
        note_frame.grid(row=1, column=0, sticky="nsew", pady=(8, 0), padx=(0, 6))
        note_frame.columnconfigure(0, weight=1)
        note_frame.rowconfigure(0, weight=1)
        self._intent_review_note = tk.Text(note_frame, height=7, wrap="word")
        self._intent_review_note.grid(row=0, column=0, sticky="nsew")

        detail_frame = ttk.LabelFrame(detail, text=self._t("\u7cfb\u7edf\u5f53\u65f6\u600e\u4e48\u5224\u65ad", "How the system judged it"), padding=(8, 6))
        detail_frame.grid(row=1, column=1, sticky="nsew", pady=(8, 0), padx=(6, 0))
        detail_frame.columnconfigure(0, weight=1)
        detail_frame.rowconfigure(0, weight=1)
        self._intent_detail = tk.Text(detail_frame, height=7, wrap="word")
        self._intent_detail.grid(row=0, column=0, sticky="nsew")
        detail_scroll = ttk.Scrollbar(detail_frame, orient="vertical", command=self._intent_detail.yview)
        detail_scroll.grid(row=0, column=1, sticky="ns")
        self._intent_detail.configure(yscrollcommand=detail_scroll.set)
    def _build_memo_tab(self) -> None:
        tab = self._tab("\u8bb0\u5fc6\u5e93", "Memo Library")
        trigger_box = ttk.LabelFrame(tab, text=self._t("备忘录触发词", "Memo trigger words"), padding=(8, 6))
        trigger_box.pack(fill="x", pady=(0, 8))
        trigger_box.columnconfigure(1, weight=1)
        trigger_fields = [
            ("memo_save_words", self._t("输入关键词", "Save words")),
            ("memo_lookup_actions", self._t("查询动作词", "Lookup actions")),
            ("memo_wake_words", self._t("记忆唤醒词", "Wake words")),
            ("memo_delete_words", self._t("删除关键词", "Delete words")),
        ]
        for row, (key, label) in enumerate(trigger_fields):
            self._vars[key] = tk.StringVar()
            ttk.Label(trigger_box, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
            ttk.Entry(trigger_box, textvariable=self._vars[key]).grid(row=row, column=1, sticky="ew", pady=3)
        ttk.Button(trigger_box, text=self._t("保存关键词并重载", "Save words and reload"), command=self._save_memo_triggers).grid(row=0, column=2, rowspan=2, sticky="ew", padx=(10, 0))

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
        ttk.Label(right, text=self._t("\u522b\u540d", "Aliases")).pack(anchor="w")
        self._memo_aliases = tk.StringVar()
        ttk.Entry(right, textvariable=self._memo_aliases).pack(fill="x", pady=(0, 8))
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
        self._refresh_intent_samples()
        self._load_intent_server_fields()
        self._refresh_intent_model_status()
        self._refresh_memo()
        self._load_memo_trigger_fields()
        self._schedule_memo_poll()
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

    def _intent_samples_path(self) -> Path:
        cfg = _read_config()
        instruction = cfg.get("instruction_mode") or {}
        training = instruction.get("intent_training") or {}
        return Path(str(training.get("path") or (_USER_DIR / "intent_samples.jsonl"))).expanduser()

    def _intent_overrides_path(self) -> Path:
        cfg = _read_config()
        instruction = cfg.get("instruction_mode") or {}
        fallbacks = instruction.get("fallbacks") or {}
        return Path(str(fallbacks.get("intent_overrides_path") or _INTENT_OVERRIDES)).expanduser()

    def _refresh_intent_samples(self) -> None:
        if not hasattr(self, "_intent_tree"):
            return
        path = self._intent_samples_path()
        query = self._intent_search.get().strip().lower() if hasattr(self, "_intent_search") else ""
        intent_type = self._intent_type_filter.get().strip() if hasattr(self, "_intent_type_filter") else ""
        review_filter = self._intent_review_filter.get().strip() if hasattr(self, "_intent_review_filter") else "all"
        rows = list(enumerate(load_samples(path, limit=0)))
        if query:
            rows = [item for item in rows if query in str(item[1].get("text") or "").lower()]
        if intent_type:
            rows = [item for item in rows if str(item[1].get("intent_type") or "") == intent_type]
        if review_filter == "reviewed":
            rows = [item for item in rows if str(item[1].get("review_label") or "")]
        elif review_filter == "unreviewed":
            rows = [item for item in rows if not str(item[1].get("review_label") or "")]
        self._intent_rows = list(reversed(rows[-300:]))
        self._intent_tree.delete(*self._intent_tree.get_children())
        for display_index, (_file_index, row) in enumerate(self._intent_rows):
            ts = row.get("ts") or 0
            stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(ts))) if ts else ""
            text = " ".join(str(row.get("text") or "").split())
            self._intent_tree.insert("", "end", iid=str(display_index), values=(
                stamp,
                row.get("intent_type", ""),
                row.get("intent_source", ""),
                row.get("intent_confidence", ""),
                row.get("status", ""),
                row.get("review_label", ""),
                text,
            ))
        self._refresh_intent_summary()
        self._clear_intent_detail()

    def _refresh_intent_summary(self) -> None:
        if not hasattr(self, "_intent_summary"):
            return
        try:
            summary = summarize_diagnostics(self._intent_samples_path(), override_path=self._intent_overrides_path())
            evaluation = summary.get("evaluation", {}) or {}
            wrong_by_intent = summary.get("wrong_by_intent", {}) or {}
            wrong_text = ", ".join(f"{key}:{value}" for key, value in sorted(wrong_by_intent.items())) or "-"
            self._intent_summary.set(
                f"共 {summary.get('total', 0)} 条 / 已看过 {summary.get('reviewed', 0)} 条 / "
                f"已纠正 {summary.get('corrected', 0)} 条 / 已生效 {summary.get('override_covered', 0)} 条 / "
                f"回放准确率 {evaluation.get('accuracy_label', '0.0%')} / 还错 {evaluation.get('wrong', 0)} 条 / 错误分布 {wrong_text}"
            )
        except Exception as e:
            self._intent_summary.set(f"Intent summary failed: {e}")

    def _refresh_intent_model_status(self) -> None:
        if not hasattr(self, "_intent_model_status"):
            return
        try:
            status = get_model_status(_INTENT_MODEL_REGISTRY)
            current = status.get("current_version") or "-"
            self._intent_model_status.set(f"当前训练版本：{current} / 版本数：{status.get('version_count', 0)} / 评测报告：{_INTENT_MODEL_REPORTS}")
        except Exception as e:
            self._intent_model_status.set(f"Model status failed: {e}")

    def _load_intent_server_fields(self) -> None:
        if not hasattr(self, "_intent_server"):
            return
        cfg = intent_training_server_config()
        self._intent_server.set(cfg["server"])
        self._intent_token.set(cfg["token"])

    def _save_intent_server_config(self) -> None:
        save_intent_training_server_config(self._intent_server.get(), self._intent_token.get())
        self._notify_text(self._t("\u8bad\u7ec3\u670d\u52a1\u5668\u5df2\u4fdd\u5b58", "Training server saved"))

    def _run_intent_worker(self, label: str, target) -> None:
        self._intent_summary.set(label)
        def worker():
            try:
                message = target()
            except Exception as e:
                if self._root is not None:
                    self._root.after(0, lambda: messagebox.showerror("Voice Keyboard", str(e)))
                return
            if self._root is not None:
                self._root.after(0, lambda: self._intent_worker_finished(message))
        threading.Thread(target=worker, daemon=True).start()

    def _intent_worker_finished(self, message: str) -> None:
        self._notify_text(message)
        self._refresh_intent_samples()
        self._refresh_intent_model_status()

    def _sync_and_evaluate_intents(self) -> None:
        def task():
            cfg = intent_training_server_config()
            if cfg["server"]:
                import requests
                report = run_training_loop(
                    sample_path=self._intent_samples_path(),
                    server=cfg["server"],
                    token=cfg["token"],
                    override_path=self._intent_overrides_path(),
                    source="windows-ui",
                    http=requests,
                )
                return format_sync_evaluation_message(sync=report["sync"], evaluation=report["evaluation"], remote=True, upload=report["upload"])
            sync = sync_local_corrected_intents(self._intent_samples_path(), override_path=self._intent_overrides_path())
            evaluation = evaluate_reviewed_samples(self._intent_samples_path(), override_path=self._intent_overrides_path())
            return format_sync_evaluation_message(sync=sync, evaluation=evaluation)
        self._run_intent_worker(self._t("\u6b63\u5728\u540c\u6b65\u5e76\u8bc4\u6d4b...", "Syncing and evaluating..."), task)

    def _show_intent_mismatches(self) -> None:
        try:
            summary = summarize_diagnostics(self._intent_samples_path(), override_path=self._intent_overrides_path())
            self._set_text(self._intent_detail, format_evaluation_mismatches(summary.get("evaluation", {})))
        except Exception as e:
            messagebox.showerror("Voice Keyboard", str(e))

    def _train_intent_model(self) -> None:
        def task():
            result = train_local_model_for_ui(
                sample_path=self._intent_samples_path(),
                registry_dir=_INTENT_MODEL_REGISTRY,
                report_dir=_INTENT_MODEL_REPORTS,
                override_path=self._intent_overrides_path(),
                min_similarity=0.8,
            )
            model = result["model"]
            evaluation = result["evaluation"]["report"]
            return f"Model trained version={model['version']} examples={model['examples']} accuracy={evaluation['accuracy_label']} report={result['evaluation']['path']}"
        self._run_intent_worker(self._t("\u6b63\u5728\u8bad\u7ec3\u6a21\u578b...", "Training model..."), task)

    def _rollback_intent_model(self) -> None:
        def task():
            result = rollback_model_for_ui(_INTENT_MODEL_REGISTRY)
            return f"Model rolled back {result['previous_version']} -> {result['version']} examples={result['examples']}"
        self._run_intent_worker(self._t("\u6b63\u5728\u56de\u6eda\u6a21\u578b...", "Rolling back model..."), task)

    def _selected_intent_row(self) -> tuple[int, dict] | None:
        selected = self._intent_tree.selection()
        if not selected:
            return None
        return self._intent_rows[int(selected[0])]

    def _load_selected_intent_sample(self) -> None:
        selected = self._selected_intent_row()
        if selected is None:
            return
        _file_index, row = selected
        self._intent_review_label.set(_REVIEW_LABEL_DISPLAY.get(str(row.get("review_label") or ""), "未标记"))
        self._set_text(self._intent_review_note, str(row.get("review_note") or ""))
        self._load_corrected_intent(row.get("corrected_intent") or {})
        detail_lines = [
            f"text: {row.get('text', '')}",
            f"type: {row.get('intent_type', '')}",
            f"name: {row.get('intent_name', '')}",
            f"key: {row.get('intent_key', '')}",
            f"source: {row.get('intent_source', '')}",
            f"confidence: {row.get('intent_confidence', '')}",
            f"cache_hit: {row.get('intent_cache_hit', '')}",
            f"app: {row.get('active_application', '')}",
            f"selection: {row.get('has_selection', False)} len={row.get('selected_length', 0)}",
            f"recent: {row.get('has_recent_text', False)} len={row.get('recent_text_length', 0)}",
            f"shortcuts: {row.get('shortcut_count', 0)}",
            f"status: {row.get('status', '')}",
            f"detail: {row.get('detail', '')}",
            f"hash: {row.get('text_hash', '')}",
        ]
        self._set_text(self._intent_detail, "\n".join(detail_lines))

    def _clear_intent_detail(self) -> None:
        if hasattr(self, "_intent_review_label"):
            self._intent_review_label.set(_REVIEW_LABEL_DISPLAY[""])
        if hasattr(self, "_intent_review_note"):
            self._set_text(self._intent_review_note, "")
        if hasattr(self, "_intent_detail"):
            self._set_text(self._intent_detail, "")

        if hasattr(self, "_intent_corrected_type"):
            self._intent_corrected_type.set(_INTENT_TYPE_DISPLAY[""])
        if hasattr(self, "_intent_corrected_value"):
            self._intent_corrected_value.set("")
        if hasattr(self, "_intent_corrected_extra"):
            self._intent_corrected_extra.set("")

    def _corrected_intent_from_fields(self) -> dict | None:
        return build_corrected_intent(
            _INTENT_DISPLAY_TO_TYPE.get(self._intent_corrected_type.get(), self._intent_corrected_type.get()),
            self._intent_corrected_value.get(),
            self._intent_corrected_extra.get(),
        )

    def _load_corrected_intent(self, corrected: dict) -> None:
        intent_type = str(corrected.get("type") or "")
        self._intent_corrected_type.set(_INTENT_TYPE_DISPLAY.get(intent_type, _INTENT_TYPE_DISPLAY[""]))
        self._intent_corrected_value.set(str(corrected.get("name") or corrected.get("key") or corrected.get("reply") or ""))
        self._intent_corrected_extra.set(str(corrected.get("value") or ""))

    def _save_intent_review(self) -> None:
        selected = self._selected_intent_row()
        if selected is None:
            return
        file_index, row = selected
        path = self._intent_samples_path()
        note = self._intent_review_note.get("1.0", "end").strip()
        row_with_index = dict(row)
        row_with_index["source_index"] = file_index
        try:
            save_diagnostics_review(
                path,
                row_with_index,
                label=_REVIEW_DISPLAY_TO_LABEL.get(self._intent_review_label.get(), self._intent_review_label.get()),
                note=note,
                corrected_intent=self._corrected_intent_from_fields(),
                override_path=self._intent_overrides_path(),
            )
        except Exception as e:
            messagebox.showerror("Voice Keyboard", str(e))
            return
        self._notify_text(self._t("\u53cd\u9988\u5df2\u4fdd\u5b58", "Feedback saved"))
        self._refresh_intent_samples()

    def _copy_intent_text(self) -> None:
        selected = self._selected_intent_row()
        if selected is None:
            return
        self._copy_text(str(selected[1].get("text") or ""))

    def _load_memo_trigger_fields(self) -> None:
        cfg = _read_config()
        triggers = (((cfg.get("instruction_mode") or {}).get("intent_fallbacks") or {}).get("memo_triggers") or {})
        defaults = {
            "memo_save_words": "记住,记一下,记下,备忘",
            "memo_lookup_actions": "查一下,查询,查找,找一下,调出,调取,读取,打开,打出,输入,填入,贴出",
            "memo_wake_words": "记忆,记忆库,备忘,备忘录,我记住的,我记下的,之前记的,上次记的,保存过的,存过的",
            "memo_delete_words": "忘记,忘掉,删除备忘,删掉备忘,删除记忆,删掉记忆,不要记",
        }
        mapping = {
            "memo_save_words": "save_words",
            "memo_lookup_actions": "lookup_actions",
            "memo_wake_words": "wake_words",
            "memo_delete_words": "delete_words",
        }
        for var_name, cfg_name in mapping.items():
            values = triggers.get(cfg_name)
            if isinstance(values, list):
                text = ",".join(str(value) for value in values)
            elif isinstance(values, str):
                text = values
            else:
                text = defaults[var_name]
            if var_name in self._vars:
                self._vars[var_name].set(text)

    def _save_memo_triggers(self) -> None:
        cfg = _read_config()
        fallbacks = cfg.setdefault("instruction_mode", {}).setdefault("intent_fallbacks", {})
        triggers = fallbacks.setdefault("memo_triggers", {})
        mapping = {
            "memo_save_words": "save_words",
            "memo_lookup_actions": "lookup_actions",
            "memo_wake_words": "wake_words",
            "memo_delete_words": "delete_words",
        }
        for var_name, cfg_name in mapping.items():
            raw = self._vars[var_name].get() if var_name in self._vars else ""
            triggers[cfg_name] = _split_words(raw)
        _write_config(cfg)
        self._reload_config(False)
        self._notify_text(self._t("备忘录关键词已保存", "Memo trigger words saved"))

    def _refresh_memo(self) -> None:
        current_key = self._memo_key.get().strip() if hasattr(self, "_memo_key") else ""
        self._memo = MemoStore()
        snapshot = self._memo_snapshot_from_store()
        self._replace_memo_list(sorted(snapshot.keys()), selected_key=current_key, snapshot=snapshot)

    def _refresh_memo_if_changed(self) -> None:
        if self._root is None or not hasattr(self, "_memo_list"):
            return
        snapshot = self._memo_snapshot_from_store()
        if snapshot != self._memo_snapshot:
            current_key = self._memo_key.get().strip() if hasattr(self, "_memo_key") else ""
            self._replace_memo_list(sorted(snapshot.keys()), selected_key=current_key, snapshot=snapshot)
            if current_key in snapshot:
                self._load_memo_fields(current_key)

    def _memo_snapshot_from_store(self) -> dict[str, tuple[str, str]]:
        return {record.key: (record.value, _memo_alias_text(record)) for record in self._memo.records()}

    def _memo_record(self, key: str) -> MemoRecord | None:
        for record in self._memo.records():
            if record.key == key:
                return record
        return None

    def _replace_memo_list(self, keys: list[str], *, selected_key: str = "", snapshot: dict[str, tuple[str, str]] | None = None) -> None:
        self._memo_keys = keys
        self._memo_snapshot = dict(snapshot or {})
        self._memo_list.delete(0, "end")
        for key in self._memo_keys:
            self._memo_list.insert("end", key)
        if selected_key in self._memo_keys:
            index = self._memo_keys.index(selected_key)
            self._memo_list.selection_set(index)
            self._memo_list.see(index)

    def _schedule_memo_poll(self) -> None:
        if self._root is None:
            return
        if self._memo_poll_after_id is not None:
            try:
                self._root.after_cancel(self._memo_poll_after_id)
            except Exception:
                pass
        self._memo_poll_after_id = self._root.after(1000, self._poll_memo)

    def _poll_memo(self) -> None:
        self._memo_poll_after_id = None
        try:
            self._refresh_memo_if_changed()
        finally:
            self._schedule_memo_poll()

    def _load_selected_memo(self) -> None:
        sel = self._memo_list.curselection()
        if not sel:
            return
        key = self._memo_keys[sel[0]]
        self._load_memo_fields(key)

    def _load_memo_fields(self, key: str) -> None:
        record = self._memo_record(key)
        self._memo_key.set(key)
        self._memo_aliases.set(_memo_alias_text(record))
        self._set_text(self._memo_text, "" if record is None else record.value)

    def _new_memo(self) -> None:
        self._memo_key.set("")
        self._memo_aliases.set("")
        self._set_text(self._memo_text, "")

    def _save_memo(self) -> None:
        key = self._memo_key.get().strip()
        aliases = tuple(_split_words(self._memo_aliases.get()))
        value = self._memo_text.get("1.0", "end").strip()
        if not key:
            messagebox.showwarning("Voice Keyboard", self._t("\u8bf7\u586b\u5199\u540d\u79f0", "Name is required"))
            return
        self._memo.save_record(key, value, aliases=aliases)
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
            if path in ("ptt_key", "ai_key") or "." not in path:
                continue
            head, key = path.split(".", 1)
            value = (cfg.get(head) or {}).get(key, "")
            var.set(str(value))

    def _save_hotkeys(self) -> None:
        cfg = _read_config()
        audio = cfg.setdefault("audio", {})
        old_ptt = audio.get("ptt_key")
        old_ai = audio.get("ai_key")
        ptt_key = self._hotkey_value(self._vars["ptt_key"].get())
        ai_key = self._hotkey_value(self._vars["ai_key"].get())
        audio["ptt_key"] = ptt_key
        audio["ai_key"] = ai_key
        _write_config(cfg)
        ok = self._reload_config(False, expected_hotkeys={"ptt_key": ptt_key, "ai_key": ai_key})
        if ok is False:
            audio["ptt_key"] = old_ptt
            audio["ai_key"] = old_ai
            _write_config(cfg)
            self._reload_config(False)
            self._notify_text(self._t("\u5feb\u6377\u952e\u91cd\u8f7d\u5931\u8d25\uff0c\u5df2\u6062\u590d\u539f\u8bbe\u7f6e", "Hotkey reload failed; restored previous setting"))
            self._load_config_fields()
            return
        self._notify_text(self._t("\u5feb\u6377\u952e\u5df2\u4fdd\u5b58", "Hotkeys saved"))

    def _save_config(self) -> None:
        cfg = _read_config()
        for path, var in self._vars.items():
            if path in ("ptt_key", "ai_key") or "." not in path:
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

    def _open_intent_samples_file(self) -> None:
        path = self._intent_samples_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
        os.startfile(str(path))

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
