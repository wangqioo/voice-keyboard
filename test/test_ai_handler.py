import unittest
from unittest.mock import patch

from agent.correction_memory import CorrectionTextSnapshot
from agent.focused_text_capture import FocusedTextWindow
from agent.input_environment import (
    OperationWindow,
    ReplacementPlan,
    TextInsertionResult,
    TextTarget,
    TyperInputEnvironment,
)
from agent.text_buffer import TextBuffer
from agent.text_io import CaretTextWindow
from agent.text_io import ShortcutCatalogEntry
from agent.text_io import ShortcutPolicyDecision
from agent.text_io import TyperTextIO


class FakeTextIO:
    def __init__(self, selected: str = ""):
        self.selected = selected
        self.calls = []
        self.shortcuts_value = ["保存"]
        self.can_insert = True
        self.confirm_paste = False
        self.caret_window = None
        self.focused_snapshot = CorrectionTextSnapshot("", source="unsupported")
        self.screen_snapshot = CorrectionTextSnapshot("", source="unsupported")
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

    def get_full_focused_text_snapshot(self):
        self.calls.append(("get_full_focused_text_snapshot",))
        return self.focused_snapshot

    def get_screen_text_snapshot(self, expected_text: str = ""):
        self.calls.append(("get_screen_text_snapshot", expected_text))
        return self.screen_snapshot

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
    def test_typer_text_io_uses_focused_text_capture_adapter(self):
        class FakeFocusedTextCapture:
            def caret_window(self):
                return FocusedTextWindow("光标附近", source="ax")

            def full_focused_snapshot(self):
                return CorrectionTextSnapshot("全文", source="focused_ax")

            def screen_snapshot(self, expected_text: str = ""):
                return CorrectionTextSnapshot(expected_text, source="screen_ocr")

        text_io = TyperTextIO(focused_text_capture=FakeFocusedTextCapture())

        self.assertEqual(
            text_io.get_caret_text_window(),
            CaretTextWindow("光标附近", source="ax"),
        )
        self.assertEqual(
            text_io.get_full_focused_text_snapshot(),
            CorrectionTextSnapshot("全文", source="focused_ax"),
        )
        self.assertEqual(
            text_io.get_screen_text_snapshot("期望文本"),
            CorrectionTextSnapshot("期望文本", source="screen_ocr"),
        )

    def test_input_environment_can_use_text_io_adapter_without_patching_typer(self):
        buf = TextBuffer()
        text_io = FakeTextIO(selected="old")
        env = TyperInputEnvironment(buf, text_io=text_io)

        env.insert_generated_text("new")

        self.assertEqual(
            text_io.calls,
            [("get_selection",), ("jump_to_end",), ("type_text", "new")],
        )
        self.assertEqual(buf.current_segment, "new")

    def test_shortcut_invocation_uses_text_io_adapter(self):
        env = TyperInputEnvironment(TextBuffer(), text_io=FakeTextIO())

        self.assertEqual(env.shortcuts(), ("保存",))
        self.assertTrue(env.send_shortcut("保存"))
        self.assertEqual(env.active_application(), "Codex (com.openai.codex)")

    def test_delete_all_text_by_shortcut_selects_all_and_deletes(self):
        buf = TextBuffer()
        buf.push("old")
        text_io = FakeTextIO()
        text_io.shortcuts_value = ["全选", "删除"]
        env = TyperInputEnvironment(buf, text_io=text_io)

        self.assertTrue(env.delete_all_text_by_shortcut())

        self.assertIn(("send_shortcut", "全选"), text_io.calls)
        self.assertIn(("send_shortcut", "删除"), text_io.calls)
        self.assertEqual(buf.current_segment, "")

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

    def test_insert_dictation_uses_same_output_path(self):
        buf = TextBuffer()
        text_io = FakeTextIO()
        env = TyperInputEnvironment(buf, text_io=text_io)

        env.insert_dictation("dictated")

        self.assertIn(("type_text", "dictated"), text_io.calls)
        self.assertEqual(buf.current_segment, "dictated")

    def test_insert_dictation_ignores_focus_probe_and_types_directly(self):
        buf = TextBuffer()
        text_io = FakeTextIO()
        text_io.can_insert = False
        text_io.confirm_paste = True
        env = TyperInputEnvironment(buf, text_io=text_io)

        result = env.insert_output_text("dictated")

        self.assertEqual(
            text_io.calls,
            [
                ("type_text", "dictated"),
            ],
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.inserted_text, "dictated")
        self.assertEqual(buf.current_segment, "dictated")

    def test_insert_generated_text_reports_cancelled_paste(self):
        text_io = FakeTextIO()
        text_io.can_insert = False
        text_io.confirm_paste = False
        env = TyperInputEnvironment(TextBuffer(), text_io=text_io)

        result = env.insert_generated_text("generated")

        self.assertTrue(result.ok)
        self.assertEqual(result.inserted_text, "generated")
        self.assertEqual(text_io.calls, [
            ("get_selection",),
            ("type_text", "generated"),
        ])

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

    def test_operation_window_uses_caret_window_without_explicit_selection_or_tracked_output(self):
        text_io = FakeTextIO()
        text_io.caret_window = CaretTextWindow("current sentence.", "caret_sentence")
        env = TyperInputEnvironment(TextBuffer(), text_io=text_io)

        result = env.operation_window_for_instruction()

        self.assertTrue(result.ok)
        self.assertIsNotNone(result.window)
        self.assertEqual(result.window.text, "current sentence.")
        self.assertEqual(result.window.source, "caret")

    def test_correction_learning_uses_full_focused_text_before_caret_slice(self):
        text_io = FakeTextIO()
        text_io.focused_snapshot = CorrectionTextSnapshot(
            text="文净，文净，文净",
            source="AXValue",
            detail="confidence=high",
        )
        text_io.caret_window = CaretTextWindow("文净，文净，文", "caret_sentence")
        env = TyperInputEnvironment(TextBuffer(), text_io=text_io)

        self.assertEqual(env.current_text_for_correction_learning(), "文净，文净，文净")
        self.assertNotIn(("get_caret_text_window",), text_io.calls)

    def test_correction_learning_uses_caret_window_when_focused_snapshot_is_empty(self):
        text_io = FakeTextIO()
        text_io.focused_snapshot = CorrectionTextSnapshot("", source="unsupported")
        text_io.caret_window = CaretTextWindow("文净，文净，文净", "caret_sentence")
        env = TyperInputEnvironment(TextBuffer(), text_io=text_io)

        snapshot = env.current_text_snapshot_for_correction_learning()

        self.assertEqual(snapshot.text, "文净，文净，文净")
        self.assertEqual(snapshot.source, "caret:caret_sentence")

    def test_correction_learning_exposes_screen_ocr_snapshot(self):
        text_io = FakeTextIO()
        text_io.screen_snapshot = CorrectionTextSnapshot(
            text="李立夫，李立夫，李立夫",
            source="ocr_window",
            detail="confidence=medium",
        )
        env = TyperInputEnvironment(TextBuffer(), text_io=text_io)

        snapshot = env.screen_text_snapshot_for_correction_learning(
            "李丽夫，李丽夫，李丽夫"
        )

        self.assertEqual(snapshot.text, "李立夫，李立夫，李立夫")
        self.assertEqual(snapshot.source, "ocr_window")
        self.assertIn("confidence=medium", snapshot.detail)
        self.assertEqual(
            text_io.calls[-1],
            ("get_screen_text_snapshot", "李丽夫，李丽夫，李丽夫"),
        )

    def test_operation_window_prefers_last_output_over_caret_window(self):
        buf = TextBuffer()
        buf.push("last dictated output")
        text_io = FakeTextIO()
        text_io.caret_window = CaretTextWindow("current sentence.", "caret_sentence")
        env = TyperInputEnvironment(buf, text_io=text_io)

        result = env.operation_window_for_instruction()

        self.assertTrue(result.ok)
        self.assertIsNotNone(result.window)
        self.assertEqual(result.window.text, "last dictated output")
        self.assertEqual(result.window.source, "tracked_segment")
        self.assertEqual(text_io.calls, [("get_selection",)])

    def test_operation_window_can_prefer_caret_window_for_explicit_whole_scope(self):
        buf = TextBuffer()
        buf.push("last dictated output")
        text_io = FakeTextIO()
        text_io.caret_window = CaretTextWindow("whole input text", "caret_sentence")
        env = TyperInputEnvironment(buf, text_io=text_io)

        result = env.operation_window_for_instruction(prefer_tracked_segment=False)

        self.assertTrue(result.ok)
        self.assertIsNotNone(result.window)
        self.assertEqual(result.window.text, "whole input text")
        self.assertEqual(result.window.source, "caret")
        self.assertEqual(
            text_io.calls,
            [("get_selection",), ("get_caret_text_window",)],
        )

    def test_text_revision_window_names_intent_for_tracked_segment(self):
        buf = TextBuffer()
        buf.push("last dictated output")
        text_io = FakeTextIO()
        text_io.caret_window = CaretTextWindow("whole input text", "caret_sentence")
        env = TyperInputEnvironment(buf, text_io=text_io)

        result = env.operation_window_for_text_revision()

        self.assertTrue(result.ok)
        self.assertIsNotNone(result.window)
        self.assertEqual(result.window.text, "last dictated output")
        self.assertEqual(result.window.source, "tracked_segment")

    def test_whole_scope_window_names_intent_for_caret_text(self):
        buf = TextBuffer()
        buf.push("last dictated output")
        text_io = FakeTextIO()
        text_io.caret_window = CaretTextWindow("whole input text", "caret_sentence")
        env = TyperInputEnvironment(buf, text_io=text_io)

        result = env.operation_window_for_whole_scope()

        self.assertTrue(result.ok)
        self.assertIsNotNone(result.window)
        self.assertEqual(result.window.text, "whole input text")
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

    def test_operation_window_falls_back_to_tracked_segment(self):
        buf = TextBuffer()
        buf.push("safe tracked")
        text_io = FakeTextIO()
        text_io.caret_window = None
        env = TyperInputEnvironment(buf, text_io=text_io)

        result = env.operation_window_for_instruction()

        self.assertTrue(result.ok)
        self.assertIsNotNone(result.window)
        self.assertEqual(result.window.text, "safe tracked")
        self.assertEqual(result.window.source, "tracked_segment")
        self.assertEqual(
            text_io.calls,
            [("get_selection",)],
        )

    def test_operation_window_tracks_last_output_not_joined_segment(self):
        buf = TextBuffer()
        buf.push("first output")
        buf.push("second output")
        text_io = FakeTextIO()
        text_io.caret_window = None
        env = TyperInputEnvironment(buf, text_io=text_io)

        result = env.operation_window_for_instruction()

        self.assertTrue(result.ok)
        self.assertIsNotNone(result.window)
        self.assertEqual(result.window.text, "second output")
        self.assertEqual(result.window.target.tracked_segment, "second output")
        self.assertEqual(result.window.source, "tracked_segment")

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
        env = TyperInputEnvironment(TextBuffer())
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
        env = TyperInputEnvironment(TextBuffer())
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

    def test_replacement_plan_retypes_tracked_segment_when_controlled_replace_fails(self):
        text_io = FakeTextIO()
        text_io.can_replace_text_window = False
        buf = TextBuffer()
        buf.push("hello world")
        env = TyperInputEnvironment(buf, text_io=text_io)
        target = TextTarget(tracked_segment="hello world")
        window = OperationWindow("hello world", target, "tracked_segment")

        result = env.apply_replacement_plan(
            window,
            ReplacementPlan(target_text="world", replacement_text="earth"),
        )

        self.assertTrue(result.ok)
        self.assertEqual(
            text_io.calls,
            [
                ("replace_text_window", "hello world", "hello earth"),
                ("erase_last", "hello world"),
                ("type_text", "hello earth"),
            ],
        )
        self.assertEqual(buf.current_segment, "hello earth")


if __name__ == "__main__":
    unittest.main()
