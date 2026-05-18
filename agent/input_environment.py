"""Input Environment seam for text-side effects.

This module keeps Instruction Mode focused on Voice Text Operations instead of
platform typing details and Tracked Segment bookkeeping.
"""

from dataclasses import dataclass
from typing import Literal

from agent.operation_history import OperationEffect
from agent.text_buffer import TextBuffer
from agent import typer


@dataclass(frozen=True)
class TextTarget:
    selected: str = ""
    tracked_segment: str = ""
    tracked_segment_safe: bool = True


TargetFailure = Literal["unsafe_tracked_segment", "no_tracked_segment"]


@dataclass(frozen=True)
class TargetChangeResult:
    changed_text: str = ""
    failure: TargetFailure | None = None

    @property
    def ok(self) -> bool:
        return self.failure is None

    @classmethod
    def changed(cls, text: str) -> "TargetChangeResult":
        return cls(changed_text=text)

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
class ReversalResult:
    applied: bool = True
    failure: str | None = None


@dataclass(frozen=True)
class TextInsertionResult:
    inserted_text: str = ""
    failure: str | None = None

    @property
    def ok(self) -> bool:
        return self.failure is None


class UnsafeTrackedSegment(RuntimeError):
    pass


class NoTrackedSegment(RuntimeError):
    pass


class TyperInputEnvironment:
    def __init__(self, buf: TextBuffer, require_selection_for_instruction: bool = True):
        self._buf = buf
        self._require_selection_for_instruction = require_selection_for_instruction

    @property
    def buffer(self) -> TextBuffer:
        return self._buf

    def target_for_instruction(self) -> TextTarget:
        selected = typer.get_selection()
        return TextTarget(
            selected=selected,
            tracked_segment=self._buf.current_segment,
            tracked_segment_safe=not self._buf.cursor_uncertain,
        )

    def target_for_revision(self) -> TargetLookupResult:
        return self._target_for_text_change()

    def target_for_removal(self) -> TargetLookupResult:
        return self._target_for_text_change()

    def insert_text(self, text: str) -> None:
        typer.type_text(text)
        self._buf.push(text)

    def insert_dictation(self, text: str) -> None:
        self.insert_text(text)

    def insert_text_after_selection(self, text: str, selected: str = "") -> None:
        if selected:
            typer.jump_to_end()
        self.insert_text(text)

    def insert_generated_text(self, text: str) -> TextInsertionResult:
        target = self.target_for_instruction()
        if target.selected:
            typer.jump_to_end()
        self.insert_text(text)
        return TextInsertionResult(inserted_text=text)

    def replace_selection(self, original: str, replacement: str) -> None:
        typer.replace_selection(replacement)
        self._sync_selected_replacement(original, replacement)

    def delete_selection(self, original: str) -> None:
        typer.delete_selection()
        self._sync_selected_replacement(original, "")

    def replace_instruction_target(
        self,
        target: TextTarget,
        replacement: str,
    ) -> TargetChangeResult:
        if target.selected:
            self.replace_selection(target.selected, replacement)
            return TargetChangeResult.changed(target.selected)
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
        return TargetChangeResult.changed(target.tracked_segment)

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

    def replace_tracked_segment(self, original: str, replacement: str) -> None:
        self._ensure_tracked_segment(original)
        typer.erase_last(original)
        typer.type_text(replacement)
        self._buf.replace_segment(replacement)

    def delete_tracked_segment(self, original: str) -> None:
        self._ensure_tracked_segment(original)
        typer.erase_last(original)
        self._buf.replace_segment("")

    def erase_text(self, text: str) -> None:
        typer.erase_last(text)

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
                typer.type_text(effect.old_text)
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
        return tuple(typer.list_shortcuts())

    def send_shortcut(self, name: str) -> bool:
        return typer.send_shortcut(name)

    def _ensure_tracked_segment(self, original: str) -> None:
        if self._buf.cursor_uncertain:
            raise UnsafeTrackedSegment("Tracked Segment is unsafe")
        if not original:
            raise NoTrackedSegment("No Tracked Segment")

    def _target_for_text_change(self) -> TargetLookupResult:
        target = self.target_for_instruction()
        if target.selected:
            return TargetLookupResult.found(target, target.selected)
        if self._require_selection_for_instruction:
            return TargetLookupResult.failed("no_tracked_segment")
        if not target.tracked_segment_safe:
            return TargetLookupResult.failed("unsafe_tracked_segment")
        if not target.tracked_segment:
            return TargetLookupResult.failed("no_tracked_segment")
        return TargetLookupResult.found(target, target.tracked_segment)

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
