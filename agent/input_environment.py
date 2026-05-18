"""Input Environment seam for text-side effects.

This module keeps Instruction Mode focused on Voice Text Operations instead of
platform typing details and Tracked Segment bookkeeping.
"""

from dataclasses import dataclass
from typing import Literal

from agent.operation_history import OperationEffect
from agent.text_buffer import TextBuffer
from agent.text_io import ShortcutPolicyDecision, TextIO, TyperTextIO


@dataclass(frozen=True)
class TextTarget:
    selected: str = ""
    tracked_segment: str = ""
    tracked_segment_safe: bool = True


@dataclass(frozen=True)
class OperationWindow:
    text: str
    target: TextTarget
    source: Literal["explicit_selection", "tracked_segment", "caret"]


@dataclass(frozen=True)
class ReplacementPlan:
    target_text: str
    replacement_text: str = ""
    confidence: Literal["high", "medium", "low"] = "high"


TargetFailure = Literal[
    "unsafe_tracked_segment",
    "no_tracked_segment",
    "no_focused_input",
    "target_not_found",
    "ambiguous_target",
    "low_confidence",
]


@dataclass(frozen=True)
class TargetChangeResult:
    changed_text: str = ""
    replacement_text: str = ""
    failure: TargetFailure | None = None

    @property
    def ok(self) -> bool:
        return self.failure is None

    @classmethod
    def changed(cls, text: str, replacement: str = "") -> "TargetChangeResult":
        return cls(changed_text=text, replacement_text=replacement)

    @classmethod
    def failed(cls, failure: TargetFailure) -> "TargetChangeResult":
        return cls(failure=failure)


@dataclass(frozen=True)
class TargetLookupResult:
    target: TextTarget | None = None
    original_text: str = ""
    failure: TargetFailure | None = None

    @property
    def ok(self) -> bool:
        return self.failure is None

    @classmethod
    def found(cls, target: TextTarget, original_text: str) -> "TargetLookupResult":
        return cls(target=target, original_text=original_text)

    @classmethod
    def failed(cls, failure: TargetFailure) -> "TargetLookupResult":
        return cls(failure=failure)


@dataclass(frozen=True)
class OperationWindowLookupResult:
    window: OperationWindow | None = None
    failure: TargetFailure | None = None

    @property
    def ok(self) -> bool:
        return self.failure is None

    @classmethod
    def found(cls, window: OperationWindow) -> "OperationWindowLookupResult":
        return cls(window=window)

    @classmethod
    def failed(cls, failure: TargetFailure) -> "OperationWindowLookupResult":
        return cls(failure=failure)


@dataclass(frozen=True)
class ReversalResult:
    applied: bool = True
    failure: str | None = None


@dataclass(frozen=True)
class TextInsertionResult:
    inserted_text: str = ""
    failure: str | None = None
    copied_text: str = ""

    @property
    def ok(self) -> bool:
        return self.failure is None


class UnsafeTrackedSegment(RuntimeError):
    pass


class NoTrackedSegment(RuntimeError):
    pass


class TyperInputEnvironment:
    def __init__(
        self,
        buf: TextBuffer,
        require_selection_for_instruction: bool = True,
        text_io: TextIO | None = None,
    ):
        self._buf = buf
        self._require_selection_for_instruction = require_selection_for_instruction
        self._text_io = text_io or TyperTextIO()

    @property
    def buffer(self) -> TextBuffer:
        return self._buf

    def target_for_instruction(self) -> TextTarget:
        selected = self._text_io.get_selection()
        return TextTarget(
            selected=selected,
            tracked_segment=self._buf.current_segment,
            tracked_segment_safe=not self._buf.cursor_uncertain,
        )

    def target_for_revision(self) -> TargetLookupResult:
        return self._target_from_operation_window()

    def target_for_removal(self) -> TargetLookupResult:
        return self._target_from_operation_window()

    def operation_window_for_instruction(self) -> OperationWindowLookupResult:
        return self._operation_window_for_text_change()

    def insert_text(self, text: str) -> None:
        self._text_io.type_text(text)
        self._buf.push(text)

    def insert_dictation(self, text: str) -> None:
        result = self.insert_output_text(text)
        if not result.ok:
            raise RuntimeError(result.failure or "insert_failed")

    def insert_output_text(self, text: str) -> TextInsertionResult:
        if not text:
            return TextInsertionResult(inserted_text="")
        if self._text_io.can_insert_text():
            self.insert_text(text)
            return TextInsertionResult(inserted_text=text)
        if not self._text_io.confirm_paste_text(text):
            return TextInsertionResult(failure="no_focused_input")
        return TextInsertionResult(failure="copied_to_clipboard", copied_text=text)

    def insert_text_after_selection(self, text: str, selected: str = "") -> None:
        if selected:
            self._text_io.jump_to_end()
        self.insert_text(text)

    def insert_generated_text(self, text: str) -> TextInsertionResult:
        target = self.target_for_instruction()
        if target.selected:
            self._text_io.jump_to_end()
        return self.insert_output_text(text)

    def replace_selection(self, original: str, replacement: str) -> None:
        self._text_io.replace_selection(replacement, original=original)
        self._sync_selected_replacement(original, replacement)

    def delete_selection(self, original: str) -> None:
        self._text_io.delete_selection(original=original)
        self._sync_selected_replacement(original, "")

    def replace_instruction_target(
        self,
        target: TextTarget,
        replacement: str,
    ) -> TargetChangeResult:
        if target.selected:
            self.replace_selection(target.selected, replacement)
            return TargetChangeResult.changed(target.selected, replacement)
        if not target.tracked_segment_safe:
            return TargetChangeResult.failed("unsafe_tracked_segment")
        if self._require_selection_for_instruction:
            return TargetChangeResult.failed("no_tracked_segment")
        if not target.tracked_segment:
            return TargetChangeResult.failed("no_tracked_segment")
        try:
            self.replace_tracked_segment(target.tracked_segment, replacement)
        except UnsafeTrackedSegment:
            return TargetChangeResult.failed("unsafe_tracked_segment")
        except NoTrackedSegment:
            return TargetChangeResult.failed("no_tracked_segment")
        return TargetChangeResult.changed(target.tracked_segment, replacement)

    def delete_instruction_target(self, target: TextTarget) -> TargetChangeResult:
        if target.selected:
            self.delete_selection(target.selected)
            return TargetChangeResult.changed(target.selected)
        if not target.tracked_segment_safe:
            return TargetChangeResult.failed("unsafe_tracked_segment")
        if self._require_selection_for_instruction:
            return TargetChangeResult.failed("no_tracked_segment")
        if not target.tracked_segment:
            return TargetChangeResult.failed("no_tracked_segment")
        try:
            self.delete_tracked_segment(target.tracked_segment)
        except UnsafeTrackedSegment:
            return TargetChangeResult.failed("unsafe_tracked_segment")
        except NoTrackedSegment:
            return TargetChangeResult.failed("no_tracked_segment")
        return TargetChangeResult.changed(target.tracked_segment)

    def apply_replacement_plan(
        self,
        window: OperationWindow,
        plan: ReplacementPlan,
    ) -> TargetChangeResult:
        if plan.confidence == "low":
            return TargetChangeResult.failed("low_confidence")
        target_text = plan.target_text
        if not target_text:
            return TargetChangeResult.failed("target_not_found")
        occurrences = window.text.count(target_text)
        if occurrences == 0:
            return TargetChangeResult.failed("target_not_found")
        if occurrences > 1:
            return TargetChangeResult.failed("ambiguous_target")

        if window.source == "explicit_selection":
            replacement = window.text.replace(
                target_text,
                plan.replacement_text,
                1,
            )
            self.replace_selection(window.text, replacement)
            return TargetChangeResult.changed(window.text, replacement)

        if window.source == "caret":
            replacement = window.text.replace(
                target_text,
                plan.replacement_text,
                1,
            )
            if not self._text_io.replace_text_window(window.text, replacement):
                return TargetChangeResult.failed("target_not_found")
            self._sync_selected_replacement(window.text, replacement)
            return TargetChangeResult.changed(window.text, replacement)

        if not window.target.tracked_segment_safe:
            return TargetChangeResult.failed("unsafe_tracked_segment")
        if self._require_selection_for_instruction:
            return TargetChangeResult.failed("no_tracked_segment")
        if target_text != window.text:
            return TargetChangeResult.failed("target_not_found")
        self.replace_tracked_segment(target_text, plan.replacement_text)
        return TargetChangeResult.changed(target_text, plan.replacement_text)

    def replace_tracked_segment(self, original: str, replacement: str) -> None:
        self._ensure_tracked_segment(original)
        self._text_io.erase_last(original)
        self._text_io.type_text(replacement)
        self._buf.replace_segment(replacement)

    def delete_tracked_segment(self, original: str) -> None:
        self._ensure_tracked_segment(original)
        self._text_io.erase_last(original)
        self._buf.replace_segment("")

    def erase_text(self, text: str) -> None:
        self._text_io.erase_last(text)

    def trim_tracked_segment_end(self, count: int) -> None:
        self._buf.trim_end(count)

    def mark_tracked_segment_unsafe(self) -> None:
        self._buf.cursor_uncertain = True

    def start_new_tracked_segment(self) -> None:
        self._buf.new_segment()

    def apply_operation_reversal(self, effect: OperationEffect) -> ReversalResult:
        if effect.kind == "replace":
            if effect.new_text:
                self.erase_text(effect.new_text)
            if effect.old_text:
                self._text_io.type_text(effect.old_text)
            self._sync_reversed_replacement(effect.old_text, effect.new_text)
        elif effect.kind == "insert":
            if effect.new_text:
                self.erase_text(effect.new_text)
                self._buf.trim_end(len(effect.new_text))
        elif effect.kind == "delete":
            if effect.old_text:
                self.insert_text(effect.old_text)
            self._buf.replace_segment(effect.old_text)
        return ReversalResult()

    def shortcuts(self) -> tuple[str, ...]:
        return tuple(self._text_io.list_shortcuts())

    def shortcut_catalog(self) -> tuple:
        return tuple(self._text_io.shortcut_catalog())

    def shortcut_policy_for_invocation(
        self,
        name: str,
        *,
        in_atomic_stack: bool = False,
    ) -> ShortcutPolicyDecision:
        return self._text_io.shortcut_policy_for_invocation(
            name,
            in_atomic_stack=in_atomic_stack,
        )

    def send_shortcut(self, name: str) -> bool:
        decision = self.shortcut_policy_for_invocation(name)
        if not decision.allowed:
            return False
        return self._text_io.send_shortcut(name)

    def active_application(self) -> str:
        return self._text_io.current_application_label()

    def _ensure_tracked_segment(self, original: str) -> None:
        if self._buf.cursor_uncertain:
            raise UnsafeTrackedSegment("Tracked Segment is unsafe")
        if not original:
            raise NoTrackedSegment("No Tracked Segment")

    def _target_from_operation_window(self) -> TargetLookupResult:
        result = self._operation_window_for_text_change()
        if not result.ok:
            return TargetLookupResult.failed(result.failure or "no_tracked_segment")
        if result.window is None:
            return TargetLookupResult.failed("no_tracked_segment")
        return TargetLookupResult.found(result.window.target, result.window.text)

    def _operation_window_for_text_change(self) -> OperationWindowLookupResult:
        target = self.target_for_instruction()
        if target.selected:
            return OperationWindowLookupResult.found(
                OperationWindow(
                    text=target.selected,
                    target=target,
                    source="explicit_selection",
                )
            )
        caret_window = self._text_io.get_caret_text_window()
        if caret_window is not None and caret_window.text:
            return OperationWindowLookupResult.found(
                OperationWindow(
                    text=caret_window.text,
                    target=target,
                    source="caret",
                )
            )
        if self._require_selection_for_instruction:
            return OperationWindowLookupResult.failed("no_tracked_segment")
        if not target.tracked_segment_safe:
            return OperationWindowLookupResult.failed("unsafe_tracked_segment")
        if not target.tracked_segment:
            return OperationWindowLookupResult.failed("no_tracked_segment")
        return OperationWindowLookupResult.found(
            OperationWindow(
                text=target.tracked_segment,
                target=target,
                source="tracked_segment",
            )
        )

    def _sync_selected_replacement(self, selected: str, replacement: str) -> None:
        segment = self._buf.current_segment
        if segment == selected:
            self._buf.replace_segment(replacement)
        elif selected and segment.endswith(selected):
            self._buf.trim_end(len(selected))
            if replacement:
                self._buf.push(replacement)
        else:
            self._buf.clear()
            if replacement:
                self._buf.push(replacement)

    def _sync_reversed_replacement(self, old_text: str, new_text: str) -> None:
        segment = self._buf.current_segment
        if new_text and segment.endswith(new_text):
            self._buf.trim_end(len(new_text))
            if old_text:
                self._buf.push(old_text)
        else:
            self._buf.replace_segment(old_text)
