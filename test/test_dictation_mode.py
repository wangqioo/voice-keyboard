import unittest
from unittest.mock import MagicMock

from agent.correction_memory import CorrectionMemory
from agent.dictation_mode import (
    DictationMode,
    clean_generated_text,
    clean_polished_text,
    looks_like_short_fragment,
    normalize_dictation_punctuation,
    strip_terminal_punctuation_for_short_fragment,
)
from agent.input_environment import TextInsertionResult


class FakePerformance:
    def __init__(self):
        self.started = []
        self.finished = []

    def span(self, name: str, **fields):
        self.started.append((name, fields))
        return name

    def finish(self, span, **fields):
        self.finished.append((span, fields))


class DictationModeModuleTests(unittest.TestCase):
    def make_module(self, stt_text="hello"):
        stt = MagicMock(spec=["transcribe"])
        stt.transcribe.return_value = stt_text
        env = MagicMock()
        status = MagicMock()
        history = MagicMock()
        env.insert_output_text.return_value = TextInsertionResult(inserted_text=stt_text)
        module = DictationMode(
            stt,
            env,
            status_window=status,
            history=history,
        )
        return module, stt, env, status, history

    def test_normal_dictation_inserts_text_and_records_history(self):
        module, stt, env, status, history = self.make_module("  ### hello  ")

        module.handle_utterance(b"pcm")

        stt.transcribe.assert_called_once_with(b"pcm")
        env.insert_output_text.assert_called_once_with("hello")
        history.append.assert_called_once_with("dictate", "hello", "ok", "")
        status.show_typing_message.assert_not_called()
        status.set_state.assert_called_once_with("idle")

    def test_normal_dictation_reports_performance_spans(self):
        module, _stt, _env, _status, _history = self.make_module("hello")
        perf = FakePerformance()
        module.performance = perf

        module.handle_utterance(b"\0" * 32000)

        self.assertEqual(
            [name for name, _fields in perf.started],
            [
                "dictation.total",
                "dictation.observe_previous",
                "dictation.stt",
                "dictation.correction",
                "dictation.typing",
            ],
        )
        finished = dict(perf.finished)
        self.assertEqual(finished["dictation.stt"]["audio_seconds"], "1.00")
        self.assertEqual(finished["dictation.typing"]["chars"], 5)
        self.assertEqual(finished["dictation.total"]["status"], "ok")

    def test_normal_dictation_outputs_without_status_preview(self):
        stt = MagicMock(spec=["transcribe"])
        stt.transcribe.return_value = "hello"
        calls = []
        status = MagicMock()
        env = MagicMock()
        status.show_typing_message.side_effect = (
            lambda text, seconds: calls.append(("preview", text, seconds))
        )

        def insert(text):
            calls.append(("insert", text))
            return TextInsertionResult(inserted_text=text)

        env.insert_output_text.side_effect = insert
        module = DictationMode(stt, env, status_window=status)

        module.handle_utterance(b"pcm")

        self.assertEqual(calls, [
            ("insert", "hello"),
        ])
        status.show_typing_message.assert_not_called()

    def test_normal_dictation_clears_status_when_preview_is_unavailable(self):
        module, _stt, env, status, history = self.make_module("hello")
        del status.show_typing_message

        module.handle_utterance(b"pcm")

        env.insert_output_text.assert_called_once_with("hello")
        history.append.assert_called_once_with("dictate", "hello", "ok", "")
        status.set_state.assert_called_once_with("idle")

    def test_normal_dictation_strips_added_punctuation_from_short_fragment(self):
        module, _stt, env, _status, history = self.make_module("时间复杂度。")

        module.handle_utterance(b"pcm")

        env.insert_output_text.assert_called_once_with("时间复杂度")
        history.append.assert_called_once_with("dictate", "时间复杂度", "ok", "")

    def test_normal_dictation_converts_clear_spoken_punctuation(self):
        module, _stt, env, _status, history = self.make_module(
            "例如苹果香蕉感叹号"
        )

        module.handle_utterance(b"pcm")

        env.insert_output_text.assert_called_once_with("例如：苹果香蕉！")
        history.append.assert_called_once_with("dictate", "例如：苹果香蕉！", "ok", "")

    def test_normal_dictation_inserts_recognized_text_when_dictionary_is_empty(self):
        module, _stt, env, _status, history = self.make_module("白光雨最喜欢说的话")

        module.handle_utterance(b"pcm")

        env.insert_output_text.assert_called_once_with("白光雨最喜欢说的话")
        history.append.assert_called_once_with("dictate", "白光雨最喜欢说的话", "ok", "")
        _status.show_typing_message.assert_not_called()

    def test_normal_dictation_applies_confirmed_correction_memory(self):
        module, _stt, env, _status, history = self.make_module("白光雨最喜欢说的话")
        memory = MagicMock(spec=CorrectionMemory)
        memory.apply.return_value = "白光宇最喜欢说的话"
        module.correction_memory = memory

        module.handle_utterance(b"pcm")

        memory.apply.assert_called_once_with("白光雨最喜欢说的话")
        env.insert_output_text.assert_called_once_with("白光宇最喜欢说的话")
        history.append.assert_called_once_with("dictate", "白光宇最喜欢说的话", "ok", "")

    def test_observes_previous_manual_correction_before_next_dictation(self):
        module, _stt, env, status, _history = self.make_module("下一句")
        tracker = MagicMock()
        tracker.observe_current_text.return_value = MagicMock(
            confirmed=[
                MagicMock(wrong="王琦", correct="王齐"),
            ],
        )
        module.correction_tracker = tracker

        module.handle_utterance(b"pcm")

        tracker.observe_current_text.assert_called_once_with()
        status.show_message.assert_called_once_with("已将「王齐」加入词典", 5.0)
        tracker.remember_inserted.assert_called_once_with("下一句")

    def test_schedules_background_correction_observation_after_insert(self):
        module, _stt, env, _status, _history = self.make_module("王琦王琦小王琦")
        tracker = MagicMock()
        tracker.observe_current_text.return_value = MagicMock(confirmed=[])
        scheduler = MagicMock()
        module.correction_tracker = tracker
        module.correction_scheduler = scheduler

        module.handle_utterance(b"pcm")

        tracker.remember_inserted.assert_called_once_with("王琦王琦小王琦")
        scheduler.schedule.assert_called_once_with()

    def test_polish_stt_uses_dedicated_transcription_method_when_available(self):
        stt = MagicMock(spec=["transcribe", "transcribe_polished"])
        stt.transcribe.return_value = "base"
        stt.transcribe_polished.return_value = "polished by stt"
        env = MagicMock()
        history = MagicMock()
        module = DictationMode(stt, env, history=history)

        module.handle_utterance(b"pcm", polish=True)

        stt.transcribe_polished.assert_called_once_with(b"pcm")
        stt.transcribe.assert_not_called()
        env.insert_output_text.assert_called_once_with("polished by stt")
        history.append.assert_called_once_with("polish", "polished by stt", "ok", "")

    def test_polish_mode_can_apply_text_polisher_after_stt(self):
        module, _stt, env, status, history = self.make_module("嗯 hello")
        editor = MagicMock()
        editor.chat.return_value = "润色结果：Hello."
        module.text_polisher = editor

        module.handle_utterance(b"pcm", polish=True)

        env.insert_output_text.assert_called_once_with("Hello.")
        self.assertEqual(status.set_state.call_args_list[0].args, ("polishing",))
        status.show_typing_message.assert_not_called()
        history.append.assert_called_once_with("polish", "Hello.", "ok", "")

    def test_polish_failure_keeps_original_text(self):
        module, _stt, env, _status, history = self.make_module("original")
        editor = MagicMock()
        editor.chat.side_effect = RuntimeError("no llm")
        module.text_polisher = editor

        module.handle_utterance(b"pcm", polish=True)

        env.insert_output_text.assert_called_once_with("original")
        history.append.assert_called_once_with("polish", "original", "ok", "")

    def test_stt_error_records_error_without_insert(self):
        module, stt, env, status, history = self.make_module()
        stt.transcribe.side_effect = RuntimeError("offline")

        module.handle_utterance(b"pcm")

        env.insert_output_text.assert_not_called()
        history.append.assert_called_once_with("dictate", "", "error", "STT: offline")
        status.set_state.assert_called_once_with("error_stt")

    def test_empty_stt_records_empty_without_insert(self):
        module, _stt, env, status, history = self.make_module("  ###  ")

        module.handle_utterance(b"pcm")

        env.insert_output_text.assert_not_called()
        history.append.assert_called_once_with("dictate", "", "empty", "")
        status.set_state.assert_called_once_with("empty_stt")

    def test_typing_error_records_original_text_without_idle_status(self):
        module, _stt, env, status, history = self.make_module("hello")
        env.insert_output_text.side_effect = RuntimeError("blocked")

        module.handle_utterance(b"pcm")

        history.append.assert_called_once_with("dictate", "hello", "error", "typing: blocked")
        status.set_state.assert_called_once_with("error_typing")

    def test_copied_no_focus_output_is_not_recorded_as_typing_error(self):
        module, _stt, env, status, history = self.make_module("hello")
        env.insert_output_text.return_value = MagicMock(
            ok=False,
            failure="copied_to_clipboard",
            copied_text="hello",
        )

        module.handle_utterance(b"pcm")

        history.append.assert_called_once_with("dictate", "hello", "copied", "no_focused_input")
        status.show_message.assert_called_once_with("已复制：hello", 5.0)
        status.set_state.assert_not_called()

    def test_status_flags_preserve_segment_behavior(self):
        module, _stt, env, status, _history = self.make_module("hello")

        module.handle_utterance(b"pcm", clear_status=False, progress_status=False)

        env.insert_output_text.assert_called_once_with("hello")
        status.set_state.assert_not_called()

    def test_cleanup_helpers_match_common_model_markup(self):
        self.assertEqual(clean_generated_text("  ### 你好世界  "), "你好世界")
        self.assertEqual(clean_polished_text("```text\n润色结果：你好世界\n```"), "你好世界")

    def test_normalize_dictation_punctuation_handles_common_spoken_symbols(self):
        self.assertEqual(normalize_dictation_punctuation("例如苹果香蕉"), "例如：苹果香蕉")
        self.assertEqual(normalize_dictation_punctuation("等等省略号"), "等等……")
        self.assertEqual(normalize_dictation_punctuation("等等破折号继续"), "等等——继续")
        self.assertEqual(normalize_dictation_punctuation("例如。"), "例如：")
        self.assertEqual(normalize_dictation_punctuation("例如：。"), "例如：")

    def test_short_word_or_idiom_polish_does_not_keep_added_sentence_punctuation(self):
        self.assertEqual(clean_polished_text("时间复杂度。"), "时间复杂度")
        self.assertEqual(clean_polished_text("一石二鸟。"), "一石二鸟")

    def test_complete_short_sentence_keeps_sentence_punctuation(self):
        self.assertEqual(clean_polished_text("这是测试。"), "这是测试。")
        self.assertEqual(clean_polished_text("你在吗？"), "你在吗？")
        self.assertEqual(clean_polished_text("我们走吧。"), "我们走吧。")
        self.assertEqual(clean_polished_text("Hello."), "Hello.")

    def test_longer_sentence_and_internal_punctuation_keep_sentence_punctuation(self):
        self.assertEqual(
            strip_terminal_punctuation_for_short_fragment("今天上海天气不错。"),
            "今天上海天气不错。",
        )
        self.assertEqual(
            strip_terminal_punctuation_for_short_fragment("上海，天气不错。"),
            "上海，天气不错。",
        )

    def test_short_fragment_classifier_is_conservative(self):
        self.assertTrue(looks_like_short_fragment("一石二鸟"))
        self.assertTrue(looks_like_short_fragment("时间复杂度"))
        self.assertFalse(looks_like_short_fragment("这是测试"))
        self.assertFalse(looks_like_short_fragment("上海，天气不错"))


if __name__ == "__main__":
    unittest.main()
