# Input Environment Seam

This design expands ADR-0002 into an implementation plan. The goal is to make Instruction Mode depend on one deep module for Input Environment behavior instead of knowing about `typer`, `TextBuffer`, keyboard monitoring, mouse monitoring, clipboard details, and platform-specific cursor behavior.

## Current Friction

The original friction was that Instruction Mode crossed several shallow interfaces:

- `agent.ai_handler` called `get_selection`, `replace_selection`, `delete_selection`, `jump_to_end`, `erase_last`, `type_text`, and `list_shortcuts` directly.
- `agent.ai_handler` read `TextBuffer.current_segment` directly.
- keyboard and mouse monitors mutated `TextBuffer` safety state from the side.
- Tests patched individual functions in `agent.ai_handler` instead of exercising a domain interface.

The result was poor locality. The current implementation concentrates text-side effects in `TyperInputEnvironment`; `TextBuffer` remains an implementation detail inside that adapter.

The current design pressure is simpler: behave like a lightweight voice keyboard. An Explicit Selection takes precedence. Without one, local partial editing may use the current Tracked Segment when the engine can still prove it owns that text. Whole-scope requests such as "translate the whole input box" may use the current safe Operation Window exposed by the Input Environment. Partial removal without an Explicit Selection still asks the user to select text.

## Target Module

Introduce an `InputEnvironment` module with one interface for Instruction Mode.

Current file:

```text
agent/input_environment.py
agent/text_io.py
agent/focused_text_capture.py
```

Suggested interface shape:

```python
@dataclass(frozen=True)
class TextTarget:
    selected: str = ""
    tracked_segment: str = ""

class InputEnvironment:
    def target_for_instruction(self) -> TextTarget: ...
    def operation_window_for_instruction(self) -> OperationWindow: ...
    def operation_window_for_text_revision(self, target: TextTarget | None = None, *, whole_scope: bool = False) -> OperationWindow: ...
    def operation_window_for_text_removal(self, *, whole_scope: bool = False) -> OperationWindow: ...
    def operation_window_for_whole_scope(self) -> OperationWindow: ...
    def apply_replacement_plan(self, plan: ReplacementPlan) -> TargetChangeResult: ...
    def insert_text(self, text: str) -> None: ...
    def insert_text_after_selection(self, text: str) -> None: ...
    def insert_generated_text(self, text: str) -> TextInsertionResult: ...
    def replace_selection(self, original: str, replacement: str) -> None: ...
    def delete_selection(self, original: str) -> None: ...
    def current_text_snapshot_for_correction_learning(self) -> CorrectionTextSnapshot: ...
    def screen_text_snapshot_for_correction_learning(self, expected_text: str = "") -> CorrectionTextSnapshot: ...
```

The first implementation is intentionally small and wraps today's `typer` and `TextBuffer` behavior. The design pressure is that callers should express domain intent, not platform IO steps.

Instruction Mode now uses the intent-specific lookup methods for Text Revision,
Text Removal, and whole-scope requests. `operation_window_for_instruction`
remains as a compatibility entry point, but new code should prefer the
intent-specific methods because they make the tracked-segment vs caret-window
choice explicit.

## Adapter

The first adapter should wrap today's implementation:

```text
TyperInputEnvironment
```

It owns:

- `TextBuffer`
- a platform text IO adapter that calls into `agent.typer`
- a focused-text capture adapter for caret, focused-text, and screen snapshots
- synchronizing selected replacements back into recent engine text
- deciding the current safe Operation Window for replacement-style operations
- verifying that a Replacement Plan only changes text inside the current Operation Window
- moving to the end before insertion when an Explicit Selection exists
- exposing focused-text and screen-text snapshots for Dictation Correction Memory without making Dictation Mode call platform IO directly

`agent/text_io.py` still owns typing, shortcuts, and replacement side effects.
`agent/focused_text_capture.py` owns read-only focused text capture and wraps the
Accessibility/OCR functions currently implemented in `agent.typer`. This keeps
future capture improvements out of Instruction Mode and Dictation Correction
Memory.

## Migration Slices

1. Done: add `agent/input_environment.py` with `TextTarget` and `TyperInputEnvironment`.
2. Done: move selected replacement synchronization out of `AIHandler` and into the adapter.
3. Done: change `AIHandler` to use `input_environment` for text-side effects while keeping the existing `buf` constructor path compatible.
4. Done: keep `TextBuffer` internally at first to reduce blast radius.
5. Done: update focused tests to assert through the Input Environment interface.
6. Done: add atomic target-change operations for Text Revision and Text Removal so Instruction Mode no longer owns the Explicit Selection branch rules.
7. Removed: local undo history; spoken undo is now the current application undo shortcut.
8. Done: add generated-text insertion so Text Generation and Memo Operation insertion no longer pass Explicit Selection state through Instruction Mode.
9. Done: route Dictation Mode insertion through the same adapter.
10. Done: put platform text IO calls behind `agent/text_io.py` so Input Environment tests can use the seam without patching `agent.typer`.
11. Done: introduce Operation Window and Replacement Plan types.
12. Done: route selected Text Revision, selected Text Removal, and whole-scope requests through locally verified Replacement Plans.
13. Done: add macOS caret-local Operation Window discovery and controlled AX replacement behind the TextIO adapter.
14. Done: add correction-learning text snapshots so Dictation Correction Memory can observe focused text through the same Input Environment/TextIO seams.
15. Done: split focused text capture from the typing adapter so read-only capture can evolve independently from text insertion.
16. Done: add intent-specific Operation Window lookup methods for Text Revision, Text Removal, and whole-scope operations.
17. Later: remove the compatibility `buf` constructor path from runtime helpers once downstream callers have migrated.

## Test Surface

Tests should cover the interface:

- Explicit Selection replacement updates the Tracked Segment when the selection is the suffix.
- Explicit Selection deletion updates the Tracked Segment when the selection is the suffix.
- Text Generation and Memo Operation insertion move out of an Explicit Selection before inserting.
- Text Generation and Memo Operation insertion can be requested without passing Explicit Selection state through Instruction Mode.
- An Operation Window can be larger than the Operation Target.
- Without an Explicit Selection, local partial replacement may use the current Tracked Segment; local partial removal asks for selection.
- Without an Explicit Selection, whole-scope replacement/removal may use the current safe Operation Window.
- Replacement Plan application refuses changes whose target text is absent, duplicated ambiguously, or outside the current Operation Window.
- Correction-learning snapshots prefer full focused text, then caret-local text, then the current Tracked Segment, with screen OCR exposed separately as a lower-confidence fallback.

## Non-Goals

- Do not move platform-specific typing behavior above the TextIO adapter.
- Do not let provider behavior bypass local Replacement Plan verification.
- Do not let Dictation Correction Memory call platform typing or OCR modules directly; keep those reads behind Input Environment/TextIO adapters.
- Do not reintroduce local undo history; undo is the current application shortcut.
- Do not redesign Instruction Mode classification yet.
- Do not introduce multiple adapters until there is a second real runtime that needs one.
- Do not let a paid provider directly decide platform mutation. It proposes a Replacement Plan; the Input Environment verifies and applies it.
