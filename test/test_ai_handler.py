import unittest
from unittest.mock import patch

from agent.input_environment import (
    OperationWindow,
    ReplacementPlan,
    TextInsertionResult,
    TextTarget,
    TyperInputEnvironment,
    UnsafeTrackedSegment,
)
from agent.operation_history import OperationEffect
from agent.text_buffer import TextBuffer
from agent.text_io import CaretTextWindow
from agent.text_io import ShortcutCatalogEntry
from agent.text_io import ShortcutPolicyDecision


class FakeTextIO:
    def __init__(self, selected: str = ""):
        self.selected = selected
        self.calls = []
        self.shortcuts_value = ["保存"]
        self.can_insert = True
        self.confirm_paste = False
        self.caret_window = None
        self.can_replace_text_window = True

    def can_insert_text(self) -> bool:
        self.calls.append(("can_insert_text",))
        return self.can_insert

    def confirm_paste_text(self, text: str) -> bool:
        self.calls.append(("confirm_paste_text", text))
        return self.confirm_paste

    def paste_text(self, text: str) -> None:
        self.calls.append(("paste_text", text))

    def get_selection(self) -> str:
        self.calls.append(("get_selection",))
        return self.selected

    def get_caret_text_window(self):
        self.calls.append(("get_caret_text_window",))
        return self.caret_window

    def type_text(self, text: str) -> None:
        self.calls.append(("type_text", text))

    def jump_to_end(self) -> None:
        self.calls.append(("jump_to_end",))

    def replace_selection(self, text: str, original: str = "") -> None:
        self.calls.append(("replace_selection", text, original))

    def replace_text_window(self, original: str, replacement: str) -> bool:
        self.calls.append(("replace_text_window", original, replacement))
        return self.can_replace_text_window

    def delete_selection(self, original: str = "") -> None:
        self.calls.append(("delete_selection", original))

    def erase_last(self, text: str) -> None:
        self.calls.append(("erase_last", text))

    def list_shortcuts(self) -> list[str]:
        self.calls.append(("list_shortcuts",))
        return self.shortcuts_value

    def shortcut_catalog(self) -> list[ShortcutCatalogEntry]:
        self.calls.append(("shortcut_catalog",))
        return [ShortcutCatalogEntry(name=name, source="global") for name in self.shortcuts_value]

    def shortcut_policy_for_invocation(
        self,
        name: str,
        *,
        in_atomic_stack: bool = False,
    ) -> ShortcutPolicyDecision:
        self.calls.append(("shortcut_policy_for_invocation", name, in_atomic_stack))
        for entry in self.shortcut_catalog():
            if entry.name != name:
                continue
            if in_atomic_stack and entry.risk == "high":
                return ShortcutPolicyDecision(
                    name=name,
                    found=True,
                    allowed=False,
                    risk=entry.risk,
                    source=entry.source,
                    application=entry.application,
                    reason="high_risk_requires_confirmation",
                )
            return ShortcutPolicyDecision(
                name=name,
                found=True,
                allowed=True,
                risk=entry.risk,
                source=entry.source,
                application=entry.application,
            )
        return ShortcutPolicyDecision.missing(name)

    def send_shortcut(self, name: str) -> bool:
        self.calls.append(("send_shortcut", name))
        return name in self.shortcuts_value

    def current_application_label(self) -> str:
        self.calls.append(("current_application_label",))
        return "Codex (com.openai.codex)"


class InputEnvironmentTests(unittest.TestCase):
    def test_input_environment_can_use_text_io_adapter_without_patching_typer(self):
        buf = TextBuffer()
        text_io = FakeTextIO(selected="old")
        env = TyperInputEnvironment(buf, text_io=text_io)

        env.insert_generated_text("new")

        self.assertEqual(
            text_io.calls,
            [("get_selection",), ("jump_to_end",), ("can_insert_text",), ("type_text", "new")],
        )
        self.assertEqual(buf.current_segment, "new")

    def test_shortcut_invocation_uses_text_io_adapter(self):
        env = TyperInputEnvironment(TextBuffer(), text_io=FakeTextIO())

        self.assertEqual(env.shortcuts(), ("保存",))
        self.assertTrue(env.send_shortcut("保存"))
        self.assertEqual(env.active_application(), "Codex (com.openai.codex)")

    def test_shortcut_policy_blocks_shortcuts_missing_from_local_catalog(self):
        text_io = FakeTextIO()
        text_io.shortcuts_value = ["保存"]
        env = TyperInputEnvironment(TextBuffer(), text_io=text_io)

        decision = env.shortcut_policy_for_invocation("provider invented")
        executed = env.send_shortcut("provider invented")

        self.assertEqual(
            decision,
            ShortcutPolicyDecision.missing("provider invented"),
        )
        self.assertFalse(executed)
        self.assertEqual(text_io.calls[0], (
            "shortcut_policy_for_invocation",
            "provider invented",
            False,
        ))
        self.assertNotIn(("send_shortcut", "provider invented"), text_io.calls)

    def test_shortcut_policy_blocks_high_risk_shortcut_inside_stack(self):
        class HighRiskTextIO(FakeTextIO):
            def shortcut_catalog(self) -> list[ShortcutCatalogEntry]:
                self.calls.append(("shortcut_catalog",))
                return [
                    ShortcutCatalogEntry(
                        name="发送",
                        source="application",
                        risk="high",
                        application="Codex (com.openai.codex)",
                    )
                ]

        env = TyperInputEnvironment(TextBuffer(), text_io=HighRiskTextIO())

        decision = env.shortcut_policy_for_invocation("发送", in_atomic_stack=True)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "high_risk_requires_confirmation")
        self.assertEqual(decision.risk, "high")

    def test_insert_after_selection_moves_to_end_once(self):
        buf = TextBuffer()
        env = TyperInputEnvironment(buf)

        with (
            patch("agent.typer.jump_to_end") as jump_to_end,
            patch("agent.typer.type_text") as type_text,
        ):
            env.insert_text_after_selection("new text", selected="old")

        jump_to_end.assert_called_once_with()
        type_text.assert_called_once_with("new text")
        self.assertEqual(buf.current_segment, "new text")

    def test_insert_dictation_uses_same_tracked_segment_path(self):
        buf = TextBuffer()
        text_io = FakeTextIO()
        env = TyperInputEnvironment(buf, text_io=text_io)

        env.insert_dictation("dictated")

        self.assertIn(("type_text", "dictated"), text_io.calls)
        self.assertEqual(buf.current_segment, "dictated")

    def test_insert_dictation_copies_to_clipboard_when_no_input_is_focused(self):
        buf = TextBuffer()
        text_io = FakeTextIO()
        text_io.can_insert = False
        text_io.confirm_paste = True
        env = TyperInputEnvironment(buf, text_io=text_io)

        result = env.insert_output_text("dictated")

        self.assertEqual(
            text_io.calls,
            [
                ("can_insert_text",),
                ("confirm_paste_text", "dictated"),
            ],
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.failure, "copied_to_clipboard")
        self.assertEqual(result.copied_text, "dictated")
        self.assertEqual(buf.current_segment, "")

    def test_insert_generated_text_reports_cancelled_paste(self):
        text_io = FakeTextIO()
        text_io.can_insert = False
        text_io.confirm_paste = False
        env = TyperInputEnvironment(TextBuffer(), text_io=text_io)

        result = env.insert_generated_text("generated")

        self.assertFalse(result.ok)
        self.assertEqual(result.failure, "no_focused_input")
        self.assertEqual(text_io.calls, [
            ("get_selection",),
            ("can_insert_text",),
            ("confirm_paste_text", "generated"),
        ])

    def test_tracking_events_are_exposed_through_environment(self):
        buf = TextBuffer()
        buf.push("hello")
        env = TyperInputEnvironment(buf)

        env.trim_tracked_segment_end(2)
        self.assertEqual(buf.current_segment, "hel")

        env.mark_tracked_segment_unsafe()
        self.assertTrue(buf.cursor_uncertain)

        env.start_new_tracked_segment()
        self.assertEqual(buf.current_segment, "")

    def test_insert_generated_text_moves_out_of_current_explicit_selection(self):
        buf = TextBuffer()
        env = TyperInputEnvironment(buf)

        with (
            patch("agent.typer.get_selection", return_value="old"),
            patch("agent.typer.has_focused_text_input", return_value=True),
            patch("agent.typer.jump_to_end") as jump_to_end,
            patch("agent.typer.type_text") as type_text,
        ):
            result = env.insert_generated_text("new text")

        jump_to_end.assert_called_once_with()
        type_text.assert_called_once_with("new text")
        self.assertEqual(result, TextInsertionResult(inserted_text="new text"))
        self.assertEqual(buf.current_segment, "new text")

    def test_insert_generated_text_without_explicit_selection_does_not_jump(self):
        buf = TextBuffer()
        env = TyperInputEnvironment(buf)

        with (
            patch("agent.typer.get_selection", return_value=""),
            patch("agent.typer.has_focused_text_input", return_value=True),
            patch("agent.typer.jump_to_end") as jump_to_end,
            patch("agent.typer.type_text") as type_text,
        ):
            result = env.insert_generated_text("new text")

        jump_to_end.assert_not_called()
        type_text.assert_called_once_with("new text")
        self.assertEqual(result.inserted_text, "new text")

    def test_replace_tracked_segment_refuses_unsafe_segment(self):
        buf = TextBuffer()
        buf.push("hello")
        buf.cursor_uncertain = True
        env = TyperInputEnvironment(buf)

        with (
            patch("agent.typer.erase_last") as erase_last,
            patch("agent.typer.type_text") as type_text,
        ):
            with self.assertRaises(UnsafeTrackedSegment):
                env.replace_tracked_segment("hello", "hi")

        erase_last.assert_not_called()
        type_text.assert_not_called()

    def test_replace_instruction_target_uses_explicit_selection(self):
        buf = TextBuffer()
        buf.push("hello world")
        env = TyperInputEnvironment(buf)

        with patch("agent.typer.replace_selection") as replace_selection:
            result = env.replace_instruction_target(
                TextTarget(selected="world", tracked_segment="hello world"),
                "earth",
            )

        replace_selection.assert_called_once_with("earth", original="world")
        self.assertTrue(result.ok)
        self.assertEqual(result.changed_text, "world")
        self.assertEqual(result.replacement_text, "earth")
        self.assertEqual(buf.current_segment, "hello earth")

    def test_delete_instruction_target_refuses_unsafe_tracked_segment(self):
        buf = TextBuffer()
        buf.push("hello")
        env = TyperInputEnvironment(buf)

        with patch("agent.typer.erase_last") as erase_last:
            result = env.delete_instruction_target(
                TextTarget(tracked_segment="hello", tracked_segment_safe=False),
            )

        erase_last.assert_not_called()
        self.assertFalse(result.ok)
        self.assertEqual(result.failure, "unsafe_tracked_segment")

    def test_target_for_revision_prefers_explicit_selection(self):
        buf = TextBuffer()
        buf.push("hello world")
        env = TyperInputEnvironment(buf)

        with patch("agent.typer.get_selection", return_value="world"):
            result = env.target_for_revision()

        self.assertTrue(result.ok)
        self.assertEqual(result.original_text, "world")

    def test_target_for_revision_reports_unsafe_tracked_segment(self):
        buf = TextBuffer()
        buf.push("hello")
        buf.cursor_uncertain = True
        env = TyperInputEnvironment(buf)

        with patch("agent.typer.get_selection", return_value=""):
            result = env.target_for_revision()

        self.assertFalse(result.ok)
        self.assertEqual(result.failure, "no_tracked_segment")

    def test_target_for_revision_uses_current_window_without_explicit_selection(self):
        buf = TextBuffer()
        buf.push("hello")
        text_io = FakeTextIO()
        text_io.caret_window = CaretTextWindow("current sentence.", "caret_sentence")
        env = TyperInputEnvironment(buf, text_io=text_io)

        result = env.target_for_revision()

        self.assertTrue(result.ok)
        self.assertEqual(result.original_text, "current sentence.")

    def test_target_for_revision_can_allow_tracked_segment_when_configured(self):
        buf = TextBuffer()
        buf.push("hello")
        env = TyperInputEnvironment(buf, require_selection_for_instruction=False)

        with patch("agent.typer.get_selection", return_value=""):
            result = env.target_for_revision()

        self.assertTrue(result.ok)
        self.assertEqual(result.original_text, "hello")

    def test_operation_window_prefers_explicit_selection(self):
        buf = TextBuffer()
        buf.push("hello world")
        env = TyperInputEnvironment(buf)

        with patch("agent.typer.get_selection", return_value="world"):
            result = env.operation_window_for_instruction()

        self.assertTrue(result.ok)
        self.assertIsNotNone(result.window)
        self.assertEqual(result.window.text, "world")
        self.assertEqual(result.window.source, "explicit_selection")

    def test_operation_window_uses_caret_window_without_explicit_selection(self):
        buf = TextBuffer()
        text_io = FakeTextIO()
        text_io.caret_window = CaretTextWindow("current sentence.", "caret_sentence")
        env = TyperInputEnvironment(buf, text_io=text_io)

        result = env.operation_window_for_instruction()

        self.assertTrue(result.ok)
        self.assertIsNotNone(result.window)
        self.assertEqual(result.window.text, "current sentence.")
        self.assertEqual(result.window.source, "caret")

    def test_operation_window_prefers_selection_over_caret_window(self):
        text_io = FakeTextIO(selected="selected")
        text_io.caret_window = CaretTextWindow("caret sentence.", "caret_sentence")
        env = TyperInputEnvironment(TextBuffer(), text_io=text_io)

        result = env.operation_window_for_instruction()

        self.assertTrue(result.ok)
        self.assertIsNotNone(result.window)
        self.assertEqual(result.window.text, "selected")
        self.assertEqual(result.window.source, "explicit_selection")

    def test_operation_window_falls_back_from_caret_window_to_safe_tracked_segment(self):
        buf = TextBuffer()
        buf.push("safe tracked")
        text_io = FakeTextIO()
        text_io.caret_window = None
        env = TyperInputEnvironment(
            buf,
            require_selection_for_instruction=False,
            text_io=text_io,
        )

        result = env.operation_window_for_instruction()

        self.assertTrue(result.ok)
        self.assertIsNotNone(result.window)
        self.assertEqual(result.window.text, "safe tracked")
        self.assertEqual(result.window.source, "tracked_segment")
        self.assertEqual(
            text_io.calls,
            [("get_selection",), ("get_caret_text_window",)],
        )

    def test_operation_window_prompts_when_no_selection_window_or_safe_tracked_segment(self):
        buf = TextBuffer()
        buf.push("unsafe tracked")
        buf.cursor_uncertain = True
        text_io = FakeTextIO()
        text_io.caret_window = None
        env = TyperInputEnvironment(
            buf,
            require_selection_for_instruction=False,
            text_io=text_io,
        )

        result = env.operation_window_for_instruction()

        self.assertFalse(result.ok)
        self.assertEqual(result.failure, "unsafe_tracked_segment")
        self.assertEqual(
            text_io.calls,
            [("get_selection",), ("get_caret_text_window",)],
        )

    def test_replacement_plan_can_replace_subtarget_inside_selected_window(self):
        buf = TextBuffer()
        buf.push("hello world")
        env = TyperInputEnvironment(buf)
        target = TextTarget(selected="hello world", tracked_segment="hello world")
        window = OperationWindow("hello world", target, "explicit_selection")

        with patch("agent.typer.replace_selection") as replace_selection:
            result = env.apply_replacement_plan(
                window,
                ReplacementPlan(target_text="world", replacement_text="earth"),
            )

        replace_selection.assert_called_once_with("hello earth", original="hello world")
        self.assertTrue(result.ok)
        self.assertEqual(result.changed_text, "hello world")
        self.assertEqual(result.replacement_text, "hello earth")
        self.assertEqual(buf.current_segment, "hello earth")

    def test_replacement_plan_refuses_ambiguous_target(self):
        buf = TextBuffer()
        env = TyperInputEnvironment(buf)
        target = TextTarget(selected="hello hello")
        window = OperationWindow("hello hello", target, "explicit_selection")

        with patch("agent.typer.replace_selection") as replace_selection:
            result = env.apply_replacement_plan(
                window,
                ReplacementPlan(target_text="hello", replacement_text="hi"),
            )

        replace_selection.assert_not_called()
        self.assertFalse(result.ok)
        self.assertEqual(result.failure, "ambiguous_target")

    def test_replacement_plan_refuses_low_confidence(self):
        buf = TextBuffer()
        env = TyperInputEnvironment(buf)
        target = TextTarget(selected="hello")
        window = OperationWindow("hello", target, "explicit_selection")

        with patch("agent.typer.replace_selection") as replace_selection:
            result = env.apply_replacement_plan(
                window,
                ReplacementPlan(
                    target_text="hello",
                    replacement_text="hi",
                    confidence="low",
                ),
            )

        replace_selection.assert_not_called()
        self.assertFalse(result.ok)
        self.assertEqual(result.failure, "low_confidence")

    def test_replacement_plan_uses_controlled_caret_window_replacement(self):
        text_io = FakeTextIO()
        env = TyperInputEnvironment(TextBuffer(), text_io=text_io)
        target = TextTarget()
        window = OperationWindow("hello world", target, "caret")

        result = env.apply_replacement_plan(
            window,
            ReplacementPlan(target_text="world", replacement_text="earth"),
        )

        self.assertTrue(result.ok)
        self.assertEqual(
            text_io.calls,
            [("replace_text_window", "hello world", "hello earth")],
        )

    def test_replacement_plan_refuses_caret_window_when_controlled_replace_fails(self):
        text_io = FakeTextIO()
        text_io.can_replace_text_window = False
        env = TyperInputEnvironment(TextBuffer(), text_io=text_io)
        target = TextTarget()
        window = OperationWindow("hello world", target, "caret")

        result = env.apply_replacement_plan(
            window,
            ReplacementPlan(target_text="world", replacement_text="earth"),
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.failure, "target_not_found")
        self.assertEqual(
            text_io.calls,
            [("replace_text_window", "hello world", "hello earth")],
        )

    def test_replacement_plan_refuses_tracked_segment_subtarget_until_range_io_exists(self):
        buf = TextBuffer()
        buf.push("hello world")
        env = TyperInputEnvironment(buf, require_selection_for_instruction=False)
        target = TextTarget(tracked_segment="hello world", tracked_segment_safe=True)
        window = OperationWindow("hello world", target, "tracked_segment")

        with patch("agent.typer.erase_last") as erase_last:
            result = env.apply_replacement_plan(
                window,
                ReplacementPlan(target_text="world", replacement_text="earth"),
            )

        erase_last.assert_not_called()
        self.assertFalse(result.ok)
        self.assertEqual(result.failure, "target_not_found")

    def test_apply_reversal_of_insert_erases_text_and_syncs_buffer(self):
        buf = TextBuffer()
        buf.push("generated")
        env = TyperInputEnvironment(buf)

        with patch("agent.typer.erase_last") as erase_last:
            result = env.apply_operation_reversal(OperationEffect.insert("generated"))

        erase_last.assert_called_once_with("generated")
        self.assertTrue(result.applied)
        self.assertEqual(buf.current_segment, "")

    def test_apply_reversal_of_replace_restores_old_text(self):
        buf = TextBuffer()
        buf.push("new")
        env = TyperInputEnvironment(buf)

        with (
            patch("agent.typer.erase_last") as erase_last,
            patch("agent.typer.type_text") as type_text,
        ):
            result = env.apply_operation_reversal(OperationEffect.replace("old", "new"))

        erase_last.assert_called_once_with("new")
        type_text.assert_called_once_with("old")
        self.assertTrue(result.applied)
        self.assertEqual(buf.current_segment, "old")

    def test_apply_reversal_of_selected_suffix_replace_preserves_segment_prefix(self):
        buf = TextBuffer()
        buf.push("hello earth")
        env = TyperInputEnvironment(buf)

        with (
            patch("agent.typer.erase_last") as erase_last,
            patch("agent.typer.type_text") as type_text,
        ):
            result = env.apply_operation_reversal(OperationEffect.replace("world", "earth"))

        erase_last.assert_called_once_with("earth")
        type_text.assert_called_once_with("world")
        self.assertTrue(result.applied)
        self.assertEqual(buf.current_segment, "hello world")

    def test_apply_reversal_of_delete_restores_deleted_text(self):
        buf = TextBuffer()
        env = TyperInputEnvironment(buf)

        with patch("agent.typer.type_text") as type_text:
            result = env.apply_operation_reversal(OperationEffect.delete("old"))

        type_text.assert_called_once_with("old")
        self.assertTrue(result.applied)
        self.assertEqual(buf.current_segment, "old")

if __name__ == "__main__":
    unittest.main()
