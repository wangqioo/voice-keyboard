import unittest
from unittest.mock import MagicMock, patch

from agent.capture_path import UtteranceEvent
from agent.capture_path_runtime import CapturePathRuntime, CaptureStart, PolishToggle
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

    def test_push_to_talk_dispatch_prefers_event_sink(self):
        on_event = MagicMock()
        on_dictation = MagicMock()
        ptt = PushToTalk(on_dictation, on_event=on_event)
        event = UtteranceEvent.dictation(b"one", polish=True)

        with patch("agent.push_to_talk.threading.Thread") as thread:
            ptt._dispatch_utterance(event, "dict")

        self.assertEqual(thread.call_args.kwargs["target"], on_event)
        self.assertEqual(thread.call_args.kwargs["args"], (event,))
        on_dictation.assert_not_called()

    def test_event_sink_keeps_ai_hotkey_enabled(self):
        ptt = PushToTalk(on_event=MagicMock(), ptt_key="a", ai_key="b")

        self.assertEqual(len(ptt._ai_keys), 1)

    def test_toggle_key_disables_and_reenables_recording(self):
        on_dictation = MagicMock()
        ptt = PushToTalk(on_dictation, ptt_key="a", toggle_key="b")

        with patch.object(ptt, "_start_recording") as start_recording:
            ptt._on_press(ptt._toggle_keys[0])
            ptt._on_press(ptt._ptt_keys[0])
            ptt._on_press(ptt._toggle_keys[0])
            ptt._on_press(ptt._ptt_keys[0])

        start_recording.assert_called_once_with()

    def test_push_to_talk_forwards_non_hotkey_presses_to_correction_tracker(self):
        on_dictation = MagicMock()
        on_key_press = MagicMock()
        ptt = PushToTalk(on_dictation, ptt_key="a", toggle_key="b", on_key_press=on_key_press)
        ordinary_key = MagicMock()

        ptt._on_press(ordinary_key)

        on_key_press.assert_called_once_with(ordinary_key)

    def test_push_to_talk_uses_quartz_listener_on_macos(self):
        on_dictation = MagicMock()
        ptt = PushToTalk(on_dictation, ptt_key="a")

        with (
            patch("agent.push_to_talk.sys.platform", "darwin"),
            patch("agent.macos_keyboard_listener.MacOSKeyboardListener") as quartz_listener,
            patch("agent.push_to_talk.kb.Listener") as pynput_listener,
            patch("agent.push_to_talk.find_device", return_value=None),
        ):
            quartz_listener.return_value.start.return_value = None
            ptt.start()

        quartz_listener.assert_called_once_with(
            on_press=ptt._on_press,
            on_release=ptt._on_release,
        )
        quartz_listener.return_value.start.assert_called_once_with()
        pynput_listener.assert_not_called()

    def test_push_to_talk_forwards_non_hotkey_releases_to_correction_tracker(self):
        on_dictation = MagicMock()
        on_key_release = MagicMock()
        ptt = PushToTalk(on_dictation, ptt_key="a", on_key_release=on_key_release)
        ordinary_key = MagicMock()

        ptt._on_release(ordinary_key)

        on_key_release.assert_called_once_with(ordinary_key)

    def test_push_to_talk_does_not_forward_keys_while_capturing(self):
        on_dictation = MagicMock()
        on_key_press = MagicMock()
        ptt = PushToTalk(on_dictation, ptt_key="a", on_key_press=on_key_press)
        ptt._capture_runtime.press_dictation(ptt._ptt_keys[0], now=10.0)

        ptt._on_press(MagicMock())

        on_key_press.assert_not_called()

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

        with (
            patch("agent.push_to_talk.time.monotonic", side_effect=[10.0, 10.2]),
            patch.object(ptt, "_start_recording"),
        ):
            ptt._on_press(ptt._ptt_keys[0])
            ptt._on_release(ptt._ptt_keys[0])
            ptt._on_press(ptt._ptt_keys[0])

        self.assertEqual(status.set_state.call_args_list[-1].args, ("polish_mode",))
        self.assertNotIn(("recording",), [call.args for call in status.set_state.call_args_list])

    def test_push_to_talk_shows_status_when_double_tap_toggles_back_to_dictation_mode(self):
        on_dictation = MagicMock()
        status = MagicMock()
        ptt = PushToTalk(on_dictation, ptt_key="a", status_window=status)
        ptt._capture_runtime.polish_mode = True

        with (
            patch("agent.push_to_talk.time.monotonic", side_effect=[10.0, 10.2]),
            patch.object(ptt, "_start_recording"),
        ):
            ptt._on_press(ptt._ptt_keys[0])
            ptt._on_release(ptt._ptt_keys[0])
            ptt._on_press(ptt._ptt_keys[0])

        self.assertEqual(status.set_state.call_args_list[-1].args, ("dictation_mode",))
        self.assertNotIn(("recording",), [call.args for call in status.set_state.call_args_list])

    def test_push_to_talk_shows_dictation_recording_status_immediately(self):
        on_dictation = MagicMock()
        status = MagicMock()
        ptt = PushToTalk(on_dictation, ptt_key="a", status_window=status)

        ptt._capture_runtime.press_dictation(ptt._ptt_keys[0], now=10.0)
        with patch("agent.push_to_talk.sd.RawInputStream") as stream_cls:
            stream_cls.return_value.start.return_value = None
            ptt._start_recording()

        status.set_state.assert_called_once_with("recording")
        self.assertIsNone(ptt._recording_status_timer)

    def test_push_to_talk_cancels_delayed_recording_status_when_stopped(self):
        on_dictation = MagicMock()
        ptt = PushToTalk(on_dictation, ptt_key="a")
        timer = MagicMock()
        ptt._recording_status_timer = timer

        ptt._stop_recording("dictate")

        timer.cancel.assert_called_once()
        self.assertIsNone(ptt._recording_status_timer)


if __name__ == "__main__":
    unittest.main()
