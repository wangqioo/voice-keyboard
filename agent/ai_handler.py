"""
Instruction Mode orchestration：speech recognition → intent classification → Voice Text Operation execution

意图分类规则：
  shortcut — 明确的快捷键操作，直接执行
  edit     — 修改/润色/编辑 Explicit Selection 或 Tracked Segment
  write    — 给主题/要求让 AI 生成新内容，直接打入，不自动删除
  undo     — 撤回上一次 Instruction Mode operation（恢复被删的原文，或删掉写入的内容）
  chat     — 其他（问题、聊天、不确定），回复打到输入框后按字数自动删除
"""

import threading

from agent.ai_intent import IntentContext, classify_intent, memo_keys
from agent.input_environment import TyperInputEnvironment
from agent.instruction_executor import InstructionModeExecutor
from agent.operation_history import OperationHistory
from agent.voice_text_operation import operation_from_intent

_AI_PREFIX = " [AI]: "


class AIHandler:
    def __init__(self, stt_client, llm_editor, buf, memo_store=None, status_window=None,
                 history=None, input_environment=None):
        self._stt             = stt_client
        self._llm             = llm_editor
        self._env             = input_environment or TyperInputEnvironment(buf)
        self._memos           = memo_store
        self._status          = status_window
        self._history         = history
        self._last_ai_output  = ""
        self._erase_timer: threading.Timer | None = None
        self._lock            = threading.Lock()   # 保护数据字段
        self._io_lock         = threading.Lock()   # 串行化所有输入框 IO（删+打）
        self._operation_history = OperationHistory(limit=5)
        self._executor = InstructionModeExecutor(
            self._llm,
            self._env,
            self._operation_history,
            memo_store=self._memos,
            show=self._show,
            set_status=self._set_status,
            text_io=self._io_lock,
            clear_pending_output=self._clear_pending_ai_output,
        )

    @property
    def _undo_stack(self) -> list[tuple[str, str, str]]:
        """Compatibility view for older tests and debugging code."""
        out: list[tuple[str, str, str]] = []
        for effect in self._operation_history.snapshot():
            if effect.kind == "insert":
                out.append(("write", effect.old_text, effect.new_text))
            else:
                out.append(("edit", effect.old_text, effect.new_text))
        return out

    def _record(self, mode: str, text: str = "", status: str = "ok", detail: str = ""):
        if self._history is not None:
            try:
                self._history.append(mode, text, status, detail)
            except Exception as e:
                print(f"[ai] history 写入失败: {e}")

    def on_ai_key_down(self) -> None:
        """AI 键按下时立即调用，取消定时器，但保留待删文字供 _run() 处理。"""
        with self._lock:
            if self._erase_timer is not None:
                self._erase_timer.cancel()
                self._erase_timer = None

    def handle(self, pcm: bytes) -> None:
        """AI 键松开后调用，在后台线程执行。"""
        threading.Thread(target=self._run, args=(pcm,), daemon=True, name="AIHandler").start()

    # ── 内部流程 ──────────────────────────────────────────────────────

    def _run(self, pcm: bytes) -> None:
        keep_status = False
        try:
            keep_status = bool(self._run_inner(pcm))
        finally:
            if self._status is not None and not keep_status:
                self._status.set_state("idle")

    def _run_inner(self, pcm: bytes) -> None:
        # 0. 删掉上一条 AI 文字（此时 Command 已松开，不会触发 Cmd+Backspace）
        with self._io_lock:
            with self._lock:
                pending = self._last_ai_output
                self._last_ai_output = ""
            if pending:
                self._env.erase_text(pending)

        # 1. STT 识别
        try:
            text = self._stt.transcribe(pcm)
        except Exception as e:
            print(f"[ai] STT 失败: {e}")
            self._record("ai", "", "error", f"STT: {e}")
            self._show_error_message(e)
            if self._status is not None:
                self._status.set_state("error_stt")
            return
        if not text:
            print("[ai] 未识别到内容")
            self._record("ai", "", "empty")
            if self._status is not None:
                self._status.set_state("empty_stt")
            return True
        print(f"[ai] 识别: {text!r}")
        self._record("ai", text, "ok")

        # 2. 读取上下文（优先用 Explicit Selection，其次用 Tracked Segment）
        target = self._env.target_for_instruction()
        selected = target.selected
        if selected:
            print(f"[ai] Explicit Selection: {selected!r}")
        context = selected or target.tracked_segment

        # 3. LLM 意图分类
        try:
            result = classify_intent(self._llm, IntentContext(
                text=text,
                selected=selected,
                recent_text=context,
                active_application=self._env.active_application(),
                shortcuts=self._env.shortcuts(),
                memo_keys=memo_keys(self._memos),
            ))
        except Exception as e:
            print(f"[ai] 意图分类失败: {e}，回退到聊天")
            self._record("ai", text, "error", f"LLM: {e}")
            if self._status is not None:
                self._status.set_state("error_llm")
            result = {"type": "chat", "reply": "没听清楚，请再说一次"}

        operation = operation_from_intent(result)
        print(f"[ai] 意图: {operation.kind}")

        return self._executor.execute(operation, text, selected)

    def _set_status(self, state: str) -> None:
        if self._status is not None:
            self._status.set_state(state)

    def _clear_pending_ai_output(self) -> None:
        with self._lock:
            if self._erase_timer is not None:
                self._erase_timer.cancel()
                self._erase_timer = None
            pending = self._last_ai_output
            self._last_ai_output = ""
        if pending:
            self._env.erase_text(pending)

    def _show(self, message: str) -> None:
        """Show AI/chat feedback in the floating status HUD."""
        message = message.replace("\n", " ").replace("\r", "")
        delay = max(3.0, min(12.0, len(message) * 0.18))
        full = _AI_PREFIX.strip() + " " + message
        if self._status is not None and hasattr(self._status, "show_typing_message"):
            self._status.show_typing_message(full, delay)
        elif self._status is not None and hasattr(self._status, "show_message"):
            self._status.show_message(full, delay)
        else:
            print(f"{_AI_PREFIX}{message}")

    def _show_error_message(self, error: Exception) -> None:
        msg = str(error)
        if "敏感" in msg or "不安全" in msg or "unsafe" in msg.lower():
            self._show("识别内容被服务商拦截，请松开热键后重新说。可用启停热键快速恢复。")

    def _auto_erase(self, expected: str) -> None:
        with self._io_lock:
            with self._lock:
                if self._last_ai_output != expected:
                    return
                self._last_ai_output = ""
                self._erase_timer = None
            self._env.erase_text(expected)
