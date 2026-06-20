import unittest
from unittest.mock import MagicMock

from agent.correction_observation import CorrectionObservationHooks


class CorrectionObservationHooksTests(unittest.TestCase):
    def test_key_press_records_and_schedules_observation(self):
        tracker = MagicMock()
        scheduler = MagicMock()
        hooks = CorrectionObservationHooks(tracker=tracker, scheduler=scheduler)
        key = MagicMock()

        hooks.record_key_press(key)

        tracker.record_key_press.assert_called_once_with(key)
        scheduler.schedule_after_edit.assert_called_once_with()

    def test_key_release_only_schedules_after_edit(self):
        tracker = MagicMock()
        scheduler = MagicMock()
        hooks = CorrectionObservationHooks(tracker=tracker, scheduler=scheduler)

        hooks.record_key_release("shift")

        tracker.record_key_press.assert_not_called()
        scheduler.schedule_after_edit.assert_called_once_with()

    def test_committed_text_schedules_only_when_tracker_accepts_it(self):
        tracker = MagicMock()
        tracker.record_committed_text.return_value = False
        scheduler = MagicMock()
        hooks = CorrectionObservationHooks(tracker=tracker, scheduler=scheduler)

        self.assertFalse(hooks.record_committed_text("w"))
        scheduler.schedule_after_edit.assert_not_called()

        tracker.record_committed_text.return_value = True
        self.assertTrue(hooks.record_committed_text("净"))
        scheduler.schedule_after_edit.assert_called_once_with()

    def test_stop_stops_scheduler(self):
        scheduler = MagicMock()
        hooks = CorrectionObservationHooks(scheduler=scheduler)

        hooks.stop()

        scheduler.stop.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()

