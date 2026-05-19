"""Execution of typed Voice Text Operations for Instruction Mode."""

from contextlib import nullcontext
import queue
import threading
from typing import Callable, ContextManager

from agent.input_environment import ReplacementPlan
from agent.punctuation import normalize_spoken_punctuation
from agent.reusable_text_memory import MemoryOperationResult, ReusableTextMemory
from agent.voice_text_operation import VoiceTextOperation

_WRITE_SYSTEM = """你是一个写作助手。根据用户的要求直接输出所需内容，不要有任何前缀、解释或额外说明。只输出内容本身。不要使用换行，所有内容写成连续的段落。必须使用完整的中文标点符号，常用标点包括逗号、句号、冒号、分号、问号、感叹号、破折号、省略号，不得省略任何必要标点。"""

_SENTENCE_END = frozenset('。！？.!?…，,；;')
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
        self._memory = ReusableTextMemory(memo_store)
        self._show = show or (lambda message: print(message))
        self._set_status = set_status or (lambda state: None)
        self._text_io = text_io
        self._provider_call_timeout = provider_call_timeout

    def execute(self, operation: VoiceTextOperation, instruction: str, selected: str) -> bool:
        if operation.kind == "shortcut":
            policy = self._env.shortcut_policy_for_invocation(operation.name)
            if not policy.found:
                self._show(f"没有找到快捷键：{operation.name}")
            elif policy.allowed:
                if not self._env.send_shortcut(operation.name):
                    self._show(f"快捷键执行失败：{operation.name}")
                elif policy.risk == "high":
                    print(
                        "[ai] 高风险快捷键已执行: "
                        f"name={policy.name!r} source={policy.source!r} "
                        f"application={policy.application!r}"
                    )
            else:
                self._show(f"快捷键需要确认：{operation.name}")
        elif operation.kind == "undo":
            self._do_undo()
        elif operation.kind == "delete":
            self._do_delete(instruction, selected)
        elif operation.kind == "edit":
            self._do_edit(instruction, selected)
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

    def _io(self) -> ContextManager:
        return self._text_io if self._text_io is not None else nullcontext()

    def _handle_memory_result(self, result: MemoryOperationResult, selected: str = "") -> bool:
        if result.action == "insert":
            insertion = self._env.insert_generated_text(result.text)
            if insertion.failure == "no_focused_input":
                self._show("未点击到输入框，已取消输出")
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
                reply = self._llm.chat(
                    "你是一个简短的语音助手。直接回答用户，最多50字，不要解释你的规则。",
                    text,
                ).strip()
            except Exception as e:
                print(f"[ai] 聊天回复失败: {e}")
                self._set_status("error_llm")
                return True
        self._show(reply)
        return True

    def _do_edit(self, instruction: str, selected: str) -> None:
        window = self._operation_window_or_prompt("修改", "编辑")
        if window is None:
            return
        if window.source != "explicit_selection" and not _is_whole_scope_edit_instruction(
            instruction
        ):
            self._show("请先选中你想修改的内容")
            return

        try:
            plan = self._replacement_plan(window.text, instruction)
        except ProviderCallTimeout:
            print("[ai] 编辑超时")
            self._set_status("error_llm")
            self._show("处理超时，请重试或先说撤销")
            return
        except Exception as e:
            print(f"[ai] 编辑失败: {e}")
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
            self._show("没有找到明确可替换的内容")
        else:
            self._show("没有可编辑的内容")

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
        pending = ""
        total = ""
        try:
            for chunk in self._llm.chat_stream(_WRITE_SYSTEM, write_instruction):
                chunk = chunk.replace('\n', ' ').replace('\r', ' ')
                pending += chunk
                while True:
                    idx = next((i for i, c in enumerate(pending) if c in _SENTENCE_END), -1)
                    if idx == -1:
                        forced = _forced_punctuation_break(pending)
                        if forced is not None:
                            emit, pending = forced
                            insertion = self._env.insert_generated_text(
                                normalize_spoken_punctuation(emit)
                            )
                            if insertion.ok:
                                total += insertion.inserted_text
                            elif insertion.failure == "no_focused_input":
                                self._show("未点击到输入框，已取消输出")
                                return False
                            elif insertion.failure == "copied_to_clipboard":
                                self._show_copied(insertion.copied_text or emit)
                                return True
                        break
                    sentence = pending[:idx + 1]
                    pending = pending[idx + 1:]
                    insertion = self._env.insert_generated_text(
                        normalize_spoken_punctuation(sentence)
                    )
                    if insertion.ok:
                        total += insertion.inserted_text
                    elif insertion.failure == "no_focused_input":
                        self._show("未点击到输入框，已取消输出")
                        return False
                    elif insertion.failure == "copied_to_clipboard":
                        self._show_copied(insertion.copied_text or sentence)
                        return True
        except Exception as e:
            print(f"[ai] 写作失败: {e}")
            return False

        if pending.strip():
            tail = _finish_write_tail(pending)
            insertion = self._env.insert_generated_text(tail)
            if insertion.ok:
                total += insertion.inserted_text
            elif insertion.failure == "no_focused_input":
                self._show("未点击到输入框，已取消输出")
                return False
            elif insertion.failure == "copied_to_clipboard":
                self._show_copied(insertion.copied_text or tail)
                return True

        return False

    def _do_delete(self, instruction: str, selected: str) -> None:
        whole_window_delete = _is_whole_window_delete_instruction(instruction)
        if whole_window_delete:
            lookup = self._env.operation_window_for_instruction()
            if not lookup.ok:
                if not self._env.delete_all_text_by_shortcut():
                    self._show("没有可删除的内容")
                return
            window = lookup.window
        else:
            window = self._operation_window_or_prompt("删除", "删除")
            if window is None:
                return
            if window.source != "explicit_selection":
                self._show("请先选中你想删除的内容")
                return
        plan = (
            ReplacementPlan(target_text=window.text, replacement_text="")
            if whole_window_delete
            else self._removal_plan(window.text, instruction)
        )
        with self._io():
            result = self._env.apply_replacement_plan(
                window,
                plan,
            )
        if result.ok:
            return
        elif result.failure in {"target_not_found", "ambiguous_target", "low_confidence"}:
            self._show("没有找到明确可删除的内容")
        else:
            self._show("没有可删除的内容")

    def _operation_window_or_prompt(self, action: str, noun: str):
        lookup = self._env.operation_window_for_instruction()
        if not lookup.ok:
            self._show(f"没有可{noun}的内容")
            return None
        return lookup.window

    def _do_undo(self) -> None:
        policy = self._env.shortcut_policy_for_invocation("撤销")
        if policy.found and policy.allowed and self._env.send_shortcut("撤销"):
            return
        self._show("没有找到快捷键：撤销")

    def _do_memo_save(self, key: str, value: str, selected: str) -> None:
        self._handle_memory_result(self._memory.save(key, value, selected), selected)

    def _do_memo_recall(self, key: str, selected: str) -> bool:
        return self._handle_memory_result(self._memory.recall(key), selected)

    def _do_memo_list(self, selected: str) -> bool:
        return self._handle_memory_result(self._memory.list_all(), selected)

    def _do_memo_delete(self, key: str) -> None:
        self._handle_memory_result(self._memory.delete(key))

    def _show_copied(self, text: str) -> None:
        preview = str(text or "").replace("\n", " ")[:60]
        suffix = "…" if len(str(text or "")) > 60 else ""
        self._show(f"已复制：{preview}{suffix}")


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
    compact = "".join(str(text or "").split()).strip("。.!！？?，,；;：:")
    return compact in {
        "删除",
        "删掉",
        "删了",
        "清除",
        "清空",
        "全部删除",
        "删除全部",
        "删掉全部",
        "全部删掉",
        "清空全部",
        "全部清空",
        "都删掉",
        "都删除",
    }


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
