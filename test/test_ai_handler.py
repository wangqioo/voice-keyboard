import unittest
from unittest.mock import patch

from agent.input_environment import TextInsertionResult, TextTarget, TyperInputEnvironment, UnsafeTrackedSegment
from agent.operation_history import OperationEffect
from agent.text_buffer import TextBuffer


class InputEnvironmentTests(unittest.TestCase):
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
        env = TyperInputEnvironment(buf)

        with patch("agent.typer.type_text") as type_text:
            env.insert_dictation("dictated")

        type_text.assert_called_once_with("dictated")
        self.assertEqual(buf.current_segment, "dictated")

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

        replace_selection.assert_called_once_with("earth")
        self.assertTrue(result.ok)
        self.assertEqual(result.changed_text, "world")
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

    def test_target_for_revision_requires_explicit_selection_by_default(self):
        buf = TextBuffer()
        buf.push("hello")
        env = TyperInputEnvironment(buf)

        with patch("agent.typer.get_selection", return_value=""):
            result = env.target_for_revision()

        self.assertFalse(result.ok)
        self.assertEqual(result.failure, "no_tracked_segment")

    def test_target_for_revision_can_allow_tracked_segment_when_configured(self):
        buf = TextBuffer()
        buf.push("hello")
        env = TyperInputEnvironment(buf, require_selection_for_instruction=False)

        with patch("agent.typer.get_selection", return_value=""):
            result = env.target_for_revision()

        self.assertTrue(result.ok)
        self.assertEqual(result.original_text, "hello")

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
