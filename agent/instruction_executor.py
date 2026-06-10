"""Execution of typed Voice Text Operations for Instruction Mode."""

from contextlib import nullcontext
from dataclasses import replace
import queue
import threading
from typing import Callable, ContextManager

from agent.input_environment import OperationWindow, ReplacementPlan, TextTarget
from agent.punctuation import normalize_spoken_punctuation
from agent.memo import MemoOperationResult, Memo
from agent.ai_intent import looks_like_whole_delete_instruction
from agent.voice_text_operation import VoiceTextOperation

_WRITE_SYSTEM = """你是一个写作助手。根据用户的要求直接输出所需内容，不要有任何前缀、解释或额外说明。只输出内容本身。不要使用换行，所有内容写成连续的段落。必须使用完整的中文标点符号，常用标点包括逗号、句号、冒号、分号、问号、感叹号、破折号、省略号，不得省略任何必要标点。"""

_SENTENCE_END = frozenset('。！？.!?…')
_LOCAL_BREAK = 28
_HARD_BREAK = 52
_CLAUSE_HINTS = (
    "是", "为", "位于", "也是", "成为", "见证", "拥有", "包括", "以及",
    "同时", "此外", "其中", "后来", "经过", "始建于", "原为", "则是",
)
_PROVIDER_CALL_TIMEOUT_SECONDS = 12.0


class ProviderCallTimeout(TimeoutError):
    pass


class InstructionModeExecutor:
    def __init__(
        self,
        llm_editor,
        input_environment,
        memo_store=None,
        show: Callable[[str], None] | None = None,
        set_status: Callable[[str], None] | None = None,
        text_io: ContextManager | None = None,
        provider_call_timeout: float = _PROVIDER_CALL_TIMEOUT_SECONDS,
    ):
        self._llm = llm_editor
        self._env = input_environment
        self._memo = Memo(memo_store)
        self._show = show or (lambda message: print(message))
        self._set_status = set_status or (lambda state: None)
        self._text_io = text_io
        self._provider_call_timeout = provider_call_timeout
        self.last_status: tuple[str, str] = ("ok", "")

    def execute(
        self,
        operation: VoiceTextOperation,
        instruction: str,
        selected: str,
        target: TextTarget | None = None,
    ) -> bool:
        self.last_status = ("ok", operation.kind)
        if operation.kind == "shortcut":
            policy = self._env.shortcut_policy_for_invocation(operation.name)
            if not policy.found:
                self._show_failure(
                    f"没有找到快捷键：{operation.name}",
                    f"shortcut_missing:{operation.name}",
                )
                return True
            elif policy.allowed:
                if not self._env.send_shortcut(operation.name):
                    self._show_failure(
                        f"快捷键执行失败：{operation.name}",
                        f"shortcut_failed:{operation.name}",
                    )
                    return True
                elif policy.risk == "high":
                    print(
                        "[ai] 高风险快捷键已执行: "
                        f"name={policy.name!r} source={policy.source!r} "
                        f"application={policy.application!r}"
                    )
            else:
                self._show_failure(
                    f"快捷键需要确认：{operation.name}",
                    f"shortcut_blocked:{operation.name}",
                )
                return True
        elif operation.kind == "undo":
            self._do_undo()
        elif operation.kind == "delete":
            self._do_delete(instruction, selected)
        elif operation.kind == "edit":
            self._do_edit(instruction, selected, target)
        elif operation.kind == "write":
            return bool(self._do_write(instruction, selected))
        elif operation.kind == "memo_save":
            self._do_memo_save(operation.key, operation.value, selected)
        elif operation.kind == "memo_recall":
            return bool(self._do_memo_recall(operation.key, selected))
        elif operation.kind == "memo_delete":
            self._do_memo_delete(operation.key)
        elif operation.kind == "memo_list":
            return bool(self._do_memo_list(selected))
        else:
            return self._do_chat(instruction, operation)
        return False

    def _mark_error(self, detail: str) -> None:
        self.last_status = ("error", detail)

    def _show_failure(self, message: str, detail: str) -> None:
        self._mark_error(detail)
        self._show(message)

    def _io(self) -> ContextManager:
        return self._text_io if self._text_io is not None else nullcontext()

    def _handle_memo_result(self, result: MemoOperationResult, selected: str = "") -> bool:
        if result.action == "insert":
            insertion = self._env.insert_generated_text(result.text)
            if insertion.failure == "no_focused_input":
                self._show_failure("未点击到输入框，已取消输出", "no_focused_input")
            elif insertion.failure == "copied_to_clipboard":
                self._show_copied(insertion.copied_text or result.text)
                return True
        else:
            self._show(result.message)
        return False

    def _do_chat(self, text: str, operation: VoiceTextOperation) -> bool:
        reply = operation.reply
        if not reply:
            try:
                self._set_status("ai_processing")
                reply = self._llm.chat(
                    "你是一个简短的语音助手。直接回答用户，最多50字，不要解释你的规则。",
                    text,
                ).strip()
            except Exception as e:
                print(f"[ai] 聊天回复失败: {e}")
                self._set_status("error_llm")
                self._show_failure("AI 回复失败，请重试", f"chat:{e}")
                return True
        self._show(reply)
        return True

    def _do_edit(
        self,
        instruction: str,
        selected: str,
        target: TextTarget | None = None,
    ) -> None:
        whole_scope = _is_whole_scope_edit_instruction(instruction)
        window = self._operation_window_or_prompt(
            "修改",
            "编辑",
            target=target,
            prefer_tracked_segment=not whole_scope,
        )
        if window is None:
            return
        if (
            window.source == "caret"
            and window.target.tracked_segment
            and not whole_scope
        ):
            window = replace(
                window,
                text=window.target.tracked_segment,
                source="tracked_segment",
            )
        if window.source != "explicit_selection" and not whole_scope:
            if window.source == "tracked_segment":
                print("[ai] 未框选内容，默认编辑最后一次输出")
            else:
                self._show_failure("请先选中你想修改的内容", "edit_no_target")
                return

        try:
            self._set_status("ai_processing")
            plan = self._replacement_plan(window.text, instruction)
        except ProviderCallTimeout:
            print("[ai] 编辑超时")
            self._set_status("error_llm")
            self._show_failure("处理超时，请重试或先说撤销", "edit_timeout")
            return
        except Exception as e:
            print(f"[ai] 编辑失败: {e}")
            self._set_status("error_llm")
            self._show_failure("AI 编辑失败，请重试", f"edit:{e}")
            return
        print(
            "[ai] 替换计划: "
            f"target={plan.target_text!r} replacement={plan.replacement_text!r}"
        )

        with self._io():
            result = self._env.apply_replacement_plan(window, plan)
        if result.ok:
            return
        elif result.failure in {"target_not_found", "ambiguous_target", "low_confidence"}:
            self._show_failure("没有找到明确可替换的内容", f"edit_{result.failure}")
        else:
            self._show_failure("没有可编辑的内容", f"edit_{result.failure or 'failed'}")

    def _replacement_plan(self, window_text: str, instruction: str) -> ReplacementPlan:
        if hasattr(self._llm, "plan_replacement"):
            plan = self._call_provider(
                lambda: self._llm.plan_replacement(window_text, instruction)
            )
            if isinstance(plan, ReplacementPlan):
                return plan
            if isinstance(plan, dict):
                return ReplacementPlan(
                    target_text=plan.get("target_text", ""),
                    replacement_text=plan.get("replacement_text", ""),
                    confidence=plan.get("confidence", "high"),
                )
        corrected = self._call_provider(lambda: self._llm.edit(window_text, instruction))
        return ReplacementPlan(
            target_text=window_text,
            replacement_text=corrected,
        )

    def _removal_plan(self, window_text: str, instruction: str) -> ReplacementPlan:
        if hasattr(self._llm, "plan_replacement"):
            plan = self._call_provider(
                lambda: self._llm.plan_replacement(window_text, instruction)
            )
            if isinstance(plan, ReplacementPlan):
                return ReplacementPlan(
                    target_text=plan.target_text,
                    replacement_text="",
                    confidence=plan.confidence,
                )
            if isinstance(plan, dict):
                return ReplacementPlan(
                    target_text=plan.get("target_text", ""),
                    replacement_text="",
                    confidence=plan.get("confidence", "high"),
                )
        return ReplacementPlan(target_text=window_text, replacement_text="")

    def _call_provider(self, fn: Callable[[], object]) -> object:
        out: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=1)

        def run() -> None:
            try:
                out.put(("ok", fn()))
            except Exception as e:
                out.put(("error", e))

        worker = threading.Thread(target=run, daemon=True, name="InstructionProviderCall")
        worker.start()
        try:
            status, value = out.get(timeout=self._provider_call_timeout)
        except queue.Empty:
            raise ProviderCallTimeout(
                f"provider call exceeded {self._provider_call_timeout:.1f}s"
            )
        if status == "error":
            raise value
        return value

    def _do_write(self, instruction: str, selected: str) -> bool:
        write_instruction = (
            instruction
            + "（必须加上完整的中文标点符号，包括逗号、句号、冒号、感叹号、问号、破折号、省略号；"
            + "出现“例如、比如、包括、如下”这类引出举例或列表的词时，后面优先使用冒号；"
            + "每20到35个汉字至少使用一个逗号或句号，禁止输出无标点长段。）"
        )
        generated = ""
        try:
            self._set_status("ai_processing")
            for chunk in self._llm.chat_stream(_WRITE_SYSTEM, write_instruction):
                chunk = chunk.replace('\n', ' ').replace('\r', ' ')
                generated += chunk
        except Exception as e:
            print(f"[ai] 写作失败: {e}")
            self._set_status("error_llm")
            self._show_failure("AI 写作失败，请重试", f"write:{e}")
            return False

        text = _finish_write_tail(generated)
        if not text:
            self._show_failure("AI 没有生成内容，请重试", "write_empty")
            return False
        insertion = self._env.insert_generated_text(text)
        if insertion.failure == "no_focused_input":
            self._show_failure("未点击到输入框，已取消输出", "no_focused_input")
            return False
        if insertion.failure == "copied_to_clipboard":
            self._show_copied(insertion.copied_text or text)
            return True

        return False

    def _do_delete(self, instruction: str, selected: str) -> None:
        whole_window_delete = _is_whole_window_delete_instruction(instruction)
        if whole_window_delete:
            lookup = self._env.operation_window_for_instruction(prefer_tracked_segment=False)
            if not lookup.ok:
                if not self._env.delete_all_text_by_shortcut():
                    self._show_failure("没有可删除的内容", f"delete_{lookup.failure}")
                return
            window = lookup.window
        else:
            window = self._operation_window_or_prompt("删除", "删除")
            if window is None:
                return
            if window.source != "explicit_selection":
                self._show_failure("请先选中你想删除的内容", "delete_no_selection")
                return
        try:
            if not whole_window_delete:
                self._set_status("ai_processing")
            plan = (
                ReplacementPlan(target_text=window.text, replacement_text="")
                if whole_window_delete
                else self._removal_plan(window.text, instruction)
            )
        except ProviderCallTimeout:
            print("[ai] 删除超时")
            self._set_status("error_llm")
            self._show_failure("处理超时，请重试或先说撤销", "delete_timeout")
            return
        except Exception as e:
            print(f"[ai] 删除失败: {e}")
            self._set_status("error_llm")
            self._show_failure("AI 删除失败，请重试", f"delete:{e}")
            return
        with self._io():
            result = self._env.apply_replacement_plan(
                window,
                plan,
            )
        if result.ok:
            return
        elif result.failure in {"target_not_found", "ambiguous_target", "low_confidence"}:
            self._show_failure("没有找到明确可删除的内容", f"delete_{result.failure}")
        else:
            self._show_failure("没有可删除的内容", f"delete_{result.failure or 'failed'}")

    def _operation_window_or_prompt(
        self,
        action: str,
        noun: str,
        target: TextTarget | None = None,
        prefer_tracked_segment: bool = True,
    ):
        if prefer_tracked_segment:
            if target is not None and target.selected:
                return OperationWindow(
                    text=target.selected,
                    target=target,
                    source="explicit_selection",
                )
            if target is not None and target.tracked_segment:
                return OperationWindow(
                    text=target.tracked_segment,
                    target=target,
                    source="tracked_segment",
                )
        lookup = self._env.operation_window_for_instruction(
            prefer_tracked_segment=prefer_tracked_segment
        )
        if not lookup.ok:
            self._show_failure(f"没有可{noun}的内容", f"{action}_no_target")
            return None
        return lookup.window

    def _do_undo(self) -> None:
        policy = self._env.shortcut_policy_for_invocation("撤销")
        if policy.found and policy.allowed and self._env.send_shortcut("撤销"):
            return
        self._show_failure("没有找到快捷键：撤销", "undo_missing")

    def _do_memo_save(self, key: str, value: str, selected: str) -> None:
        self._handle_memo_result(self._memo.save(key, value, selected), selected)

    def _do_memo_recall(self, key: str, selected: str) -> bool:
        result = self._memo.recall(key)
        keep_status = self._handle_memo_result(result, selected)
        if result.action == "insert":
            self._show(f"已读取「{key}」")
            return True
        return keep_status

    def _do_memo_list(self, selected: str) -> bool:
        result = self._memo.list_all()
        if result.action == "insert":
            self._show(result.text)
            return True
        return self._handle_memo_result(result, selected)

    def _do_memo_delete(self, key: str) -> None:
        key = (key or "").strip()
        if not key:
            self._handle_memo_result(self._memo.delete(key))
            return
        self._show(f"为避免误删，请在备忘页删除「{key}」")

    def _show_copied(self, text: str) -> None:
        preview = str(text or "").replace("\n", " ")[:60]
        suffix = "…" if len(str(text or "")) > 60 else ""
        self._show(f"已复制：{preview}{suffix}")


def _prefer_tracked_delete_instruction(text: str) -> bool:
    compact = "".join(str(text or "").split()).strip("。.!！？?，,；;：:")
    for prefix in ("我说", "请", "帮我", "麻烦", "麻烦你"):
        if compact.startswith(prefix):
            compact = compact[len(prefix):]
            break
    return compact in {
        "删除",
        "删掉",
        "删了",
        "清除",
        "清空",
        "删除所有",
        "删掉所有",
        "清空所有",
        "删除刚才",
        "删掉刚才",
        "删除上一段",
        "删掉上一段",
        "删除最近输出",
        "删掉最近输出",
    }
def _forced_punctuation_break(text: str) -> tuple[str, str] | None:
    pending = str(text or "")
    compact_len = len(pending.strip())
    if compact_len < _LOCAL_BREAK:
        return None
    cut = _find_local_break(pending)
    if cut is None and compact_len >= _HARD_BREAK:
        cut = _HARD_BREAK
    if cut is None:
        return None
    left = pending[:cut].strip()
    right = pending[cut:].lstrip()
    if not left:
        return None
    punctuation = "。" if len(left) >= _HARD_BREAK else "，"
    return left + punctuation, right


def _find_local_break(text: str) -> int | None:
    window = text[0:min(len(text), _HARD_BREAK)]
    if not window:
        return None
    best = None
    for hint in _CLAUSE_HINTS:
        idx = window.find(hint)
        if idx < 0:
            continue
        absolute = idx
        if absolute > _LOCAL_BREAK:
            best = absolute if best is None else min(best, absolute)
    return best


def _finish_write_tail(text: str) -> str:
    tail = normalize_spoken_punctuation(str(text or "").strip())
    if not tail or tail[-1] in _SENTENCE_END:
        return tail
    return tail + "。"


def _is_whole_window_delete_instruction(text: str) -> bool:
    return looks_like_whole_delete_instruction(text)


def _is_whole_scope_edit_instruction(text: str) -> bool:
    compact = "".join(str(text or "").split()).strip("。.!！？?，,；;：:")
    return any(
        marker in compact
        for marker in (
            "全文",
            "全部",
            "整体",
            "整段",
            "整篇",
            "所有内容",
            "当前内容",
            "整个输入框",
            "输入框内容",
            "输入框里的内容",
            "输入框里面的内容",
        )
    )
