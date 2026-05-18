"""Dictation Mode pipeline for the Voice Keyboard Engine."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from agent.input_environment import TyperInputEnvironment
from agent.punctuation import normalize_spoken_punctuation
from agent.text_buffer import TextBuffer


class SpeechTranscriber(Protocol):
    def transcribe(self, pcm: bytes) -> str:
        ...


class PolishTranscriber(SpeechTranscriber, Protocol):
    def transcribe_polished(self, pcm: bytes) -> str:
        ...


class TextPolisher(Protocol):
    def chat(self, system_prompt: str, user_message: str) -> str:
        ...


_POLISH_SYSTEM = """你是文字润色助手。对用户说的话做最轻度的润色：
- 去掉口语填充词（嗯、啊、呃、那个、就是说、然后呢之类）
- 修正明显的错别字和不通顺的地方
- 只有完整句子才加合适的标点；短词、成语、标题、姓名、专有名词、搜索词、命令片段不要补句末标点

严格遵守：保留原意和说话风格，不要扩写、不要总结、不要改写措辞。
直接输出润色后的文字，不要任何解释、前缀或引号。"""


_POLISH_LABEL_RE = re.compile(r"^(?:润色后|润色结果|修改后|修改结果|优化后|优化结果|结果|输出)\s*[:：]\s*")
_LEADING_INVISIBLE_RE = re.compile(r"^[\s\ufeff\u200b\u200c\u200d]+")
_LEADING_HASH_MARK_RE = re.compile(r"^[#＃]{1,6}[\s:：、，。,.!?！？;；-]*")
_TERMINAL_PUNCTUATION_RE = re.compile(r"[。.!！？?]+$")
_INTERNAL_PUNCTUATION_RE = re.compile(r"[，,、；;：:]")
_ASCII_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _./+#-]*$")
_SENTENCE_HINT_RE = re.compile(
    r"(是|有|在|了|吗|呢|吧|啊|呀|嘛|得|把|被|给|让|想|要|需要|可以|应该|"
    r"不是|没有|不能|因为|所以|但是|如果|然后|就是|我们|你们|他们|这个|那个|"
    r"今天|明天|昨天|天气|不错|很好|很|比较|特别|已经|正在|出现|变成)"
)


def clean_generated_text(text: str) -> str:
    cleaned = str(text or "").strip().strip("\"'“”")
    for _ in range(4):
        before = cleaned
        cleaned = _LEADING_INVISIBLE_RE.sub("", cleaned)
        cleaned = _LEADING_HASH_MARK_RE.sub("", cleaned).strip()
        if cleaned == before:
            break
    return cleaned.strip().strip("\"'“”")


def clean_polished_text(text: str) -> str:
    cleaned = clean_generated_text(text)
    cleaned = re.sub(r"^```(?:\w+)?\s*", "", cleaned).strip()
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    for _ in range(3):
        before = cleaned
        cleaned = _POLISH_LABEL_RE.sub("", cleaned).strip()
        cleaned = clean_generated_text(cleaned)
        cleaned = re.sub(r"^[-*•]\s+", "", cleaned).strip()
        if cleaned == before:
            break
    return normalize_dictation_punctuation(clean_generated_text(cleaned))


def normalize_dictation_punctuation(text: str) -> str:
    normalized = normalize_spoken_punctuation(text)
    return strip_terminal_punctuation_for_short_fragment(normalized)


def strip_terminal_punctuation_for_short_fragment(text: str) -> str:
    """Remove model-added sentence punctuation for short words/phrases.

    Micro-polish should not turn a dictated term such as "时间复杂度" or an idiom
    into "时间复杂度。". The rule is intentionally conservative: only strip final
    sentence punctuation when the result looks like a short fragment rather than
    a complete sentence.
    """
    cleaned = str(text or "").strip()
    if not cleaned or not _TERMINAL_PUNCTUATION_RE.search(cleaned):
        return cleaned
    stem = _TERMINAL_PUNCTUATION_RE.sub("", cleaned).strip()
    if not stem:
        return cleaned
    if looks_like_short_fragment(stem):
        return stem
    return cleaned


def looks_like_short_fragment(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    if not compact:
        return False
    if _INTERNAL_PUNCTUATION_RE.search(compact):
        return False
    if _ASCII_RE.match(compact):
        return False
    if len(compact) == 4 and not _SENTENCE_HINT_RE.search(compact):
        return True
    if len(compact) <= 8 and not _SENTENCE_HINT_RE.search(compact):
        return True
    return False


@dataclass
class DictationMode:
    """Owns Dictation Mode interpretation, insertion, status, and history."""

    transcriber: SpeechTranscriber
    input_environment: object
    kbd_monitor: object | None = None
    text_polisher: TextPolisher | None = None
    status_window: object | None = None
    history: object | None = None

    def handle_utterance(
        self,
        pcm: bytes,
        polish: bool = False,
        clear_status: bool = True,
        progress_status: bool = True,
    ) -> None:
        mode = "polish" if polish else "dictate"
        try:
            text = self._transcribe(pcm, polish)
        except Exception as e:
            print(f"[stt] 请求失败: {e}")
            self._append_history(mode, "", "error", f"STT: {e}")
            self._show_error_message(e)
            if progress_status:
                self._set_status("error_stt")
            return

        text = normalize_dictation_punctuation(clean_generated_text(text))
        if not text:
            print("[stt] 识别结果为空")
            self._append_history(mode, "", "empty")
            if progress_status:
                self._set_status("empty_stt")
            return

        print(f"[stt] {text!r}")
        if polish and self.text_polisher is not None:
            if progress_status:
                self._set_status("polishing")
            text = self._polish_text(text)

        try:
            result = self.input_environment.insert_output_text(text)
            if not result.ok:
                if result.failure == "copied_to_clipboard":
                    self._append_history(mode, text, "copied", "no_focused_input")
                    self._show_copied_message(result.copied_text or text)
                    return
                raise RuntimeError(result.failure or "insert_failed")
        except Exception as e:
            if str(e) == "no_focused_input":
                self._append_history(mode, text, "cancelled", "no_focused_input")
                self._show("未点击到输入框，已取消输出")
                if progress_status:
                    self._set_status("idle")
                return
            print(f"[stt] 打字失败: {e}")
            if progress_status:
                self._set_status("error_typing")
            self._append_history(mode, text, "error", f"typing: {e}")
            return

        self._append_history(mode, text, "ok")
        if self.kbd_monitor is not None:
            self.kbd_monitor.notify_voice_output()
        if clear_status:
            self._set_status("idle")
            print("[typeup] 输入完成")

    def _transcribe(self, pcm: bytes, polish: bool) -> str:
        if polish and hasattr(self.transcriber, "transcribe_polished"):
            return self.transcriber.transcribe_polished(pcm)  # type: ignore[attr-defined]
        return self.transcriber.transcribe(pcm)

    def _polish_text(self, text: str) -> str:
        try:
            polished = clean_polished_text(self.text_polisher.chat(_POLISH_SYSTEM, text))  # type: ignore[union-attr]
            if polished:
                print(f"[stt] 微润色 → {polished!r}")
                return polished
        except Exception as e:
            print(f"[stt] 润色失败，回退原文: {e}")
        return text

    def _set_status(self, state: str) -> None:
        if self.status_window is not None:
            self.status_window.set_state(state)

    def _show(self, message: str) -> None:
        if self.status_window is not None and hasattr(self.status_window, "show_message"):
            self.status_window.show_message(message, 5.0)
        else:
            print(f"[stt] {message}")

    def _show_copied_message(self, text: str) -> None:
        preview = str(text or "").replace("\n", " ")[:60]
        suffix = "…" if len(str(text or "")) > 60 else ""
        self._show(f"已复制：{preview}{suffix}")

    def _append_history(
        self,
        mode: str,
        text: str,
        status: str = "ok",
        detail: str = "",
    ) -> None:
        if self.history is not None:
            self.history.append(mode, text, status, detail)

    def _show_error_message(self, error: Exception) -> None:
        msg = str(error)
        if "敏感" in msg or "不安全" in msg or "unsafe" in msg.lower():
            message = "识别内容被服务商拦截，请松开热键后重新说。可用启停热键快速恢复。"
            if self.status_window is not None and hasattr(self.status_window, "show_message"):
                self.status_window.show_message(message, 5.0)
            else:
                print(f"[stt] {message}")


def make_utterance_handler(
    stt_client,
    buf: TextBuffer,
    kbd_mon=None,
    editor=None,
    status_window=None,
    history=None,
    input_environment=None,
):
    env = input_environment or TyperInputEnvironment(buf)
    mode = DictationMode(
        stt_client,
        env,
        kbd_monitor=kbd_mon,
        text_polisher=editor,
        status_window=status_window,
        history=history,
    )
    return mode.handle_utterance
