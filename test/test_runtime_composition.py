import inspect
import unittest
from unittest.mock import MagicMock, patch

from agent.capture_path import UtteranceEvent
from agent.ai_intent import IntentFallbackOptions
import agent.runtime_composition as runtime_composition
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
        backend.ime_monitor = Component("ime")
        backend.correction_observation = Component("correction")
        backend.reader = Component("reader")

        backend.stop()

        self.assertEqual(calls, ["audio", "ime", "correction", "reader"])
        self.assertIsNone(backend.audio)
        self.assertIsNone(backend.ime_monitor)
        self.assertIsNone(backend.correction_observation)
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

    def test_runtime_composition_does_not_depend_on_main_handler_factories(self):
        source = inspect.getsource(runtime_composition)

        self.assertNotIn("from agent.main import make_serial_handlers", source)
        self.assertNotIn("from agent.main import make_utterance_handler", source)

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
            patch("agent.operation_confirmation.make_operation_confirmation", return_value="confirm") as confirm_factory,
            patch("agent.runtime_handlers.make_utterance_handler", return_value=MagicMock()),
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
                "correction_memory": {
                    "confirm_threshold": 3,
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
        self.assertEqual(handler_cls.call_args.kwargs["confirm_operation"], "confirm")
        confirm_factory.assert_called_once()
        event_sink = ptt_cls.call_args.kwargs["on_event"]
        self.assertTrue(callable(event_sink))
        ptt_cls.return_value.start.assert_called_once_with()

    def test_build_audio_runtime_passes_correction_config_to_utterance_handler(self):
        from agent.runtime_composition import build_audio_runtime

        providers = MagicMock()
        providers.text_operation_editor = None
        providers.instruction_stt = None
        providers.utterance_stt = MagicMock()
        mode = MagicMock()
        mode.handle_utterance = MagicMock()
        mode.correction_observation_hooks = None
        with (
            patch("agent.runtime_composition.SpeechInterpretationProviderFactory") as factory_cls,
            patch("agent.runtime_handlers.make_utterance_handler", return_value=mode) as utterance_handler,
            patch("agent.push_to_talk.PushToTalk"),
        ):
            factory_cls.return_value.create_provider_set.return_value = providers

            build_audio_runtime({
                "audio": {"mode": "ptt"},
                "correction_memory": {"confirm_threshold": 3},
            }, MagicMock())

        self.assertEqual(
            utterance_handler.call_args.kwargs["correction_config"],
            {"confirm_threshold": 3},
        )
        self.assertTrue(utterance_handler.call_args.kwargs["return_mode"])

    def test_build_audio_runtime_wires_correction_observation_hooks_to_ptt(self):
        from agent.runtime_composition import build_audio_runtime

        providers = MagicMock()
        providers.text_operation_editor = None
        providers.instruction_stt = None
        providers.utterance_stt = MagicMock()
        hooks = MagicMock()
        hooks.enabled = True
        mode = MagicMock()
        mode.handle_utterance = MagicMock()
        mode.correction_observation_hooks = hooks
        with (
            patch("agent.runtime_composition.SpeechInterpretationProviderFactory") as factory_cls,
            patch("agent.runtime_handlers.make_utterance_handler", return_value=mode),
            patch("agent.ime_commit_monitor.ImeCommitMonitor") as ime_monitor_cls,
            patch("agent.push_to_talk.PushToTalk") as ptt_cls,
        ):
            factory_cls.return_value.create_provider_set.return_value = providers

            build_audio_runtime({"audio": {"mode": "ptt"}}, MagicMock())

        ptt_cls.call_args.kwargs["on_event"](UtteranceEvent.dictation(b"pcm", polish=True))
        mode.handle_utterance.assert_called_once_with(b"pcm", True)

        on_key_press = ptt_cls.call_args.kwargs["on_key_press"]
        key = MagicMock()
        on_key_press(key)
        hooks.record_key_press.assert_called_once_with(key)

        on_key_release = ptt_cls.call_args.kwargs["on_key_release"]
        on_key_release(key)
        hooks.record_key_release.assert_called_once_with(key)

        on_committed_text = ime_monitor_cls.call_args.args[0]
        on_committed_text("净")
        hooks.record_committed_text.assert_called_once_with("净")
        ime_monitor_cls.return_value.start.assert_called_once_with()
        self.assertEqual(
            ptt_cls.return_value._correction_ime_monitor,
            ime_monitor_cls.return_value,
        )
        self.assertEqual(
            ptt_cls.return_value._correction_observation,
            hooks,
        )

    def test_build_audio_runtime_does_not_wire_correction_observation_when_disabled(self):
        from agent.runtime_composition import build_audio_runtime

        providers = MagicMock()
        providers.text_operation_editor = None
        providers.instruction_stt = None
        providers.utterance_stt = MagicMock()
        hooks = MagicMock()
        hooks.enabled = False
        mode = MagicMock()
        mode.handle_utterance = MagicMock()
        mode.correction_observation_hooks = hooks
        with (
            patch("agent.runtime_composition.SpeechInterpretationProviderFactory") as factory_cls,
            patch("agent.runtime_handlers.make_utterance_handler", return_value=mode),
            patch("agent.ime_commit_monitor.ImeCommitMonitor") as ime_monitor_cls,
            patch("agent.push_to_talk.PushToTalk") as ptt_cls,
        ):
            factory_cls.return_value.create_provider_set.return_value = providers

            build_audio_runtime({"audio": {"mode": "ptt"}}, MagicMock())

        self.assertIsNone(ptt_cls.call_args.kwargs["on_key_press"])
        self.assertIsNone(ptt_cls.call_args.kwargs["on_key_release"])
        ime_monitor_cls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
