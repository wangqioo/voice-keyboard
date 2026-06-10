import unittest
from unittest.mock import MagicMock, patch

from agent.ai_intent import IntentFallbackOptions
from agent.runtime_composition import RuntimeBackend, RuntimeOptions, build_runtime_backend, options_from_args


class RuntimeCompositionTests(unittest.TestCase):
    def test_options_from_args_keeps_runtime_flags_only(self):
        class Args:
            no_serial = True
            port = "/dev/cu.test"
            headless = True

        self.assertEqual(
            options_from_args(Args()),
            RuntimeOptions(no_serial=True, port="/dev/cu.test"),
        )

    def test_runtime_backend_stop_stops_components_and_clears_slots(self):
        calls = []

        class Component:
            def __init__(self, name):
                self.name = name

            def stop(self):
                calls.append(self.name)

        backend = RuntimeBackend()
        backend.audio = Component("audio")
        backend.reader = Component("reader")

        backend.stop()

        self.assertEqual(calls, ["audio", "reader"])
        self.assertIsNone(backend.audio)
        self.assertIsNone(backend.reader)

    def test_runtime_backend_builds_input_environment_without_cursor_monitors(self):
        with (
            patch("agent.runtime_composition.load_config", return_value={
                "stt": {"provider": "openai", "api_key": "sk"},
            }),
            patch("agent.typer.init"),
            patch("agent.runtime_composition.SpeechInterpretationProviderFactory") as factory_cls,
        ):
            factory_cls.return_value.create_provider_set.return_value = None
            backend = build_runtime_backend(RuntimeOptions(no_serial=True), MagicMock(), None, MagicMock())

        self.assertIsNotNone(backend.input_environment)

    def test_runtime_backend_records_active_hotkeys(self):
        with (
            patch("agent.runtime_composition.load_config", return_value={
                "stt": {"provider": "openai", "api_key": "sk"},
                "audio": {"ptt_key": "shift_r", "ai_key": "ctrl_r"},
            }),
            patch("agent.typer.init"),
            patch("agent.runtime_composition.SpeechInterpretationProviderFactory") as factory_cls,
        ):
            factory_cls.return_value.create_provider_set.return_value = None
            backend = build_runtime_backend(RuntimeOptions(no_serial=True), MagicMock(), None, MagicMock())

        self.assertEqual(backend.hotkeys, {"ptt_key": "shift_r", "ai_key": "ctrl_r"})

    def test_build_audio_runtime_passes_intent_fallback_options_to_ai_handler(self):
        from agent.runtime_composition import build_audio_runtime

        providers = MagicMock()
        providers.text_operation_editor = MagicMock()
        providers.instruction_stt = MagicMock()
        providers.utterance_stt = MagicMock()
        with (
            patch("agent.runtime_composition.SpeechInterpretationProviderFactory") as factory_cls,
            patch("agent.ai_handler.AIHandler") as handler_cls,
            patch("agent.memo_store.MemoStore"),
            patch("agent.main.make_utterance_handler", return_value=MagicMock()),
            patch("agent.push_to_talk.PushToTalk") as ptt_cls,
        ):
            factory_cls.return_value.create_provider_set.return_value = providers

            build_audio_runtime({
                "audio": {"mode": "ptt"},
                "instruction_mode": {
                    "intent_fallbacks": {
                        "multi_step_guard": False,
                        "memo_fuzzy_recall": False,
                    },
                },
            }, MagicMock())

        self.assertEqual(
            handler_cls.call_args.kwargs["intent_fallbacks"],
            IntentFallbackOptions(
                multi_step_guard=False,
                selected_edit_override=True,
                memo_fuzzy_recall=False,
            ),
        )
        self.assertNotIn("personal_lexicon", handler_cls.call_args.kwargs)
        ptt_cls.return_value.start.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
