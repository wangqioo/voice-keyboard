"""
全局鼠标监听，检测用户点击，标记 Tracked Segment 为不安全。

当用户点击鼠标时，光标可能已跳到其他位置，此时 Tracked Segment 与
Input Environment 实际内容的对应关系不再可靠。

用途：触发后只需标记，不需要立刻做任何 IO。
"""

from pynput import mouse

class MouseMonitor:
    """监听鼠标点击，标记 Tracked Segment 为不安全。"""

    def __init__(self, input_environment):
        self._env      = input_environment
        self._listener = None

    def start(self):
        self._listener = mouse.Listener(
            on_click=self._on_click,
            daemon=True,
        )
        self._listener.start()
        print("[mouse] 鼠标点击监听已启动（光标位移检测）")

    def stop(self):
        if self._listener:
            self._listener.stop()
            self._listener = None

    def _on_click(self, x, y, button, pressed):
        if pressed:
            # 任意鼠标按键按下时，认为光标位置已改变，同时标记新段落
            self._env.mark_tracked_segment_unsafe()
            self._env.start_new_tracked_segment()
