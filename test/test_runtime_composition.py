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
        backend.kbd_monitor = Component("keyboard")

        backend.stop()

        self.assertEqual(calls, ["audio", "reader", "keyboard"])
        self.assertIsNone(backend.audio)
        self.assertIsNone(backend.reader)
        self.assertIsNone(backend.mouse_monitor)
        self.assertIsNone(backend.kbd_monitor)

    def test_selection_only_instruction_mode_does_not_start_keyboard_monitor(self):
        with (
            patch("agent.runtime_composition.load_config", return_value={
                "stt": {"provider": "openai", "api_key": "sk"},
                "instruction_mode": {"require_selection_for_edit": True},
            }),
            patch("agent.typer.init"),
            patch("agent.runtime_composition.SpeechInterpretationProviderFactory") as factory_cls,
        ):
            factory_cls.return_value.create_provider_set.return_value = None
            backend = build_runtime_backend(RuntimeOptions(no_serial=True), MagicMock(), None, MagicMock())

        self.assertIsNone(backend.kbd_monitor)

    def test_tracked_segment_instruction_mode_starts_cursor_safety_monitors(self):
        with (
            patch("agent.runtime_composition.load_config", return_value={
                "stt": {"provider": "openai", "api_key": "sk"},
                "instruction_mode": {"require_selection_for_edit": False},
            }),
            patch("agent.typer.init"),
            patch("agent.runtime_composition.SpeechInterpretationProviderFactory") as factory_cls,
            patch("agent.keyboard_monitor.KeyboardMonitor") as keyboard_cls,
            patch("agent.mouse_monitor.MouseMonitor") as mouse_cls,
        ):
            factory_cls.return_value.create_provider_set.return_value = None
            keyboard = keyboard_cls.return_value
            mouse = mouse_cls.return_value

            backend = build_runtime_backend(RuntimeOptions(no_serial=True), MagicMock(), None, MagicMock())

        self.assertIs(backend.kbd_monitor, keyboard)
        self.assertIs(backend.mouse_monitor, mouse)
        keyboard.start.assert_called_once_with()
        mouse.start.assert_called_once_with()

    def test_current_window_instruction_mode_is_default(self):
        with (
            patch("agent.runtime_composition.load_config", return_value={
                "stt": {"provider": "openai", "api_key": "sk"},
            }),
            patch("agent.typer.init"),
            patch("agent.runtime_composition.SpeechInterpretationProviderFactory") as factory_cls,
            patch("agent.keyboard_monitor.KeyboardMonitor") as keyboard_cls,
            patch("agent.mouse_monitor.MouseMonitor") as mouse_cls,
        ):
            factory_cls.return_value.create_provider_set.return_value = None
            keyboard = keyboard_cls.return_value
            mouse = mouse_cls.return_value

            backend = build_runtime_backend(RuntimeOptions(no_serial=True), MagicMock(), None, MagicMock())

        self.assertIs(backend.kbd_monitor, keyboard)
        self.assertIs(backend.mouse_monitor, mouse)
        keyboard.start.assert_called_once_with()
        mouse.start.assert_called_once_with()

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
                        "edit_hint_override": True,
                        "memo_fuzzy_recall": False,
                    },
                },
            }, MagicMock())

        self.assertEqual(
            handler_cls.call_args.kwargs["intent_fallbacks"],
            IntentFallbackOptions(
                multi_step_guard=False,
                selected_edit_override=True,
                edit_hint_override=True,
                memo_fuzzy_recall=False,
            ),
        )
        ptt_cls.return_value.start.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
