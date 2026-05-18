"""
全局键盘监听，追踪用户手动按 Backspace / Delete，实时同步 Tracked Segment。

设计要点：
  - 只监听 Backspace 和 Delete 两个键，不干扰其他按键逻辑
  - typer.py 调用 erase_last() 时会设置 _erasing=True 标志，
    此时 pynput 回调也会收到我们自己发出的退格事件，
    通过 typer.is_erasing() 判断并忽略，避免双重扣减
  - 运行在独立守护线程，不阻塞主流程

已知限制：
  监听是全局的，用户在其他应用按退格时也会触发追踪状态更新。
  缓解措施：超过 TRACK_TIMEOUT 秒没有语音输出，停止追踪退格，
  同时标记 Tracked Segment 为不安全，避免隐式修改错误位置。
"""

import time

from pynput import keyboard as kb

import agent.typer as typer
# 超过此时长（秒）没有语音输出，退格不再同步 Tracked Segment。
# 避免用户切到其他应用按退格时污染追踪状态。
TRACK_TIMEOUT = 30.0


class KeyboardMonitor:
    """监听 Backspace/Delete，实时同步 Tracked Segment。

    设计：不再自己开 pynput.Listener。由 PushToTalk 的 listener 顺手调用
    process_press(key)，把全局只剩一个键盘 CGEventTap，避免事件被 Python
    多次 round-trip 拖慢系统输入（尤其切换中文输入法时）。
    """

    def __init__(self, input_environment):
        self._env           = input_environment
        self._last_voice_ts = 0.0   # 上次语音输出的时间戳

    def notify_voice_output(self) -> None:
        """每次语音打字后调用，刷新追踪窗口。"""
        self._last_voice_ts = time.monotonic()

    def _within_track_window(self) -> bool:
        return (time.monotonic() - self._last_voice_ts) < TRACK_TIMEOUT

    def start(self):
        # 不再创建独立 listener，仅打印启用提示
        print(f"[kbd] 键盘退格同步已启用（共享 PTT 监听；{TRACK_TIMEOUT}s 内同步 Tracked Segment）")

    def stop(self):
        # 没有自己的 listener，无需 stop
        pass

    def process_press(self, key):
        """供 PushToTalk 在 on_press 里调用——不创建独立 CGEventTap。"""
        # 忽略我们自己调用 erase_last 时发出的退格
        if typer.is_erasing():
            return

        if key == kb.Key.backspace:
            if self._within_track_window():
                self._env.trim_tracked_segment_end(1)
            else:
                self._env.mark_tracked_segment_unsafe()
        elif key == kb.Key.delete:
            self._env.mark_tracked_segment_unsafe()
