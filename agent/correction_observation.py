"""Runtime adapter for Dictation Correction Memory observation events."""

from __future__ import annotations

from dataclasses import dataclass

from agent.correction_memory import CorrectionLearningTracker, CorrectionObservationScheduler


@dataclass(frozen=True)
class CorrectionObservationHooks:
    """Small interface runtime composition can attach to Capture Path events."""

    tracker: CorrectionLearningTracker | None = None
    scheduler: CorrectionObservationScheduler | None = None

    @property
    def enabled(self) -> bool:
        return self.tracker is not None

    def record_key_press(self, key: object) -> None:
        if self.tracker is None:
            return
        self.tracker.record_key_press(key)
        self._schedule_after_edit()

    def record_key_release(self, _key: object) -> None:
        if self.tracker is None:
            return
        self._schedule_after_edit()

    def record_committed_text(self, text: str) -> bool:
        if self.tracker is None:
            return False
        committed = self.tracker.record_committed_text(text)
        if committed:
            self._schedule_after_edit()
        return committed

    def stop(self) -> None:
        if self.scheduler is not None:
            self.scheduler.stop()

    def _schedule_after_edit(self) -> None:
        if self.scheduler is not None:
            self.scheduler.schedule_after_edit()

