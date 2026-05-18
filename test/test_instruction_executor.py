import unittest
from unittest.mock import MagicMock, patch

from agent.input_environment import (
    OperationWindowLookupResult,
    ReplacementPlan,
    ReversalResult,
    ShortcutPolicyDecision,
    TextInsertionResult,
    TyperInputEnvironment,
)
from agent.input_environment import TargetLookupResult, TextTarget
from agent.instruction_executor import InstructionModeExecutor, _forced_punctuation_break
from agent.operation_history import OperationEffect, OperationHistory
from agent.text_buffer import TextBuffer
from agent.voice_text_operation import VoiceTextOperation


class InstructionModeExecutorTests(unittest.TestCase):
    def test_shortcut_invocation_requires_local_catalog_policy(self):
        env = MagicMock()
        env.shortcut_policy_for_invocation.return_value = ShortcutPolicyDecision.missing(
            "provider invented"
        )
        messages = []
        executor = InstructionModeExecutor(
            MagicMock(),
            env,
            OperationHistory(),
            show=messages.append,
        )

        executor.execute(VoiceTextOperation("shortcut", name="provider invented"), "", "")

        env.shortcut_policy_for_invocation.assert_called_once_with("provider invented")
        env.send_shortcut.assert_not_called()
        self.assertEqual(messages, ["没有找到快捷键：provider invented"])

    def test_single_high_risk_shortcut_invocation_is_marked_but_not_blocked(self):
        env = MagicMock()
        env.shortcut_policy_for_invocation.return_value = ShortcutPolicyDecision(
            name="发送",
            found=True,
            allowed=True,
            risk="high",
            source="application",
            application="Codex (com.openai.codex)",
        )
        env.send_shortcut.return_value = True
        messages = []
        executor = InstructionModeExecutor(
            MagicMock(),
            env,
            OperationHistory(),
            show=messages.append,
        )

        executor.execute(VoiceTextOperation("shortcut", name="发送"), "", "")

        env.shortcut_policy_for_invocation.assert_called_once_with("发送")
        env.send_shortcut.assert_called_once_with("发送")
        self.assertEqual(messages, [])

    def test_selected_edit_records_effect_and_syncs_buffer_suffix(self):
        buf = TextBuffer()
        buf.push("hello world")
        llm = MagicMock()
        llm.edit.return_value = "earth"
        history = OperationHistory()
        executor = InstructionModeExecutor(llm, TyperInputEnvironment(buf), history)

        with (
            patch("agent.typer.get_selection", return_value="world"),
            patch("agent.typer.replace_selection") as replace_selection,
        ):
            executor.execute(VoiceTextOperation("edit"), "改成 earth", "world")

        replace_selection.assert_called_once_with("earth", original="world")
        self.assertEqual(buf.current_segment, "hello earth")
        self.assertEqual(history.snapshot(), (OperationEffect.replace("world", "earth"),))

    def test_selected_edit_uses_structured_replacement_plan_for_subtarget(self):
        buf = TextBuffer()
        buf.push("hello world")
        llm = MagicMock()
        llm.plan_replacement.return_value = ReplacementPlan(
            target_text="world",
            replacement_text="earth",
        )
        history = OperationHistory()
        executor = InstructionModeExecutor(llm, TyperInputEnvironment(buf), history)

        with (
            patch("agent.typer.get_selection", return_value="hello world"),
            patch("agent.typer.replace_selection") as replace_selection,
        ):
            executor.execute(VoiceTextOperation("edit"), "把 world 改成 earth", "")

        llm.plan_replacement.assert_called_once_with("hello world", "把 world 改成 earth")
        llm.edit.assert_not_called()
        replace_selection.assert_called_once_with("hello earth", original="hello world")
        self.assertEqual(buf.current_segment, "hello earth")
        self.assertEqual(
            history.snapshot(),
            (OperationEffect.replace("hello world", "hello earth"),),
        )

    def test_ambiguous_replacement_plan_does_not_mutate_text(self):
        buf = TextBuffer()
        buf.push("hello hello")
        llm = MagicMock()
        llm.plan_replacement.return_value = ReplacementPlan(
            target_text="hello",
            replacement_text="hi",
        )
        history = OperationHistory()
        messages = []
        executor = InstructionModeExecutor(
            llm,
            TyperInputEnvironment(buf),
            history,
            show=messages.append,
        )

        with (
            patch("agent.typer.get_selection", return_value="hello hello"),
            patch("agent.typer.replace_selection") as replace_selection,
        ):
            executor.execute(VoiceTextOperation("edit"), "改一个 hello", "")

        replace_selection.assert_not_called()
        self.assertEqual(history.snapshot(), ())
        self.assertEqual(messages, ["没有找到明确可替换的内容"])

    def test_selected_delete_uses_controlled_delete_and_records_effect(self):
        buf = TextBuffer()
        buf.push("hello world")
        history = OperationHistory()
        executor = InstructionModeExecutor(MagicMock(), TyperInputEnvironment(buf), history)

        with (
            patch("agent.typer.get_selection", return_value="world"),
            patch("agent.typer.replace_selection") as replace_selection,
        ):
            executor.execute(VoiceTextOperation("delete"), "删掉", "world")

        replace_selection.assert_called_once_with("", original="world")
        self.assertEqual(buf.current_segment, "hello ")
        self.assertEqual(history.snapshot(), (OperationEffect.delete("world"),))

    def test_delete_uses_structured_replacement_plan_for_subtarget(self):
        buf = TextBuffer()
        buf.push("hello world")
        llm = MagicMock()
        llm.plan_replacement.return_value = ReplacementPlan(
            target_text="world",
            replacement_text="ignored",
        )
        history = OperationHistory()
        executor = InstructionModeExecutor(llm, TyperInputEnvironment(buf), history)

        with (
            patch("agent.typer.get_selection", return_value="hello world"),
            patch("agent.typer.replace_selection") as replace_selection,
        ):
            executor.execute(VoiceTextOperation("delete"), "删掉 world", "")

        llm.plan_replacement.assert_called_once_with("hello world", "删掉 world")
        replace_selection.assert_called_once_with("hello ", original="hello world")
        self.assertEqual(buf.current_segment, "hello ")
        self.assertEqual(
            history.snapshot(),
            (OperationEffect.replace("hello world", "hello "),),
        )

    def test_delete_with_ambiguous_replacement_plan_does_not_mutate_text(self):
        buf = TextBuffer()
        buf.push("hello hello")
        llm = MagicMock()
        llm.plan_replacement.return_value = ReplacementPlan(
            target_text="hello",
            replacement_text="",
        )
        history = OperationHistory()
        messages = []
        executor = InstructionModeExecutor(
            llm,
            TyperInputEnvironment(buf),
            history,
            show=messages.append,
        )

        with (
            patch("agent.typer.get_selection", return_value="hello hello"),
            patch("agent.typer.replace_selection") as replace_selection,
        ):
            executor.execute(VoiceTextOperation("delete"), "删掉一个 hello", "")

        replace_selection.assert_not_called()
        self.assertEqual(history.snapshot(), ())
        self.assertEqual(messages, ["没有找到明确可删除的内容"])

    def test_undo_reverses_latest_insert_effect(self):
        history = OperationHistory()
        history.push(OperationEffect.insert("generated"))
        env = MagicMock()
        env.apply_operation_reversal.return_value = ReversalResult()
        executor = InstructionModeExecutor(MagicMock(), env, history)

        executor.execute(VoiceTextOperation("undo"), "撤回", "")

        env.apply_operation_reversal.assert_called_once_with(OperationEffect.insert("generated"))
        self.assertEqual(history.snapshot(), ())

    def test_memo_recall_inserts_memory_after_selection(self):
        buf = TextBuffer()
        history = OperationHistory()
        memos = MagicMock()
        memos.get.return_value = "me@example.com"
        executor = InstructionModeExecutor(
            MagicMock(),
            TyperInputEnvironment(buf),
            history,
            memo_store=memos,
        )

        with (
            patch("agent.typer.get_selection", return_value="old"),
            patch("agent.typer.has_focused_text_input", return_value=True),
            patch("agent.typer.jump_to_end") as jump_to_end,
            patch("agent.typer.type_text") as type_text,
        ):
            executor.execute(VoiceTextOperation("memo_recall", key="邮箱"), "我的邮箱", "")

        memos.get.assert_called_once_with("邮箱")
        jump_to_end.assert_called_once_with()
        type_text.assert_called_once_with("me@example.com")
        self.assertEqual(buf.current_segment, "me@example.com")
        self.assertEqual(history.snapshot(), (OperationEffect.insert("me@example.com"),))

    def test_write_uses_generated_text_insertion_seam(self):
        llm = MagicMock()
        llm.chat_stream.return_value = ["第一句。", "第二句。"]
        env = MagicMock()
        env.insert_generated_text.side_effect = (
            lambda text: TextInsertionResult(inserted_text=text)
        )
        history = OperationHistory()
        executor = InstructionModeExecutor(llm, env, history)

        executor.execute(VoiceTextOperation("write"), "写两句", "")

        self.assertEqual(env.insert_generated_text.call_count, 2)
        env.insert_generated_text.assert_any_call("第一句。")
        env.insert_generated_text.assert_any_call("第二句。")
        self.assertEqual(history.snapshot(), (OperationEffect.insert("第一句。第二句。"),))

    def test_write_adds_local_punctuation_when_provider_stream_has_none(self):
        llm = MagicMock()
        llm.chat_stream.return_value = [
            "北京天安门位于中国北京市中心是天安门广场的北端是中华人民共和国的象征也是世界上最大的城市广场之一"
        ]
        env = MagicMock()
        env.insert_generated_text.side_effect = (
            lambda text: TextInsertionResult(inserted_text=text)
        )
        history = OperationHistory()
        executor = InstructionModeExecutor(llm, env, history)

        executor.execute(VoiceTextOperation("write"), "介绍北京天安门", "")

        inserted = "".join(call.args[0] for call in env.insert_generated_text.call_args_list)
        self.assertIn("，", inserted)
        self.assertIn("。", inserted)
        self.assertEqual(history.snapshot(), (OperationEffect.insert(inserted),))

    def test_write_normalizes_common_spoken_punctuation_names(self):
        llm = MagicMock()
        llm.chat_stream.return_value = ["常见水果例如苹果香蕉感叹号"]
        env = MagicMock()
        env.insert_generated_text.side_effect = (
            lambda text: TextInsertionResult(inserted_text=text)
        )
        history = OperationHistory()
        executor = InstructionModeExecutor(llm, env, history)

        executor.execute(VoiceTextOperation("write"), "写一个例句", "")

        inserted = "".join(call.args[0] for call in env.insert_generated_text.call_args_list)
        self.assertEqual(inserted, "常见水果例如：苹果香蕉！")
        self.assertEqual(history.snapshot(), (OperationEffect.insert(inserted),))

    def test_forced_punctuation_break_waits_for_reasonable_length(self):
        self.assertIsNone(_forced_punctuation_break("北京天安门"))
        forced = _forced_punctuation_break(
            "北京天安门位于中国北京市中心是天安门广场的北端是中华人民共和国的象征也是重要地标"
        )
        self.assertIsNotNone(forced)
        emit, rest = forced
        self.assertTrue(emit.endswith(("，", "。")))
        self.assertTrue(emit)
        self.assertIsInstance(rest, str)

    def test_write_cancelled_paste_does_not_record_insert_effect(self):
        llm = MagicMock()
        llm.chat_stream.return_value = ["第一句。"]
        env = MagicMock()
        env.insert_generated_text.return_value = TextInsertionResult(failure="no_focused_input")
        history = OperationHistory()
        messages = []
        executor = InstructionModeExecutor(llm, env, history, show=messages.append)

        executor.execute(VoiceTextOperation("write"), "写一句", "")

        self.assertEqual(history.snapshot(), ())
        self.assertEqual(messages, ["未点击到输入框，已取消输出"])

    def test_write_copied_to_clipboard_shows_status_without_recording_insert_effect(self):
        llm = MagicMock()
        llm.chat_stream.return_value = ["第一句。"]
        env = MagicMock()
        env.insert_generated_text.return_value = TextInsertionResult(
            failure="copied_to_clipboard",
            copied_text="第一句。",
        )
        history = OperationHistory()
        messages = []
        executor = InstructionModeExecutor(llm, env, history, show=messages.append)

        executor.execute(VoiceTextOperation("write"), "写一句", "")

        self.assertEqual(history.snapshot(), ())
        self.assertEqual(messages, ["已复制：第一句。"])

    def test_unsafe_tracked_segment_edit_does_not_call_llm(self):
        llm = MagicMock()
        env = MagicMock()
        env.operation_window_for_instruction.return_value = OperationWindowLookupResult.failed(
            "unsafe_tracked_segment"
        )
        messages = []
        executor = InstructionModeExecutor(
            llm,
            env,
            OperationHistory(),
            show=messages.append,
        )

        executor.execute(VoiceTextOperation("edit"), "润色一下", "")

        llm.edit.assert_not_called()
        self.assertEqual(messages, ["请先选中你想修改的内容"])


if __name__ == "__main__":
    unittest.main()
