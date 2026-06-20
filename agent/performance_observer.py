"""Structured runtime performance logging for Voice Keyboard Engine flows."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable


Clock = Callable[[], float]


@dataclass
class PerformanceSpan:
    name: str
    clock: Clock = time.perf_counter
    started_at: float = field(init=False)
    finished_at: float | None = None

    def __post_init__(self) -> None:
        self.started_at = self.clock()

    def finish(self) -> float:
        if self.finished_at is None:
            self.finished_at = self.clock()
        return self.duration

    @property
    def duration(self) -> float:
        end = self.finished_at if self.finished_at is not None else self.clock()
        return max(0.0, end - self.started_at)


class PerformanceObserver:
    """Tiny interface for structured performance events."""

    def span(self, name: str, **fields) -> PerformanceSpan:
        return PerformanceSpan(name)

    def finish(self, span: PerformanceSpan, **fields) -> None:
        span.finish()


class LoggingPerformanceObserver(PerformanceObserver):
    def __init__(self, *, enabled: bool = True, clock: Clock = time.perf_counter):
        self._enabled = bool(enabled)
        self._clock = clock

    def span(self, name: str, **fields) -> PerformanceSpan:
        return PerformanceSpan(name=name, clock=self._clock)

    def finish(self, span: PerformanceSpan, **fields) -> None:
        duration = span.finish()
        if not self._enabled:
            return
        parts = [f"[perf] {span.name}={duration:.3f}s"]
        for key, value in fields.items():
            if value is None:
                continue
            parts.append(f"{key}={value}")
        print(" ".join(parts))


class NullPerformanceObserver(PerformanceObserver):
    def span(self, name: str, **fields) -> PerformanceSpan:
        return PerformanceSpan(name)

    def finish(self, span: PerformanceSpan, **fields) -> None:
        span.finish()

