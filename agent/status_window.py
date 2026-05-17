"""
macOS 原生悬浮状态窗口，HUD 风格：毛玻璃背景 + 彩色状态点 + 文字。
屏幕底部居中。必须在主线程调用 run()，其他线程通过 set_state() 安全更新。
"""

import queue
import threading

import objc
from AppKit import (
    NSApplication, NSBackingStoreBuffered, NSColor, NSFont,
    NSFontWeightMedium,
    NSPanel, NSScreen, NSTextField, NSTextAlignmentLeft, NSView,
    NSVisualEffectBlendingModeBehindWindow, NSVisualEffectMaterialHUDWindow,
    NSVisualEffectStateActive, NSVisualEffectView,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorIgnoresCycle,
    NSWindowCollectionBehaviorTransient,
    NSWindowStyleMaskBorderless, NSWindowStyleMaskNonactivatingPanel,
    NSStatusWindowLevel,
)
from Foundation import NSMakeRect, NSObject, NSTimer
from PyObjCTools import AppHelper
from Quartz import CGColorCreateGenericRGB


# 状态 → (文字, 状态点 RGB)
_STATES: dict[str, tuple[str, tuple[float, float, float]]] = {
    "recording":        ("录音中",            (0.94, 0.32, 0.31)),  # 红
    "polish_recording": ("录音中 · 微润色",     (0.20, 0.78, 0.50)),  # 绿
    "ai_recording":     ("AI 指令录音中",      (0.69, 0.40, 0.85)),  # 紫
    "recognizing":      ("识别中",            (0.96, 0.62, 0.07)),  # 橙
    "empty_stt":        ("未识别到语句",       (0.96, 0.62, 0.07)),  # 橙
    "polishing":        ("润色中",            (0.10, 0.74, 0.81)),  # 青
    "ai_processing":    ("AI 处理中",         (0.27, 0.62, 0.94)),  # 蓝
    "error_stt":        ("识别失败",           (0.94, 0.20, 0.20)),  # 深红
    "error_typing":     ("打字失败 · 检查权限",  (0.94, 0.20, 0.20)),  # 深红
    "error_llm":        ("LLM 失败",          (0.94, 0.20, 0.20)),  # 深红
    "error_perm":       ("权限未授予",          (0.94, 0.20, 0.20)),  # 深红
}
# 错误状态 1.5s 后自动消失
_ERROR_STATES = {"error_stt", "error_typing", "error_llm", "error_perm", "empty_stt"}

_BOTTOM_MARGIN = 96
_HEIGHT        = 36
_PAD_LEFT      = 14
_PAD_RIGHT     = 16
_DOT_SIZE      = 8
_DOT_GAP       = 9
_FONT_SIZE     = 13


class _DotView(NSView):
    def initWithFrame_(self, frame):
        self = objc.super(_DotView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.setWantsLayer_(True)
        layer = self.layer()
        layer.setCornerRadius_(frame.size.width / 2.0)
        layer.setMasksToBounds_(True)
        return self

    @objc.python_method
    def set_color(self, rgb):
        cg = CGColorCreateGenericRGB(rgb[0], rgb[1], rgb[2], 1.0)
        self.layer().setBackgroundColor_(cg)


class _Controller(NSObject):
    def initWithQueue_(self, q):
        self = objc.super(_Controller, self).init()
        if self is None:
            return None
        self._q = q
        self._panel = None
        self._effect = None
        self._dot = None
        self._label = None
        self._state = "idle"
        self._message_token = 0
        self._message_width_text = ""
        self._build()
        return self

    @objc.python_method
    def _build(self):
        screen = NSScreen.mainScreen() or (NSScreen.screens() and NSScreen.screens()[0])
        if screen is None:
            print("[status] 找不到屏幕，悬浮窗不可用")
            return
        sf = screen.frame()

        w = 200
        h = _HEIGHT
        x = sf.origin.x + (sf.size.width - w) / 2
        y = sf.origin.y + _BOTTOM_MARGIN

        style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, w, h), style, NSBackingStoreBuffered, False,
        )
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setLevel_(NSStatusWindowLevel)
        panel.setHidesOnDeactivate_(False)
        panel.setIgnoresMouseEvents_(True)
        panel.setMovable_(False)
        panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorTransient
            | NSWindowCollectionBehaviorFullScreenAuxiliary
            | NSWindowCollectionBehaviorIgnoresCycle
        )

        # 毛玻璃 HUD 背景
        effect = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
        effect.setMaterial_(NSVisualEffectMaterialHUDWindow)
        effect.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        effect.setState_(NSVisualEffectStateActive)
        effect.setWantsLayer_(True)
        effect.layer().setCornerRadius_(h / 2.0)
        effect.layer().setMasksToBounds_(True)
        panel.setContentView_(effect)

        # 状态点
        dot_y = (h - _DOT_SIZE) / 2.0
        dot = _DotView.alloc().initWithFrame_(
            NSMakeRect(_PAD_LEFT, dot_y, _DOT_SIZE, _DOT_SIZE)
        )
        effect.addSubview_(dot)

        # 文字
        label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(_PAD_LEFT + _DOT_SIZE + _DOT_GAP, 0, w, h)
        )
        label.setEditable_(False)
        label.setBordered_(False)
        label.setSelectable_(False)
        label.setDrawsBackground_(False)
        label.setBackgroundColor_(NSColor.clearColor())
        label.setTextColor_(NSColor.whiteColor())
        label.setAlignment_(NSTextAlignmentLeft)
        label.setFont_(NSFont.systemFontOfSize_weight_(_FONT_SIZE, NSFontWeightMedium))
        effect.addSubview_(label)

        self._panel = panel
        self._effect = effect
        self._dot = dot
        self._label = label

    def startPolling(self):
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.04, self, b"tick:", None, True,
        )

    def tick_(self, _timer):
        try:
            while True:
                item = self._q.get_nowait()
                if isinstance(item, tuple) and item and item[0] == "message":
                    _, text, token, *rest = item
                    width_text = rest[0] if rest else text
                    self._apply_message(text, token, width_text)
                elif isinstance(item, tuple) and item and item[0] == "hide_message":
                    _, token = item
                    self._hide_message_now(token)
                else:
                    state = item[1] if isinstance(item, tuple) else item
                    self._apply(state)
        except queue.Empty:
            pass

    @objc.python_method
    def _apply(self, state: str):
        if self._panel is None:
            return
        info = _STATES.get(state)
        if info is None or state == "idle":
            self._state = "idle"
            self._message_width_text = ""
            self._panel.orderOut_(None)
            return
        text, rgb = info

        self._state = state
        self._message_width_text = ""
        self._layout(text, rgb, text)

        if state in _ERROR_STATES:
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                1.5, self, b"hide:", None, False,
            )

    @objc.python_method
    def _layout(self, text: str, rgb, width_text: str):
        self._label.setStringValue_(width_text)
        self._label.sizeToFit()
        text_w = self._label.frame().size.width

        self._label.setStringValue_(text)
        self._label.sizeToFit()
        label_w = self._label.frame().size.width
        text_h = self._label.frame().size.height

        h = _HEIGHT
        w = _PAD_LEFT + _DOT_SIZE + _DOT_GAP + text_w + _PAD_RIGHT

        screen = NSScreen.mainScreen() or NSScreen.screens()[0]
        sf = screen.frame()
        x = sf.origin.x + (sf.size.width - w) / 2
        y = sf.origin.y + _BOTTOM_MARGIN

        self._panel.setFrame_display_(NSMakeRect(x, y, w, h), True)
        self._effect.setFrame_(NSMakeRect(0, 0, w, h))
        self._effect.layer().setCornerRadius_(h / 2.0)

        dot_y = (h - _DOT_SIZE) / 2.0
        self._dot.setFrame_(NSMakeRect(_PAD_LEFT, dot_y, _DOT_SIZE, _DOT_SIZE))
        self._dot.set_color(rgb)

        label_y = (h - text_h) / 2.0
        self._label.setFrame_(NSMakeRect(
            _PAD_LEFT + _DOT_SIZE + _DOT_GAP, label_y, label_w + 4, text_h,
        ))

        self._panel.orderFrontRegardless()

    @objc.python_method
    def _apply_message(self, text: str, token: int, width_text: str | None = None):
        if self._panel is None:
            return
        self._message_token = token
        self._state = "message"
        self._message_width_text = width_text or text
        self._layout(text, (0.27, 0.62, 0.94), self._message_width_text)

    @objc.python_method
    def _hide_message_now(self, token: int):
        if self._panel is None or token != self._message_token or self._state != "message":
            return
        self._state = "idle"
        self._message_width_text = ""
        self._panel.orderOut_(None)

    def hide_(self, _timer):
        if self._panel is not None:
            self._state = "idle"
            self._message_width_text = ""
            self._panel.orderOut_(None)


class StatusWindow:
    def __init__(self):
        self._q: queue.Queue[str] = queue.Queue()
        self._controller = None
        self._message_token = 0
        self._extra_setup = []  # 主线程启动时回调（供菜单栏/主窗口附加）

    def set_state(self, state: str) -> None:
        """线程安全，从任意线程调用。"""
        self._q.put(state)

    def show_message(self, text: str, seconds: float = 6.0) -> None:
        self._message_token += 1
        token = self._message_token
        self._q.put(("message", text, token))
        threading.Timer(seconds, self._hide_message, args=(token,)).start()

    def show_typing_message(self, text: str, seconds: float = 6.0, interval: float = 0.006) -> None:
        self._message_token += 1
        token = self._message_token
        step = max(1, len(text) // 36)

        def run() -> None:
            for idx in range(step, len(text) + step, step):
                if token != self._message_token:
                    return
                self._q.put(("message", text[:idx], token, text))
                threading.Event().wait(interval)
            threading.Timer(seconds, self._hide_message, args=(token,)).start()

        threading.Thread(target=run, daemon=True, name="StatusTypingMessage").start()

    def _hide_message(self, token: int) -> None:
        self._q.put(("hide_message", token))

    def add_main_thread_setup(self, fn) -> None:
        """注册一个在 NSApp 主循环启动后执行的初始化函数（菜单栏、主窗口构建等）。"""
        self._extra_setup.append(fn)

    def stop(self) -> None:
        AppHelper.callAfter(NSApplication.sharedApplication().stop_, None)

    def run(self) -> None:
        """阻塞，必须在主线程调用。"""
        NSApplication.sharedApplication()
        self._controller = _Controller.alloc().initWithQueue_(self._q)
        self._controller.startPolling()
        for fn in self._extra_setup:
            try:
                fn()
            except Exception as e:
                print(f"[status] 主线程初始化失败: {e}")
        AppHelper.runEventLoop()
