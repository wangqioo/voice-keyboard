"""Input Environment seam for text-side effects.

This module keeps Instruction Mode focused on Voice Text Operations instead of
platform typing details.
"""

from dataclasses import dataclass
from typing import Literal

from agent.text_buffer import TextBuffer
from agent.text_io import ShortcutPolicyDecision, TextIO, TyperTextIO


@dataclass(frozen=True)
class TextTarget:
    selected: str = ""
    tracked_segment: str = ""


@dataclass(frozen=True)
class OperationWindow:
    text: str
    target: TextTarget
    source: Literal["explicit_selection", "caret", "tracked_segment"]


@dataclass(frozen=True)
class ReplacementPlan:
    target_text: str
    replacement_text: str = ""
    confidence: Literal["high", "medium", "low"] = "high"


TargetFailure = Literal[
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
class TextInsertionResult:
    inserted_text: str = ""
    failure: str | None = None
    copied_text: str = ""

    @property
    def ok(self) -> bool:
        return self.failure is None


class TyperInputEnvironment:
    def __init__(
        self,
        buf: TextBuffer,
        text_io: TextIO | None = None,
    ):
        self._buf = buf
        self._text_io = text_io or TyperTextIO()

    @property
    def buffer(self) -> TextBuffer:
        return self._buf

    def target_for_instruction(self) -> TextTarget:
        selected = self._text_io.get_selection()
        return TextTarget(
            selected=selected,
            tracked_segment=self._buf.last,
        )

    def operation_window_for_instruction(
        self,
        *,
        prefer_tracked_segment: bool = True,
    ) -> OperationWindowLookupResult:
        return self._operation_window_for_text_change(
            prefer_tracked_segment=prefer_tracked_segment
        )

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
        self.insert_text(text)
        return TextInsertionResult(inserted_text=text)

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
            if replacement:
                self.replace_selection(window.text, replacement)
            else:
                self.delete_selection(window.text)
            return TargetChangeResult.changed(window.text, replacement)

        if window.source in {"caret", "tracked_segment"}:
            replacement = window.text.replace(
                target_text,
                plan.replacement_text,
                1,
            )
            if not self._text_io.replace_text_window(window.text, replacement):
                if window.source == "tracked_segment":
                    self._text_io.erase_last(window.text)
                    self._text_io.type_text(replacement)
                    self._sync_selected_replacement(window.text, replacement)
                    return TargetChangeResult.changed(window.text, replacement)
                return TargetChangeResult.failed("target_not_found")
            self._sync_selected_replacement(window.text, replacement)
            return TargetChangeResult.changed(window.text, replacement)
        return TargetChangeResult.failed("target_not_found")

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

    def delete_all_text_by_shortcut(self) -> bool:
        if not self.send_shortcut("全选"):
            return False
        if not self.send_shortcut("删除"):
            return False
        self._buf.clear()
        return True

    def active_application(self) -> str:
        return self._text_io.current_application_label()

    def _operation_window_for_text_change(
        self,
        *,
        prefer_tracked_segment: bool = True,
    ) -> OperationWindowLookupResult:
        target = self.target_for_instruction()
        if target.selected:
            return OperationWindowLookupResult.found(
                OperationWindow(
                    text=target.selected,
                    target=target,
                    source="explicit_selection",
                )
            )
        if prefer_tracked_segment and target.tracked_segment:
            return OperationWindowLookupResult.found(
                OperationWindow(
                    text=target.tracked_segment,
                    target=target,
                    source="tracked_segment",
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
        if target.tracked_segment:
            return OperationWindowLookupResult.found(
                OperationWindow(
                    text=target.tracked_segment,
                    target=target,
                    source="tracked_segment",
                )
            )
        return OperationWindowLookupResult.failed("no_tracked_segment")

    def _sync_selected_replacement(self, selected: str, replacement: str) -> None:
        last = self._buf.last
        if last == selected:
            self._buf.replace_last(replacement)
        elif selected and last.endswith(selected):
            self._buf.trim_end(len(selected))
            if replacement:
                self._buf.push(replacement)
        else:
            self._buf.clear()
            if replacement:
                self._buf.push(replacement)
