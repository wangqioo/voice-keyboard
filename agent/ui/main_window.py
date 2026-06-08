"""
Voice Keyboard 主窗口：单 NSWindow + NSTabView：
  设置 / 快捷键 / 历史 / 备忘 / 权限自检
所有 UI 操作必须在主线程；从其他线程调用通过 PyObjCTools.AppHelper.callAfter 入队。
"""

import json
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import objc
from AppKit import (
    NSAlert, NSAlertFirstButtonReturn, NSApplication,
    NSBackingStoreBuffered, NSButton, NSBezelStyleRounded,
    NSColor, NSComboBox, NSFont,
    NSMakeRect, NSObject, NSPopUpButton, NSScrollView, NSSecureTextField,
    NSTabView, NSTabViewItem, NSTableColumn, NSTableView,
    NSTextField, NSView, NSWindow,
    NSWindowStyleMaskTitled, NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable, NSWindowStyleMaskResizable,
)


class _FlippedView(NSView):
    """y=0 在顶部的 NSView，配合 NSScrollView 让滚动行为符合直觉（从上往下排版）。"""
    def isFlipped(self):
        return True
from Foundation import NSIndexSet, NSMutableArray
from PyObjCTools import AppHelper

import sounddevice as sd
import yaml

from agent import typer as _typer
from agent import permissions as _perm
from agent.history import History
from agent.intent_diagnostics import load_diagnostics_rows, save_diagnostics_review
from agent.intent_training import _DEFAULT_PATH as _INTENT_SAMPLES_PATH

_USER_DIR = Path.home() / ".voice-keyboard"
_USER_CONFIG = _USER_DIR / "config.yaml"


def _load_user_config() -> dict:
    if not _USER_CONFIG.exists():
        return {}
    try:
        return yaml.safe_load(_USER_CONFIG.read_text(encoding="utf-8")) or {}
    except Exception as e:
        print(f"[ui] 读取 config 失败: {e}")
        return {}


def _write_user_config(cfg: dict) -> None:
    _USER_DIR.mkdir(parents=True, exist_ok=True)
    _USER_CONFIG.write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _typing_config(cfg: dict) -> dict:
    typing_cfg = cfg.get("typing")
    if not isinstance(typing_cfg, dict):
        typing_cfg = {}
        cfg["typing"] = typing_cfg
    return typing_cfg


# ── 通用控件辅助 ─────────────────────────────────────────────────

def _label(text: str, frame) -> NSTextField:
    f = NSTextField.alloc().initWithFrame_(frame)
    f.setStringValue_(text)
    f.setEditable_(False)
    f.setBordered_(False)
    f.setDrawsBackground_(False)
    f.setSelectable_(False)
    f.setFont_(NSFont.systemFontOfSize_(12))
    f.setTextColor_(NSColor.labelColor())
    return f


def _input(value: str, frame, secure: bool = False) -> NSTextField:
    cls = NSSecureTextField if secure else NSTextField
    f = cls.alloc().initWithFrame_(frame)
    f.setStringValue_(value or "")
    f.setFont_(NSFont.systemFontOfSize_(12))
    return f


def _button(title: str, frame, action_target, action_sel: bytes) -> NSButton:
    b = NSButton.alloc().initWithFrame_(frame)
    b.setTitle_(title)
    b.setBezelStyle_(NSBezelStyleRounded)
    b.setTarget_(action_target)
    b.setAction_(action_sel)
    return b


# ── 设置 tab ─────────────────────────────────────────────────────

class _SettingsTab(NSObject):
    def initWithApp_(self, app):
        self = objc.super(_SettingsTab, self).init()
        if self is None:
            return None
        self._app = app
        self._fields = {}
        self.view = self._build()
        self._load()
        return self

    @objc.python_method
    def _build(self) -> NSView:
        # 容器：占满 tab 区域
        container = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 600, 480))
        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 600, 480))
        scroll.setHasVerticalScroller_(True)
        scroll.setHasHorizontalScroller_(False)
        scroll.setBorderType_(0)  # NSNoBorder
        scroll.setAutohidesScrollers_(False)
        scroll.setAutoresizingMask_(2 | 16)  # NSViewWidthSizable | NSViewHeightSizable
        container.addSubview_(scroll)

        # 滚动内容视图（flipped：y=0 在顶部）
        # 高度先给个大值，最后根据实际内容裁剪
        doc = _FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, 600, 1000))
        scroll.setDocumentView_(doc)

        y = 16  # flipped 坐标系，y 从顶部开始递增

        def row(label_text: str, key: str, value: str = "", secure: bool = False, w: int = 380):
            nonlocal y
            doc.addSubview_(_label(label_text, NSMakeRect(20, y, 160, 20)))
            inp = _input(value, NSMakeRect(180, y - 4, w, 24), secure=secure)
            doc.addSubview_(inp)
            self._fields[key] = inp
            y += 32

        def section(title: str):
            nonlocal y
            y += 8
            doc.addSubview_(_label(title, NSMakeRect(20, y, 240, 20)))
            y += 28

        section("【语音识别 STT】")
        row("provider", "stt.provider", "xunfei", w=200)
        row("app_id", "stt.app_id")
        row("api_key", "stt.api_key", secure=True)
        row("api_secret", "stt.api_secret", secure=True)
        row("language", "stt.language", "zh_cn", w=160)

        section("【LLM】")
        row("provider", "llm.provider", "zhipuai", w=200)
        row("api_key", "llm.api_key", secure=True)
        row("model", "llm.model", "glm-4-flash", w=240)

        section("【热键 / 音频 / 打字】")
        row("ptt_key", "audio.ptt_key", "alt,alt_r", w=200)
        row("ai_key",  "audio.ai_key",  "cmd,cmd_r", w=200)
        row("toggle_key",  "audio.toggle_key",  "f8", w=200)

        # 麦克风 popup
        doc.addSubview_(_label("device", NSMakeRect(20, y, 160, 20)))
        pop = NSPopUpButton.alloc().initWithFrame_(NSMakeRect(180, y - 4, 380, 26))
        pop.addItemWithTitle_("auto")
        try:
            for i, d in enumerate(sd.query_devices()):
                if d["max_input_channels"] > 0:
                    pop.addItemWithTitle_(f"{i}: {d['name']}")
        except Exception:
            pass
        doc.addSubview_(pop)
        self._fields["audio.device"] = pop
        y += 32

        # typing.method popup
        doc.addSubview_(_label("typing.method", NSMakeRect(20, y, 160, 20)))
        tm = NSPopUpButton.alloc().initWithFrame_(NSMakeRect(180, y - 4, 200, 26))
        tm.addItemWithTitle_("unicode")
        tm.addItemWithTitle_("clip")
        doc.addSubview_(tm)
        self._fields["typing.method"] = tm
        y += 44

        # 保存按钮
        save = _button("保存并热重载", NSMakeRect(180, y, 180, 32), self, b"save:")
        save.setKeyEquivalent_("\r")
        doc.addSubview_(save)
        doc.addSubview_(_label("热重载会重启 STT/LLM/PTT，热键继续可用", NSMakeRect(370, y + 6, 280, 20)))
        y += 48

        # 把 doc 高度精确收紧到内容总高，让滚动条对齐
        doc.setFrame_(NSMakeRect(0, 0, 600, max(y, 480)))
        return container

    @objc.python_method
    def _load(self):
        cfg = _load_user_config()
        for path, ctrl in self._fields.items():
            head, key = path.split(".", 1)
            val = (cfg.get(head) or {}).get(key, "")
            if isinstance(val, list):
                val = ",".join(str(x) for x in val)
            if isinstance(ctrl, NSPopUpButton):
                if val and ctrl.indexOfItemWithTitle_(str(val)) >= 0:
                    ctrl.selectItemWithTitle_(str(val))
                elif path == "audio.device" and isinstance(val, int):
                    # device 可能是数字，匹配 "{i}: ..." 项
                    for i in range(ctrl.numberOfItems()):
                        if ctrl.itemTitleAtIndex_(i).startswith(f"{val}:"):
                            ctrl.selectItemAtIndex_(i)
                            break
            else:
                ctrl.setStringValue_(str(val) if val is not None else "")

    @objc.python_method
    def _gather(self) -> dict:
        cfg: dict = {}
        for path, ctrl in self._fields.items():
            head, key = path.split(".", 1)
            cfg.setdefault(head, {})
            if isinstance(ctrl, NSPopUpButton):
                val = ctrl.titleOfSelectedItem() or ""
                if path == "audio.device" and val and val != "auto" and ":" in val:
                    val = val.split(":", 1)[0].strip()
            else:
                val = ctrl.stringValue() or ""
            # 列表字段
            if path in ("audio.ptt_key", "audio.ai_key", "audio.toggle_key") and "," in val:
                val = [s.strip() for s in val.split(",") if s.strip()]
            cfg[head][key] = val
        # 清掉空字段，避免覆盖原 yaml 的有效值
        for h in list(cfg.keys()):
            cfg[h] = {k: v for k, v in cfg[h].items() if v not in (None, "", [])}
            if not cfg[h]:
                del cfg[h]
        return cfg

    def save_(self, sender):
        new_cfg = self._gather()
        try:
            existing = _load_user_config()
            # 合并，保留 existing 中本表单不涉及的子字段
            for h, sub in new_cfg.items():
                existing.setdefault(h, {})
                existing[h].update(sub)
            _write_user_config(existing)
        except Exception as e:
            self._alert("保存失败", str(e))
            return
        try:
            self._app.reload()
            self._alert("保存成功", f"配置已写入 {_USER_CONFIG}\n后台已热重载。")
        except Exception as e:
            self._alert("保存成功，热重载失败", str(e))

    @objc.python_method
    def _alert(self, title: str, msg: str):
        a = NSAlert.alloc().init()
        a.setMessageText_(title)
        a.setInformativeText_(msg)
        a.runModal()


# ── 快捷键 tab ───────────────────────────────────────────────────

_SHORTCUT_SOURCE_LABEL = {
    "global": "通用",
    "application": "应用",
    "system": "系统",
}

_SHORTCUT_KIND_LABEL = {
    "shortcut": "按键",
    "app_launch": "打开应用",
    "system_action": "系统动作",
    "system_window_action": "窗口动作",
}

_SHORTCUT_RISK_LABEL = {
    "normal": "普通",
    "high": "需确认",
}


class _ShortcutsTab(NSObject):
    def initWithApp_(self, app):
        self = objc.super(_ShortcutsTab, self).init()
        if self is None:
            return None
        self._app = app
        self._rows = []
        self._blocked_names: list[str] = []
        self._catalog_table = None
        self._blocked_table = None
        self.view = self._build()
        self.reload_(None)
        return self

    @objc.python_method
    def _build(self) -> NSView:
        v = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 600, 480))

        v.addSubview_(_label("当前快捷键", NSMakeRect(20, 444, 120, 20)))
        v.addSubview_(_button("刷新", NSMakeRect(500, 438, 80, 28), self, b"reload:"))

        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(20, 210, 560, 225))
        scroll.setHasVerticalScroller_(True)
        scroll.setBorderType_(1)
        table = NSTableView.alloc().initWithFrame_(scroll.bounds())
        table.setUsesAlternatingRowBackgroundColors_(True)
        for ident, title, w in (
            ("name", "动作", 180),
            ("source", "类型", 80),
            ("risk", "风险", 60),
            ("application", "应用", 230),
        ):
            col = NSTableColumn.alloc().initWithIdentifier_(ident)
            col.headerCell().setStringValue_(title)
            col.setWidth_(w)
            table.addTableColumn_(col)
        table.setDelegate_(self)
        table.setDataSource_(self)
        scroll.setDocumentView_(table)
        v.addSubview_(scroll)
        self._catalog_table = table

        v.addSubview_(_button("禁用所选", NSMakeRect(20, 172, 100, 28), self, b"disableSelected:"))
        v.addSubview_(_label("macOS 系统动作", NSMakeRect(132, 178, 180, 20)))

        v.addSubview_(_label("已禁用", NSMakeRect(20, 138, 120, 20)))
        blocked_scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(20, 58, 250, 76))
        blocked_scroll.setHasVerticalScroller_(True)
        blocked_scroll.setBorderType_(1)
        blocked_table = NSTableView.alloc().initWithFrame_(blocked_scroll.bounds())
        blocked_col = NSTableColumn.alloc().initWithIdentifier_("blocked")
        blocked_col.headerCell().setStringValue_("动作")
        blocked_col.setWidth_(230)
        blocked_table.addTableColumn_(blocked_col)
        blocked_table.setDelegate_(self)
        blocked_table.setDataSource_(self)
        blocked_scroll.setDocumentView_(blocked_table)
        v.addSubview_(blocked_scroll)
        self._blocked_table = blocked_table
        v.addSubview_(_button("恢复所选", NSMakeRect(20, 20, 100, 28), self, b"enableSelected:"))

        v.addSubview_(_label("自定义动作", NSMakeRect(300, 138, 120, 20)))
        v.addSubview_(_label("语音动作", NSMakeRect(300, 104, 70, 20)))
        self._custom_name = _input("", NSMakeRect(370, 100, 210, 24))
        v.addSubview_(self._custom_name)
        v.addSubview_(_label("按键", NSMakeRect(300, 70, 70, 20)))
        self._custom_keys = _input("", NSMakeRect(370, 66, 210, 24))
        v.addSubview_(self._custom_keys)
        v.addSubview_(_button("保存自定义", NSMakeRect(370, 20, 120, 28), self, b"saveCustom:"))
        return v

    def reload_(self, sender):
        try:
            self._rows = list(_typer.shortcut_catalog())
        except Exception as e:
            print(f"[ui] shortcut catalog load 失败: {e}")
            self._rows = []
        cfg = _load_user_config()
        typing_cfg = cfg.get("typing") or {}
        blocked = typing_cfg.get("blocked_shortcuts", []) or []
        self._blocked_names = sorted({
            str(name).strip()
            for name in blocked
            if isinstance(name, str) and name.strip()
        })
        if self._catalog_table is not None:
            self._catalog_table.reloadData()
        if self._blocked_table is not None:
            self._blocked_table.reloadData()

    def numberOfRowsInTableView_(self, table):
        if table == self._blocked_table:
            return len(self._blocked_names)
        return len(self._rows)

    def tableView_objectValueForTableColumn_row_(self, table, col, row):
        if table == self._blocked_table:
            if row < 0 or row >= len(self._blocked_names):
                return ""
            return self._blocked_names[row]
        if row < 0 or row >= len(self._rows):
            return ""
        entry = self._rows[row]
        ident = col.identifier()
        if ident == "name":
            return entry.name
        if ident == "source":
            return _SHORTCUT_KIND_LABEL.get(
                getattr(entry, "kind", "shortcut"),
                _SHORTCUT_SOURCE_LABEL.get(entry.source, entry.source),
            )
        if ident == "risk":
            return _SHORTCUT_RISK_LABEL.get(entry.risk, entry.risk)
        if ident == "application":
            return entry.application
        return ""

    def disableSelected_(self, sender):
        idx = self._catalog_table.selectedRow()
        if idx < 0 or idx >= len(self._rows):
            return
        name = self._rows[idx].name
        try:
            cfg = _load_user_config()
            typing_cfg = _typing_config(cfg)
            blocked = typing_cfg.get("blocked_shortcuts")
            if not isinstance(blocked, list):
                blocked = []
            if name not in blocked:
                blocked.append(name)
            typing_cfg["blocked_shortcuts"] = blocked
            _write_user_config(cfg)
            self._reload_backend()
            self.reload_(None)
        except Exception as e:
            self._alert("禁用失败", str(e))

    def enableSelected_(self, sender):
        idx = self._blocked_table.selectedRow()
        if idx < 0 or idx >= len(self._blocked_names):
            return
        name = self._blocked_names[idx]
        try:
            cfg = _load_user_config()
            typing_cfg = _typing_config(cfg)
            blocked = typing_cfg.get("blocked_shortcuts")
            if isinstance(blocked, list):
                typing_cfg["blocked_shortcuts"] = [
                    item for item in blocked
                    if not (isinstance(item, str) and item.strip() == name)
                ]
            _write_user_config(cfg)
            self._reload_backend()
            self.reload_(None)
        except Exception as e:
            self._alert("恢复失败", str(e))

    def saveCustom_(self, sender):
        name = self._custom_name.stringValue().strip()
        keys = self._custom_keys.stringValue().strip()
        if not name or not keys:
            self._alert("保存失败", "语音动作和按键都不能为空。")
            return
        try:
            _typer._parse_shortcut_keys(keys)
        except Exception as e:
            self._alert("按键格式不正确", str(e))
            return
        try:
            cfg = _load_user_config()
            typing_cfg = _typing_config(cfg)
            shortcuts = typing_cfg.get("shortcuts")
            if not isinstance(shortcuts, dict):
                shortcuts = {}
            shortcuts[name] = keys
            typing_cfg["shortcuts"] = shortcuts
            _write_user_config(cfg)
            self._reload_backend()
            self._custom_name.setStringValue_("")
            self._custom_keys.setStringValue_("")
            self.reload_(None)
        except Exception as e:
            self._alert("保存失败", str(e))

    @objc.python_method
    def _reload_backend(self):
        self._app.reload()

    @objc.python_method
    def _alert(self, title, msg):
        a = NSAlert.alloc().init()
        a.setMessageText_(title)
        a.setInformativeText_(msg)
        a.runModal()


# ── 历史 tab ─────────────────────────────────────────────────────

_MODE_LABEL = {
    "dictate": "听写", "polish": "润色", "ai": "AI", "edit": "编辑",
    "ai_chat": "AI 聊天", "ai_write": "AI 写作", "ai_edit": "AI 编辑",
    "ai_delete": "AI 删除", "ai_undo": "撤销", "ai_shortcut": "AI 快捷键",
}


class _HistoryTab(NSObject):
    def initWithApp_(self, app):
        self = objc.super(_HistoryTab, self).init()
        if self is None:
            return None
        self._app = app
        self._rows: list[dict] = []
        self.view = self._build()
        app.history.add_listener(self._on_new_entry)
        self.reload_(None)
        return self

    @objc.python_method
    def _build(self) -> NSView:
        v = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 600, 480))
        # 顶部按钮条
        v.addSubview_(_button("刷新", NSMakeRect(20, 440, 80, 26), self, b"reload:"))
        v.addSubview_(_button("打开日志", NSMakeRect(110, 440, 100, 26), self, b"openLog:"))
        v.addSubview_(_button("再次打字", NSMakeRect(220, 440, 100, 26), self, b"retype:"))
        v.addSubview_(_label("双击或选中后点「再次打字」把历史记录打到当前输入框", NSMakeRect(330, 444, 320, 20)))

        # 表格
        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(20, 20, 560, 410))
        scroll.setHasVerticalScroller_(True)
        scroll.setBorderType_(1)  # NSBezelBorder
        table = NSTableView.alloc().initWithFrame_(scroll.bounds())
        table.setUsesAlternatingRowBackgroundColors_(True)

        for ident, title, w in (
            ("ts", "时间", 130), ("mode", "类型", 70), ("status", "状态", 60),
            ("text", "文本", 290),
        ):
            col = NSTableColumn.alloc().initWithIdentifier_(ident)
            col.headerCell().setStringValue_(title)
            col.setWidth_(w)
            table.addTableColumn_(col)

        table.setDelegate_(self)
        table.setDataSource_(self)
        table.setDoubleAction_(b"retype:")
        table.setTarget_(self)
        scroll.setDocumentView_(table)
        v.addSubview_(scroll)
        self._table = table
        return v

    # NSTableViewDataSource
    def numberOfRowsInTableView_(self, t):
        return len(self._rows)

    def tableView_objectValueForTableColumn_row_(self, t, col, row):
        if row < 0 or row >= len(self._rows):
            return ""
        e = self._rows[row]
        ident = col.identifier()
        if ident == "ts":
            return time.strftime("%m-%d %H:%M:%S", time.localtime(e.get("ts", 0)))
        if ident == "mode":
            return _MODE_LABEL.get(e.get("mode", ""), e.get("mode", ""))
        if ident == "status":
            s = e.get("status", "")
            return {"ok": "✓", "empty": "空", "error": "✗"}.get(s, s)
        if ident == "text":
            t = e.get("text", "") or e.get("detail", "")
            return t.replace("\n", " ⏎ ")
        return ""

    def reload_(self, sender):
        self._rows = list(reversed(self._app.history.load(limit=300)))
        self._table.reloadData()

    @objc.python_method
    def _on_new_entry(self, entry: dict):
        # listener 来自 STT 线程，UI 操作必须切回主线程
        AppHelper.callAfter(self._refresh_main)

    def _refresh_main(self):
        self.reload_(None)

    def openLog_(self, sender):
        from agent import log_setup
        from AppKit import NSWorkspace
        p = log_setup.log_path()
        if p.exists():
            NSWorkspace.sharedWorkspace().openFile_(str(p))
        else:
            self._alert("日志文件未创建", "开发模式下日志输出在终端，仅打包应用会写文件。")

    def retype_(self, sender):
        idx = self._table.selectedRow()
        if idx < 0 or idx >= len(self._rows):
            return
        text = self._rows[idx].get("text", "")
        if not text:
            return
        self._app.retype_after_delay(text)

    @objc.python_method
    def _alert(self, title, msg):
        a = NSAlert.alloc().init()
        a.setMessageText_(title); a.setInformativeText_(msg); a.runModal()


# ── 意图诊断 tab ─────────────────────────────────────────────────

_INTENT_LABEL_OPTIONS = [
    "",
    "correct",
    "wrong_intent",
    "wrong_target",
    "unsafe_should_confirm",
    "missing_shortcut",
    "unclear",
]


class _IntentDiagnosticsTab(NSObject):
    def initWithApp_(self, app):
        self = objc.super(_IntentDiagnosticsTab, self).init()
        if self is None:
            return None
        self._app = app
        self._rows: list[dict] = []
        self.view = self._build()
        self.reload_(None)
        return self

    @objc.python_method
    def _build(self) -> NSView:
        v = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 600, 480))
        v.addSubview_(_button("刷新", NSMakeRect(20, 440, 80, 26), self, b"reload:"))
        v.addSubview_(_button("打开样本文件", NSMakeRect(110, 440, 120, 26), self, b"openSamples:"))
        v.addSubview_(_label(str(_INTENT_SAMPLES_PATH), NSMakeRect(240, 444, 340, 20)))

        v.addSubview_(_label("意图", NSMakeRect(20, 408, 40, 20)))
        intent_box = NSPopUpButton.alloc().initWithFrame_(NSMakeRect(62, 404, 150, 26))
        for item in ("全部", "chat", "shortcut", "write", "edit", "delete", "memo", "app_launch", "system_action"):
            intent_box.addItemWithTitle_(item)
        intent_box.setTarget_(self)
        intent_box.setAction_(b"reload:")
        v.addSubview_(intent_box)
        self._intent_filter = intent_box

        v.addSubview_(_label("标注", NSMakeRect(230, 408, 40, 20)))
        review_box = NSPopUpButton.alloc().initWithFrame_(NSMakeRect(272, 404, 130, 26))
        for item in ("全部", "未标注", "已标注"):
            review_box.addItemWithTitle_(item)
        review_box.setTarget_(self)
        review_box.setAction_(b"reload:")
        v.addSubview_(review_box)
        self._review_filter = review_box

        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(20, 220, 560, 175))
        scroll.setHasVerticalScroller_(True)
        scroll.setBorderType_(1)
        table = NSTableView.alloc().initWithFrame_(scroll.bounds())
        table.setUsesAlternatingRowBackgroundColors_(True)
        for ident, title, w in (
            ("ts", "时间", 105),
            ("intent", "意图", 82),
            ("source", "来源", 58),
            ("confidence", "置信", 58),
            ("status", "状态", 52),
            ("review", "标注", 95),
            ("text", "文本", 110),
        ):
            col = NSTableColumn.alloc().initWithIdentifier_(ident)
            col.headerCell().setStringValue_(title)
            col.setWidth_(w)
            table.addTableColumn_(col)
        table.setDelegate_(self)
        table.setDataSource_(self)
        scroll.setDocumentView_(table)
        v.addSubview_(scroll)
        self._table = table

        v.addSubview_(_label("标注", NSMakeRect(20, 184, 50, 20)))
        label_box = NSPopUpButton.alloc().initWithFrame_(NSMakeRect(72, 180, 190, 26))
        for item in _INTENT_LABEL_OPTIONS:
            label_box.addItemWithTitle_(item)
        v.addSubview_(label_box)
        self._label_box = label_box
        v.addSubview_(_button("保存反馈", NSMakeRect(272, 180, 90, 28), self, b"saveReview:"))
        v.addSubview_(_button("复制文本", NSMakeRect(372, 180, 90, 28), self, b"copyText:"))

        v.addSubview_(_label("备注", NSMakeRect(20, 148, 50, 20)))
        from AppKit import NSTextView
        note_scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(72, 112, 508, 58))
        note_scroll.setHasVerticalScroller_(True)
        note_scroll.setBorderType_(1)
        note = NSTextView.alloc().initWithFrame_(note_scroll.bounds())
        note.setEditable_(True)
        note.setRichText_(False)
        note.setFont_(NSFont.systemFontOfSize_(12))
        note_scroll.setDocumentView_(note)
        v.addSubview_(note_scroll)
        self._note = note

        v.addSubview_(_label("详情", NSMakeRect(20, 82, 50, 20)))
        detail_scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(72, 20, 508, 82))
        detail_scroll.setHasVerticalScroller_(True)
        detail_scroll.setBorderType_(1)
        detail = NSTextView.alloc().initWithFrame_(detail_scroll.bounds())
        detail.setEditable_(False)
        detail.setRichText_(False)
        detail.setFont_(NSFont.userFixedPitchFontOfSize_(11))
        detail_scroll.setDocumentView_(detail)
        v.addSubview_(detail_scroll)
        self._detail = detail
        return v

    def numberOfRowsInTableView_(self, t):
        return len(self._rows)

    def tableView_objectValueForTableColumn_row_(self, t, col, row):
        if row < 0 or row >= len(self._rows):
            return ""
        e = self._rows[row]
        ident = col.identifier()
        if ident == "ts":
            return time.strftime("%m-%d %H:%M", time.localtime(e.get("ts", 0)))
        if ident == "intent":
            return e.get("intent_type", "")
        if ident == "source":
            return e.get("intent_source", "")
        if ident == "confidence":
            return e.get("intent_confidence", "")
        if ident == "status":
            return e.get("status", "")
        if ident == "review":
            return e.get("review_label", "")
        if ident == "text":
            return str(e.get("text", "")).replace("\n", " ⏎ ")
        return ""

    def tableViewSelectionDidChange_(self, note):
        self._load_selected()

    def reload_(self, sender):
        try:
            self._rows = load_diagnostics_rows(
                _INTENT_SAMPLES_PATH,
                limit=300,
                intent_type=self._selected_intent_filter(),
                review_state=self._selected_review_filter(),
            )
        except Exception as e:
            print(f"[ui] intent diagnostics load 失败: {e}")
            self._rows = []
        self._table.reloadData()
        self._load_selected()

    def openSamples_(self, sender):
        from AppKit import NSWorkspace
        p = Path(_INTENT_SAMPLES_PATH)
        if p.exists():
            NSWorkspace.sharedWorkspace().openFile_(str(p))
        else:
            self._alert("样本文件未创建", str(p))

    def saveReview_(self, sender):
        row = self._selected_row()
        if row is None:
            return
        label = self._label_box.titleOfSelectedItem() or ""
        note = self._note.string() or ""
        try:
            updated = save_diagnostics_review(
                _INTENT_SAMPLES_PATH,
                row,
                label=label,
                note=note,
            )
        except Exception as e:
            self._alert("保存反馈失败", str(e))
            return
        idx = self._table.selectedRow()
        if 0 <= idx < len(self._rows):
            self._rows[idx] = updated
        self._table.reloadData()
        self._load_selected()

    def copyText_(self, sender):
        row = self._selected_row()
        if row is None:
            return
        from AppKit import NSPasteboard, NSPasteboardTypeString
        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_(str(row.get("text", "")), NSPasteboardTypeString)

    @objc.python_method
    def _selected_row(self):
        idx = self._table.selectedRow()
        if idx < 0 or idx >= len(self._rows):
            return None
        return self._rows[idx]

    @objc.python_method
    def _selected_intent_filter(self) -> str:
        value = self._intent_filter.titleOfSelectedItem() or ""
        return "" if value == "全部" else value

    @objc.python_method
    def _selected_review_filter(self) -> str:
        value = self._review_filter.titleOfSelectedItem() or ""
        if value == "已标注":
            return "reviewed"
        if value == "未标注":
            return "unreviewed"
        return ""

    @objc.python_method
    def _load_selected(self):
        row = self._selected_row()
        if row is None:
            self._label_box.selectItemWithTitle_("")
            self._note.setString_("")
            self._detail.setString_("")
            return
        label = row.get("review_label", "") or ""
        if self._label_box.indexOfItemWithTitle_(label) >= 0:
            self._label_box.selectItemWithTitle_(label)
        else:
            self._label_box.selectItemWithTitle_("")
        self._note.setString_(row.get("review_note", "") or "")
        detail = json.dumps(row, ensure_ascii=False, indent=2)
        self._detail.setString_(detail)

    @objc.python_method
    def _alert(self, title, msg):
        a = NSAlert.alloc().init()
        a.setMessageText_(title); a.setInformativeText_(msg); a.runModal()


# ── 备忘 tab ───────────────────────────────────────────────

class _MemoTab(NSObject):
    def initWithApp_(self, app):
        self = objc.super(_MemoTab, self).init()
        if self is None:
            return None
        self._app = app
        self._keys: list[str] = []
        self.view = self._build()
        self.reload_(None)
        return self

    @objc.python_method
    def _build(self) -> NSView:
        v = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 600, 480))

        # 左侧：列表
        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(20, 60, 220, 400))
        scroll.setHasVerticalScroller_(True)
        scroll.setBorderType_(1)
        table = NSTableView.alloc().initWithFrame_(scroll.bounds())
        col = NSTableColumn.alloc().initWithIdentifier_("key")
        col.headerCell().setStringValue_("名称")
        col.setWidth_(200)
        table.addTableColumn_(col)
        table.setDataSource_(self)
        table.setDelegate_(self)
        scroll.setDocumentView_(table)
        v.addSubview_(scroll)
        self._table = table

        # 右侧：键名 + 内容
        v.addSubview_(_label("键名", NSMakeRect(260, 430, 60, 20)))
        self._key_input = _input("", NSMakeRect(260, 400, 320, 24))
        v.addSubview_(self._key_input)

        v.addSubview_(_label("内容", NSMakeRect(260, 370, 60, 20)))
        # 多行输入：用 NSScrollView 包 NSTextView
        from AppKit import NSTextView
        val_scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(260, 60, 320, 300))
        val_scroll.setHasVerticalScroller_(True)
        val_scroll.setBorderType_(1)
        tv = NSTextView.alloc().initWithFrame_(val_scroll.bounds())
        tv.setEditable_(True)
        tv.setRichText_(False)
        tv.setFont_(NSFont.systemFontOfSize_(12))
        val_scroll.setDocumentView_(tv)
        v.addSubview_(val_scroll)
        self._val_input = tv

        # 操作按钮
        v.addSubview_(_button("新建", NSMakeRect(20, 20, 70, 28), self, b"addNew:"))
        v.addSubview_(_button("保存", NSMakeRect(95, 20, 70, 28), self, b"saveMemo:"))
        v.addSubview_(_button("删除", NSMakeRect(170, 20, 70, 28), self, b"deleteMemo:"))
        v.addSubview_(_button("刷新", NSMakeRect(245, 20, 70, 28), self, b"reload:"))
        return v

    def reload_(self, sender):
        try:
            self._keys = sorted(self._app.memo.keys())
        except Exception as e:
            print(f"[ui] memo load 失败: {e}")
            self._keys = []
        self._table.reloadData()

    # NSTableViewDataSource
    def numberOfRowsInTableView_(self, t):
        return len(self._keys)

    def tableView_objectValueForTableColumn_row_(self, t, col, row):
        if row < 0 or row >= len(self._keys):
            return ""
        return self._keys[row]

    # NSTableViewDelegate
    def tableViewSelectionDidChange_(self, note):
        idx = self._table.selectedRow()
        if idx < 0 or idx >= len(self._keys):
            return
        k = self._keys[idx]
        v = self._app.memo.get(k) or ""
        self._key_input.setStringValue_(k)
        self._val_input.setString_(v)

    def addNew_(self, sender):
        self._key_input.setStringValue_("")
        self._val_input.setString_("")
        self._table.deselectAll_(None)
        self._key_input.becomeFirstResponder()

    def saveMemo_(self, sender):
        k = self._key_input.stringValue().strip()
        v = self._val_input.string()
        if not k:
            self._alert("键名不能为空", "")
            return
        self._app.memo.save(k, v)
        self.reload_(None)
        # 选中刚保存的
        if k in self._keys:
            i = self._keys.index(k)
            self._table.selectRowIndexes_byExtendingSelection_(NSIndexSet.indexSetWithIndex_(i), False)

    def deleteMemo_(self, sender):
        k = self._key_input.stringValue().strip()
        if not k:
            return
        a = NSAlert.alloc().init()
        a.setMessageText_(f"删除备忘「{k}」？")
        a.addButtonWithTitle_("删除")
        a.addButtonWithTitle_("取消")
        if a.runModal() != NSAlertFirstButtonReturn:
            return
        self._app.memo.delete(k)
        self._key_input.setStringValue_("")
        self._val_input.setString_("")
        self.reload_(None)

    @objc.python_method
    def _alert(self, title, msg):
        a = NSAlert.alloc().init()
        a.setMessageText_(title); a.setInformativeText_(msg); a.runModal()


# ── 权限 tab ─────────────────────────────────────────────────────

class _PermsTab(NSObject):
    def initWithApp_(self, app):
        self = objc.super(_PermsTab, self).init()
        if self is None:
            return None
        self._app = app
        self.view = self._build()
        self.reload_(None)
        return self

    @objc.python_method
    def _build(self) -> NSView:
        v = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 600, 480))
        v.addSubview_(_label("macOS 权限自检（adhoc 签名每次重新打包都会失效）",
                             NSMakeRect(20, 440, 560, 20)))

        self._rows = {}
        items = [
            ("accessibility",    "辅助功能（打字）",    "agent 通过 Quartz 发送 Unicode 按键需要此权限"),
            ("input_monitoring", "输入监听（热键）",   "pynput 监听全局 PTT/AI 键需要此权限"),
            ("microphone",       "麦克风",           "录音必须；首次会主动弹窗请求"),
        ]
        y = 380
        for key, title, hint in items:
            v.addSubview_(_label(title, NSMakeRect(20, y, 180, 20)))
            status = _label("…", NSMakeRect(200, y, 120, 20))
            status.setFont_(NSFont.boldSystemFontOfSize_(13))
            v.addSubview_(status)
            v.addSubview_(_label(hint, NSMakeRect(20, y - 22, 480, 18)))
            btn = NSButton.alloc().initWithFrame_(NSMakeRect(420, y - 4, 140, 28))
            btn.setBezelStyle_(NSBezelStyleRounded)
            btn.setTitle_("打开系统设置")
            btn.setTarget_(self)
            btn.setAction_(b"openSettings:")
            btn.setTag_({"accessibility": 1, "input_monitoring": 2, "microphone": 3}[key])
            v.addSubview_(btn)
            self._rows[key] = status
            y -= 60

        v.addSubview_(_button("重新检查", NSMakeRect(20, y, 120, 28), self, b"reload:"))
        v.addSubview_(_button("请求麦克风", NSMakeRect(150, y, 140, 28), self, b"reqMic:"))
        v.addSubview_(_label("授权后请重启 Voice Keyboard", NSMakeRect(300, y + 4, 280, 20)))
        return v

    def reload_(self, sender):
        s = _perm.all_status()
        text_color = {
            "granted": NSColor.systemGreenColor(),
            "denied":  NSColor.systemRedColor(),
            "not_determined": NSColor.systemOrangeColor(),
            "unknown": NSColor.secondaryLabelColor(),
        }
        text_label = {
            "granted": "✓ 已授权",
            "denied":  "✗ 已拒绝",
            "not_determined": "? 未决定",
            "unknown": "? 未知",
        }
        for k, lbl in self._rows.items():
            v = s.get(k, "unknown")
            lbl.setStringValue_(text_label.get(v, v))
            lbl.setTextColor_(text_color.get(v, NSColor.labelColor()))

    def openSettings_(self, sender):
        tag = sender.tag()
        name = {1: "accessibility", 2: "input_monitoring", 3: "microphone"}.get(tag)
        if name:
            _perm.open_settings(name)

    def reqMic_(self, sender):
        _perm.request_microphone(lambda granted: print(f"[perm] 麦克风授权回调: {granted}"))


# ── 主窗口控制器 ─────────────────────────────────────────────────

class MainWindow(NSObject):
    def initWithApp_(self, app):
        self = objc.super(MainWindow, self).init()
        if self is None:
            return None
        self._app = app
        self._win = None
        self._tab_view = None
        self._tabs = {}  # name -> tab obj
        self._build()
        return self

    @objc.python_method
    def _build(self):
        style = (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
                 | NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable)
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(200, 200, 600, 520), style, NSBackingStoreBuffered, False,
        )
        win.setTitle_("Voice Keyboard")
        win.setReleasedWhenClosed_(False)

        tv = NSTabView.alloc().initWithFrame_(NSMakeRect(0, 0, 600, 520))

        for ident, title, cls in (
            ("settings", "设置",   _SettingsTab),
            ("shortcuts", "快捷键", _ShortcutsTab),
            ("history",  "历史",   _HistoryTab),
            ("intent", "意图诊断", _IntentDiagnosticsTab),
            ("memo",    "备忘", _MemoTab),
            ("perms",    "权限",   _PermsTab),
        ):
            tab = cls.alloc().initWithApp_(self._app)
            self._tabs[ident] = tab
            item = NSTabViewItem.alloc().initWithIdentifier_(ident)
            item.setLabel_(title)
            item.setView_(tab.view)
            tv.addTabViewItem_(item)

        win.setContentView_(tv)
        self._win = win
        self._tab_view = tv

    def show_(self, sender):
        # 主线程入口
        if self._win is None:
            return
        # 切到 perms tab 时刷新
        for name, tab in self._tabs.items():
            if hasattr(tab, "reload_"):
                try:
                    tab.reload_(None)
                except Exception:
                    pass
        self._win.makeKeyAndOrderFront_(None)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    def show_tab(self, ident: str):
        if self._tab_view is None:
            return
        idx = self._tab_view.indexOfTabViewItemWithIdentifier_(ident)
        if idx >= 0:
            self._tab_view.selectTabViewItemAtIndex_(idx)
        self.show_(None)
