"""
记录 Voice Keyboard Engine 打出的文字历史，供 Instruction Mode 使用。

只记录通过 Voice Keyboard Engine 打出去的内容，用户手动输入的内容不在此范围。
Input Environment adapter 会把 Backspace 等事件同步到这里。

Tracked Segment 安全标志：
  鼠标点击等事件会让追踪位置变得不安全。
  Instruction Mode 修改已有文本时，只有安全的 Tracked Segment 才能被隐式修改。
"""


class TextBuffer:
    def __init__(self, max_entries: int = 20):
        self._entries: list[str]  = []
        self._max                 = max_entries
        self._segment_start: int  = 0   # Tracked Segment 在 _entries 中的起始索引
        self.cursor_uncertain: bool = False   # Tracked Segment 是否不安全

    # ── 写入 / 读取 ────────────────────────────────────────────────

    def push(self, text: str) -> None:
        """Voice Keyboard Engine 打出一段文字后调用，加入历史。"""
        if text:
            self._entries.append(text)
            if len(self._entries) > self._max:
                self._entries.pop(0)
                self._segment_start = max(0, self._segment_start - 1)
            # 新打出一段话 → 说明光标就在刚打的文字后面，位置可信
            self.cursor_uncertain = False

    def new_segment(self) -> None:
        """回车或鼠标点击时调用，标记新的 Tracked Segment 起始位置。"""
        self._segment_start = len(self._entries)

    def pop_last(self) -> str:
        return self._entries.pop() if self._entries else ""

    def replace_last(self, new_text: str) -> None:
        if self._entries:
            self._entries[-1] = new_text

    @property
    def last(self) -> str:
        return self._entries[-1] if self._entries else ""

    @property
    def current_segment(self) -> str:
        """Tracked Segment 的全部文字（上次回车/鼠标点击之后打的内容）。"""
        return "".join(self._entries[self._segment_start:])

    @property
    def session(self) -> str:
        """当前 session 打出的全部文字（拼接）。"""
        return "".join(self._entries)

    def replace_segment(self, new_text: str) -> None:
        """用 new_text 替换 Tracked Segment 的全部内容。"""
        del self._entries[self._segment_start:]
        if new_text:
            self._entries.append(new_text)
            self._segment_start = len(self._entries) - 1
        else:
            self._segment_start = len(self._entries)
        self.cursor_uncertain = False

    def clear(self) -> None:
        self._entries.clear()
        self._segment_start = 0

    def __bool__(self) -> bool:
        return bool(self._entries)

    # ── Backspace 同步 ─────────────────────────────────────────────

    def trim_end(self, n: int) -> None:
        """
        用户手动按了 n 次 Backspace，从 Tracked Segment 末尾截掉 n 个字符。

        若 n 超过了最后一段的长度，会继续向上一段截（递归）。
        """
        if n <= 0 or not self._entries:
            return
        last = self._entries[-1]
        if n >= len(last):
            # 退格超过了当前最后一段，弹出整段，继续截上一段
            overflow = n - len(last)
            self._entries.pop()
            if overflow > 0:
                self.trim_end(overflow)
        else:
            self._entries[-1] = last[:-n]
