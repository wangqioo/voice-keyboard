"""
Instruction Mode orchestration：speech recognition → intent classification → Voice Text Operation execution

意图分类规则：
  shortcut — 明确的快捷键操作，直接执行
  edit     — 修改/润色/编辑 Explicit Selection 或 Tracked Segment
  write    — 给主题/要求让 AI 生成新内容，直接打入，不自动删除
  undo     — 触发当前输入环境的撤销快捷键
  chat     — 其他（问题、聊天、不确定），只在状态框显示简短 feedback
"""

import queue
import threading

from agent.ai_intent import (
    IntentContext,
    IntentFallbackOptions,
    classify_intent,
    memo_records,
)
from agent.input_environment import TyperInputEnvironment
from agent.instruction_executor import InstructionModeExecutor
from agent.memo import Memo, parse_memo_edit_command
from agent.voice_text_operation import operation_from_intent

_AI_PREFIX = " [AI]: "
_INTENT_TIMEOUT_SECONDS = 12.0


class AIHandler:
    def __init__(self, stt_client, llm_editor, buf, memo_store=None,
                 status_window=None, history=None, input_environment=None, intent_fallbacks=None):
        self._stt             = stt_client
        self._llm             = llm_editor
        self._env             = input_environment or TyperInputEnvironment(buf)
        self._memo_store = memo_store
        self._status          = status_window
        self._history         = history
        self._intent_fallbacks = intent_fallbacks or IntentFallbackOptions()
        self._io_lock         = threading.Lock()   # 串行化所有输入框 IO（删+打）
        self._executor = InstructionModeExecutor(
            self._llm,
            self._env,
            memo_store=self._memo_store,
            show=self._show,
            set_status=self._set_status,
            text_io=self._io_lock,
        )

    def _record(self, mode: str, text: str = "", status: str = "ok", detail: str = ""):
        if self._history is not None:
            try:
                self._history.append(mode, text, status, detail)
            except Exception as e:
                print(f"[ai] history 写入失败: {e}")

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
        memo_edit = parse_memo_edit_command(text)
        if memo_edit is not None:
            result = Memo(self._memo_store).edit_text(
                memo_edit.target,
                memo_edit.old,
                memo_edit.new,
            )
            self._record("ai", text, "ok", "memo_edit")
            self._show(result.message)
            return True

        # 2. 读取上下文（优先用 Explicit Selection，其次用 Tracked Segment）
        target = self._env.target_for_instruction()
        selected = target.selected
        if selected:
            print(f"[ai] Explicit Selection: {selected!r}")
        context = selected or target.tracked_segment
        print(
            "[ai] 目标上下文: "
            f"selected_len={len(selected)} tracked_len={len(target.tracked_segment)}"
        )

        # 3. LLM 意图分类
        try:
            result = self._classify_intent_with_timeout(IntentContext(
                text=text,
                selected=selected,
                recent_text=context,
                active_application=self._env.active_application(),
                shortcuts=self._env.shortcuts(),
                memo_records=memo_records(
                    self._memo_store,
                ),
            ))
        except TimeoutError as e:
            print(f"[ai] 意图分类超时: {e}")
            self._record("ai", text, "error", "intent_timeout")
            if self._status is not None:
                self._status.set_state("error_llm")
            self._show("AI 理解超时，请重试")
            return True
        except Exception as e:
            print(f"[ai] 意图分类失败: {e}，回退到聊天")
            self._record("ai", text, "error", f"LLM: {e}")
            if self._status is not None:
                self._status.set_state("error_llm")
            result = {"type": "chat", "reply": "没听清楚，请再说一次"}

        operation = operation_from_intent(result)
        print(f"[ai] 意图: {operation.kind}")

        keep_status = self._executor.execute(operation, text, selected, target)
        status, detail = getattr(self._executor, "last_status", ("ok", operation.kind))
        self._record("ai", text, status, detail)
        return keep_status

    def _classify_intent_with_timeout(self, context: IntentContext) -> dict:
        out: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=1)

        def run() -> None:
            try:
                out.put(("ok", classify_intent(
                    self._llm,
                    context,
                    self._intent_fallbacks,
                )))
            except Exception as e:
                out.put(("error", e))

        threading.Thread(target=run, daemon=True, name="AIIntentClassifier").start()
        try:
            status, value = out.get(timeout=_INTENT_TIMEOUT_SECONDS)
        except queue.Empty:
            raise TimeoutError(
                f"intent classification exceeded {_INTENT_TIMEOUT_SECONDS:.1f}s"
            )
        if status == "error":
            raise value
        return value

    def _set_status(self, state: str) -> None:
        if self._status is not None:
            self._status.set_state(state)

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
