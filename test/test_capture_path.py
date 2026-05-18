import unittest
from unittest.mock import MagicMock, patch

from pynput import keyboard as kb

from agent.capture_path import UtteranceEvent
from agent.capture_path_runtime import CapturePathRuntime, CaptureStart, PolishToggle
from agent.keyboard_monitor import KeyboardMonitor
from agent.push_to_talk import PushToTalk


class CapturePathTests(unittest.TestCase):
    def test_utterance_event_constructors_name_capture_mode(self):
        self.assertEqual(
            UtteranceEvent.dictation(b"pcm", polish=True),
            UtteranceEvent(pcm=b"pcm", mode="dictation", polish=True),
        )
        self.assertEqual(
            UtteranceEvent.instruction_edit(b"edit"),
            UtteranceEvent(pcm=b"edit", mode="instruction_edit"),
        )
        self.assertEqual(
            UtteranceEvent.instruction(b"ai"),
            UtteranceEvent(pcm=b"ai", mode="instruction"),
        )

    def test_push_to_talk_dispatch_maps_capture_events_to_existing_callbacks(self):
        on_dictation = MagicMock()
        on_edit = MagicMock()
        on_instruction = MagicMock()
        ptt = PushToTalk(
            on_dictation,
            on_edit_utterance=on_edit,
            on_ai_utterance=on_instruction,
        )

        with patch("agent.push_to_talk.threading.Thread") as thread:
            ptt._dispatch_utterance(UtteranceEvent.dictation(b"one", polish=True), "dict")
            ptt._dispatch_utterance(UtteranceEvent.instruction_edit(b"two"), "edit")
            ptt._dispatch_utterance(UtteranceEvent.instruction(b"three"), "inst")

        calls = thread.call_args_list
        self.assertEqual(calls[0].kwargs["target"], on_dictation)
        self.assertEqual(calls[0].kwargs["args"], (b"one", True))
        self.assertEqual(calls[1].kwargs["target"], on_edit)
        self.assertEqual(calls[1].kwargs["args"], (b"two",))
        self.assertEqual(calls[2].kwargs["target"], on_instruction)
        self.assertEqual(calls[2].kwargs["args"], (b"three",))

    def test_toggle_key_disables_and_reenables_recording(self):
        on_dictation = MagicMock()
        ptt = PushToTalk(on_dictation, ptt_key="a", toggle_key="b")

        with patch.object(ptt, "_start_recording") as start_recording:
            ptt._on_press(ptt._toggle_keys[0])
            ptt._on_press(ptt._ptt_keys[0])
            ptt._on_press(ptt._toggle_keys[0])
            ptt._on_press(ptt._ptt_keys[0])

        start_recording.assert_called_once_with()

    def test_toggle_key_works_without_keyboard_monitor_side_effects(self):
        on_dictation = MagicMock()
        monitor = MagicMock()
        ptt = PushToTalk(on_dictation, ptt_key="a", toggle_key="b", kbd_monitor=monitor)

        ptt._on_press(ptt._toggle_keys[0])

        monitor.process_press.assert_not_called()

    def test_enter_marks_tracked_segment_unsafe(self):
        env = MagicMock()
        monitor = KeyboardMonitor(env)

        monitor.process_press(kb.Key.enter)

        env.mark_tracked_segment_unsafe.assert_called_once_with()

    def test_capture_path_runtime_blocks_capture_when_disabled(self):
        runtime = CapturePathRuntime()

        self.assertFalse(runtime.toggle_enabled())
        self.assertIsNone(runtime.press_dictation("ptt", now=10.0))

        self.assertTrue(runtime.toggle_enabled())
        self.assertEqual(
            runtime.press_dictation("ptt", now=11.0),
            CaptureStart(mode="dictate", polish=False),
        )

    def test_capture_path_runtime_keeps_one_active_capture(self):
        runtime = CapturePathRuntime()

        self.assertEqual(runtime.press_instruction_edit("edit"), CaptureStart(mode="edit"))
        self.assertIsNone(runtime.press_instruction("ai"))
        self.assertIsNone(runtime.release("other"))

        self.assertEqual(runtime.release("edit"), "edit")
        self.assertEqual(runtime.press_instruction("ai"), CaptureStart(mode="ai"))

    def test_capture_path_runtime_toggles_polish_on_double_tap_without_capture(self):
        runtime = CapturePathRuntime()

        self.assertEqual(
            runtime.press_dictation("ptt", now=10.0),
            CaptureStart(mode="dictate", polish=False),
        )
        self.assertEqual(runtime.release("ptt"), "dictate")

        self.assertEqual(runtime.press_dictation("ptt", now=10.2), PolishToggle(polish=True))
        self.assertFalse(runtime.is_capturing)

        self.assertEqual(
            runtime.press_dictation("ptt", now=11.0),
            CaptureStart(mode="dictate", polish=True),
        )

    def test_push_to_talk_shows_status_when_double_tap_toggles_polish_mode(self):
        on_dictation = MagicMock()
        status = MagicMock()
        ptt = PushToTalk(on_dictation, ptt_key="a", status_window=status)

        with patch("agent.push_to_talk.time.monotonic", side_effect=[10.0, 10.2]):
            ptt._on_press(ptt._ptt_keys[0])
            ptt._on_release(ptt._ptt_keys[0])
            ptt._on_press(ptt._ptt_keys[0])

        status.set_state.assert_called_with("polish_mode")

    def test_push_to_talk_shows_status_when_double_tap_toggles_back_to_dictation_mode(self):
        on_dictation = MagicMock()
        status = MagicMock()
        ptt = PushToTalk(on_dictation, ptt_key="a", status_window=status)
        ptt._capture_runtime.polish_mode = True

        with patch("agent.push_to_talk.time.monotonic", side_effect=[10.0, 10.2]):
            ptt._on_press(ptt._ptt_keys[0])
            ptt._on_release(ptt._ptt_keys[0])
            ptt._on_press(ptt._ptt_keys[0])

        status.set_state.assert_called_with("dictation_mode")


if __name__ == "__main__":
    unittest.main()
