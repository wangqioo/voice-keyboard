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
    classify_intent_details,
    looks_like_memo_save_command,
    memo_records,
    shortcut_intent_entries,
)
from agent.input_environment import TyperInputEnvironment
from agent.instruction_executor import InstructionModeExecutor
from agent.intent_training import IntentTrainingRecorder
from agent.memo import Memo, parse_memo_edit_command
from agent.voice_text_operation import operation_from_intent

_AI_PREFIX = " [AI]: "
_INTENT_TIMEOUT_SECONDS = 12.0
_PROGRESS_SECONDS = 2.2
_AI_FINAL_MIN_SECONDS = 3.0
_AI_FINAL_MAX_SECONDS = 12.0

_SESSION_STATE_MESSAGES = {
    "ai_processing": "AI 处理中",
    "error_stt": "识别失败",
    "empty_stt": "未识别到语句",
    "error_typing": "打字失败",
    "error_llm": "AI 处理失败",
    "error_perm": "权限未授予",
}
_SESSION_ERROR_STATES = {
    "error_stt",
    "empty_stt",
    "error_typing",
    "error_llm",
    "error_perm",
}



class AIHandler:
    def __init__(self, stt_client, llm_editor, buf, memo_store=None,
                 status_window=None, history=None, input_environment=None,
                 intent_fallbacks=None, intent_training=None):
        self._stt             = stt_client
        self._llm             = llm_editor
        self._env             = input_environment or TyperInputEnvironment(buf)
        self._memo_store = memo_store
        self._status          = status_window
        self._history         = history
        self._intent_fallbacks = intent_fallbacks or IntentFallbackOptions()
        self._intent_training = intent_training or IntentTrainingRecorder()
        self._io_lock         = threading.Lock()   # 串行化所有输入框 IO（删+打）
        self._active_ai_text = ""
        self._ai_result_kind = "done"
        self._status_result_visible = False
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
        self._status_result_visible = False
        try:
            keep_status = bool(self._run_inner(pcm))
        finally:
            if self._status is not None and not keep_status and not self._status_result_visible:
                self._status.set_state("idle")
            self._active_ai_text = ""
            self._ai_result_kind = "done"
            self._status_result_visible = False

    def _run_inner(self, pcm: bytes) -> None:
        # 1. STT 识别
        try:
            text = self._stt.transcribe(pcm)
        except Exception as e:
            print(f"[ai] STT 失败: {e}")
            self._record("ai", "", "error", f"STT: {e}")
            self._show_error_message(e)
            self._set_status("error_stt")
            return
        if not text:
            print("[ai] 未识别到内容")
            self._record("ai", "", "empty")
            self._set_status("empty_stt")
            return True
        print(f"[ai] 识别: {text!r}")
        self._active_ai_text = text
        self._show_progress("已识别语音")
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
            self._show_progress("\u6b63\u5728\u7406\u89e3\u6307\u4ee4")
            shortcuts = self._env.shortcuts()
            shortcut_entries = shortcut_intent_entries(
                self._env.shortcut_catalog() if hasattr(self._env, "shortcut_catalog") else ()
            )
            classification_context = IntentContext(
                text=text,
                selected=selected,
                recent_text=context,
                active_application=self._env.active_application(),
                shortcuts=shortcuts,
                shortcut_entries=shortcut_entries,
                memo_records=memo_records(
                    self._memo_store,
                ),
            )
            classification = self._classify_intent_with_timeout(classification_context)
            result = classification.result
        except TimeoutError as e:
            print(f"[ai] 意图分类超时: {e}")
            self._record("ai", text, "error", "intent_timeout")
            self._set_status("error_llm")
            self._show("AI 理解超时，请重试")
            return True
        except Exception as e:
            print(f"[ai] 意图分类失败: {e}，回退到聊天")
            self._record("ai", text, "error", f"LLM: {e}")
            self._set_status("error_llm")
            result = {"type": "chat", "reply": "没听清楚，请再说一次"}

        result = self._memo_save_fallback_result(text, selected, result)
        operation = operation_from_intent(result)
        intent_source = result.get("_intent_source", "unknown")
        intent_confidence = result.get("_intent_confidence", "")
        cache_hit = bool(result.get("_intent_cache_hit"))
        print(
            f"[ai] intent: {operation.kind} "
            f"source={intent_source} confidence={intent_confidence} cache={cache_hit}"
        )
        self._show_progress(_operation_message(operation))

        keep_status = self._executor.execute(operation, text, selected, target)
        status, detail = getattr(self._executor, "last_status", ("ok", operation.kind))
        intent_detail = _intent_detail(detail, intent_source, intent_confidence, cache_hit)
        self._intent_training.record(
            text=text,
            active_application=classification_context.active_application,
            selected=selected,
            recent_text=context,
            shortcuts=classification_context.shortcuts,
            intent_result=result,
            status=status,
            detail=intent_detail,
        )
        self._record("ai", text, status, intent_detail)
        return keep_status

    def _memo_save_fallback_result(self, text: str, selected: str, result: dict) -> dict:
        if result.get("type") == "memo_save":
            return result
        if not selected or not looks_like_memo_save_command(text, self._intent_fallbacks.memo_triggers):
            return result
        key = self._extract_memo_key(text)
        if not key:
            return result
        print(f"[memo] 保存兜底启用 key={key!r}")
        return {
            "type": "memo_save",
            "key": key,
            "value": "",
            "_intent_source": "local",
            "_intent_confidence": "high",
        }

    def _extract_memo_key(self, text: str) -> str:
        system = (
            "你只负责给一段已选中文本取一个短名称。"
            "根据用户的话提炼 key，输出 2 到 12 个中文字符或简短英文短语。"
            "不要解释，不要标点，不要输出 JSON。"
        )
        user = f"用户说：{text}\n这段选中文本应该记为什么名字？"
        try:
            key = str(self._llm.chat(system, user) or "").strip()
        except Exception as e:
            print(f"[memo] key 提炼失败: {e}")
            key = ""
        key = _clean_memo_key(key)
        if key:
            return key
        return _fallback_memo_key(text)

    def _classify_intent_with_timeout(self, context: IntentContext) -> dict:
        out: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=1)

        def run() -> None:
            try:
                out.put(("ok", classify_intent_details(
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
        if self._status is None:
            return
        if self._active_ai_text and hasattr(self._status, "show_ai_progress"):
            if state in _SESSION_ERROR_STATES:
                self._ai_result_kind = "error"
            message = _SESSION_STATE_MESSAGES.get(state)
            if message:
                self._status.show_ai_progress(_preview(self._active_ai_text, 80), message)
                return
        self._status.set_state(state)

    def _show_progress(self, message: str) -> None:
        """Show short non-typing progress feedback while an AI command runs."""
        if (
            self._status is not None
            and self._active_ai_text
            and hasattr(self._status, "show_ai_progress")
        ):
            self._status.show_ai_progress(_preview(self._active_ai_text, 80), message)
            return
        full = _AI_PREFIX.strip() + " " + message
        if self._status is not None and hasattr(self._status, "show_message"):
            self._status.show_message(full, _PROGRESS_SECONDS)
        else:
            print(f"{_AI_PREFIX}{message}")

    def _show(self, message: str) -> None:
        """Show AI/chat feedback in the floating status HUD."""
        message = message.replace("\n", " ").replace("\r", "")
        delay = max(_AI_FINAL_MIN_SECONDS, min(_AI_FINAL_MAX_SECONDS, len(message) * 0.18))
        if (
            self._status is not None
            and self._active_ai_text
            and hasattr(self._status, "show_ai_result")
        ):
            kind = self._ai_result_kind
            if _looks_like_error_feedback(message):
                kind = "error"
            self._status.show_ai_result(
                _preview(self._active_ai_text, 80),
                message,
                delay,
                kind,
            )
            self._status_result_visible = True
            self._ai_result_kind = "done"
            return
        full = _AI_PREFIX.strip() + " " + message
        if self._status is not None and hasattr(self._status, "show_typing_message"):
            self._status.show_typing_message(full, delay)
            self._status_result_visible = True
        elif self._status is not None and hasattr(self._status, "show_message"):
            self._status.show_message(full, delay)
            self._status_result_visible = True
        else:
            print(f"{_AI_PREFIX}{message}")

    def _show_error_message(self, error: Exception) -> None:
        msg = str(error)
        if "敏感" in msg or "不安全" in msg or "unsafe" in msg.lower():
            self._show("识别内容被服务商拦截，请松开热键后重新说。可用启停热键快速恢复。")


def _looks_like_error_feedback(message: str) -> bool:
    text = str(message or "")
    error_markers = (
        "失败",
        "没有",
        "未",
        "请先",
        "取消",
        "超时",
        "没听清",
        "没记过",
        "需要确认",
    )
    return any(marker in text for marker in error_markers)


def _intent_detail(detail: str, source: str, confidence: str, cache_hit: bool) -> str:
    parts = [detail] if detail else []
    if source:
        parts.append(f"intent_source={source}")
    if confidence:
        parts.append(f"intent_confidence={confidence}")
    if cache_hit:
        parts.append("intent_cache_hit=true")
    return ";".join(parts)

def _preview(text: str, limit: int = 28) -> str:
    compact = str(text or "").replace("\n", " ").replace("\r", " ").strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."


def _operation_message(operation) -> str:
    if operation.kind == "shortcut":
        return f"\u51c6\u5907\u6267\u884c\u5feb\u6377\u952e\uff1a{operation.name or '\u672a\u547d\u540d'}"
    labels = {
        "undo": "\u51c6\u5907\u64a4\u9500",
        "delete": "\u51c6\u5907\u5220\u9664\u5185\u5bb9",
        "edit": "\u51c6\u5907\u7f16\u8f91\u5185\u5bb9",
        "write": "\u51c6\u5907\u751f\u6210\u6587\u5b57",
        "memo_save": "\u51c6\u5907\u4fdd\u5b58\u8bb0\u5fc6",
        "memo_recall": "\u51c6\u5907\u8bfb\u53d6\u8bb0\u5fc6",
        "memo_delete": "\u51c6\u5907\u5220\u9664\u8bb0\u5fc6",
        "memo_list": "\u51c6\u5907\u5217\u51fa\u8bb0\u5fc6",
        "chat": "\u51c6\u5907\u663e\u793a\u56de\u7b54",
    }
    return labels.get(operation.kind, "\u51c6\u5907\u6267\u884c\u6307\u4ee4")

def _clean_memo_key(key: str) -> str:
    key = str(key or "").strip().strip("。.!！？?，,；;：:\"'“”‘’` ")
    if key.startswith("{"):
        return ""
    for prefix in ("名称是", "名字是", "key是", "Key是", "记为", "保存为"):
        if key.startswith(prefix):
            key = key[len(prefix):].strip()
            break
    return key[:32].strip()


def _fallback_memo_key(text: str) -> str:
    compact = "".join(
        char for char in str(text or "").strip()
        if char not in " \t\r\n。.!！?？,，;；:：\"'“”‘’"
    )
    for marker in ("记一下", "记住", "记下", "备忘"):
        compact = compact.replace(marker, "")
    for prefix in ("这是我的", "这个是我的", "这条是我的", "这是", "这个是", "这条是", "我的"):
        if compact.startswith(prefix):
            compact = compact[len(prefix):]
            break
    return _clean_memo_key(compact) or "备忘"
