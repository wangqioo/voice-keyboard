"""Local correction memory for Dictation Mode.

This module keeps learned speech corrections separate from Memo.  It stores
small wrong->correct pairs that can be applied before dictation text reaches
the Input Environment.
"""

from __future__ import annotations

import difflib
import json
import re
import threading
import time
import unicodedata
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable


_DEFAULT_PATH = Path.home() / ".voice-keyboard" / "correction_memory.json"
_MIN_TERM_LENGTH = 2
_MAX_TERM_LENGTH = 5
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_CJK_TERM_RE = re.compile(r"^[\u3400-\u9fff]+$")
_SPACE_RE = re.compile(r"\s")
_EDGE_PUNCTUATION_RE = re.compile(r"^[\s，。,.、；;：:！？!?（）()【】\[\]「」『』\"'“”‘’]+|[\s，。,.、；;：:！？!?（）()【】\[\]「」『』\"'“”‘’]+$")
_PUNCTUATION_ONLY_RE = re.compile(r"^[\s，。,.、；;：:！？!?（）()【】\[\]「」『』\"'“”‘’]+$")
_PUNCTUATION_SPLIT_RE = re.compile(r"[\s，。,.、；;：:！？!?（）()【】\[\]「」『』\"'“”‘’]+")
_NICKNAME_PREFIXES = {"小", "老", "阿"}


@dataclass(frozen=True)
class CorrectionEntry:
    wrong: str
    correct: str
    count: int = 1
    source: str = "manual_edit"
    updated_at: float = 0.0


@dataclass(frozen=True)
class InferredCorrection:
    wrong: str
    correct: str
    evidence_count: int = 1


@dataclass(frozen=True)
class LearnedCorrection:
    wrong: str
    correct: str
    count: int
    newly_confirmed: bool = False


@dataclass(frozen=True)
class CorrectionTextSnapshot:
    text: str
    source: str = "unknown"
    detail: str = ""


@dataclass(frozen=True)
class CorrectionCaptureDecision:
    decision: str
    reason: str
    source: str = "unknown"
    detail: str = ""
    before: str = ""
    after: str = ""
    inferred: tuple[InferredCorrection, ...] = ()


@dataclass(frozen=True)
class CorrectionObservationResult:
    candidates: tuple[LearnedCorrection, ...] = ()
    confirmed: tuple[LearnedCorrection, ...] = ()
    decisions: tuple[CorrectionCaptureDecision, ...] = ()


@dataclass
class _PendingCorrectionObservation:
    text: str
    inserted_at: float
    shadow_text: str
    caret: int
    shadow_changed: bool = False
    keyboard_edit_seen: bool = False
    awaiting_ime_commit: bool = False
    composition_text: str = ""
    last_deleted_text: str = ""
    last_deleted_context: str = ""
    last_deleted_context_index: int = 0
    committed_replacement_evidence: dict[tuple[str, str], int] = field(default_factory=dict)
    recorded_evidence: dict[tuple[str, str], int] = field(default_factory=dict)


class CorrectionMemory:
    def __init__(
        self,
        path: Path | None = None,
        *,
        confirm_threshold: int = 2,
        enabled: bool = True,
    ):
        self._path = path or _DEFAULT_PATH
        self._confirm_threshold = max(1, int(confirm_threshold or 2))
        self._enabled = bool(enabled)
        self._lock = threading.Lock()
        self._entries: dict[str, CorrectionEntry] = {}
        self._candidates: dict[tuple[str, str], CorrectionEntry] = {}
        self._mtime_ns: int | None = None
        self._load()

    @classmethod
    def from_config(cls, cfg: dict | None) -> "CorrectionMemory":
        cfg = cfg or {}
        path_text = str(cfg.get("path", "") or "").strip()
        path = Path(path_text).expanduser() if path_text else None
        return cls(
            path=path,
            confirm_threshold=int(cfg.get("confirm_threshold", 2) or 2),
            enabled=bool(cfg.get("enabled", True)),
        )

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def entries(self) -> tuple[CorrectionEntry, ...]:
        with self._lock:
            self._reload_if_changed()
            return tuple(self._entries.values())

    @property
    def candidates(self) -> tuple[CorrectionEntry, ...]:
        with self._lock:
            self._reload_if_changed()
            return tuple(self._candidates.values())

    @property
    def path(self) -> Path:
        return self._path

    @property
    def confirm_threshold(self) -> int:
        return self._confirm_threshold

    def apply(self, text: str) -> str:
        if not self._enabled or not text:
            return text
        with self._lock:
            self._reload_if_changed()
            entries = sorted(
                self._entries.values(),
                key=lambda entry: len(entry.wrong),
                reverse=True,
            )
        corrected = str(text)
        for entry in entries:
            if entry.wrong and entry.wrong != entry.correct:
                corrected = corrected.replace(entry.wrong, entry.correct)
        return corrected

    def record_observation(self, before: str, after: str) -> CorrectionObservationResult:
        if not self._enabled:
            return CorrectionObservationResult()
        inferred = infer_correction_pairs(before, after)
        candidates: list[LearnedCorrection] = []
        confirmed: list[LearnedCorrection] = []
        for correction in inferred:
            learned = self.learn(
                correction.wrong,
                correction.correct,
                evidence_count=correction.evidence_count,
            )
            if learned is None:
                continue
            if learned.newly_confirmed:
                confirmed.append(learned)
            else:
                candidates.append(learned)
        return CorrectionObservationResult(
            candidates=tuple(candidates),
            confirmed=tuple(confirmed),
        )

    def learn(
        self,
        wrong: str,
        correct: str,
        *,
        evidence_count: int = 1,
    ) -> LearnedCorrection | None:
        wrong = _clean_term(wrong)
        correct = _clean_term(correct)
        if not _valid_pair(wrong, correct):
            return None
        count_delta = max(1, int(evidence_count or 1))
        now = time.time()
        with self._lock:
            self._reload_if_changed()
            existing = self._entries.get(wrong)
            if existing is not None and existing.correct == correct:
                updated = CorrectionEntry(
                    wrong=wrong,
                    correct=correct,
                    count=existing.count + count_delta,
                    source=existing.source,
                    updated_at=now,
                )
                self._entries[wrong] = updated
                self._save()
                return LearnedCorrection(wrong, correct, updated.count, False)

            key = (wrong, correct)
            candidate = self._candidates.get(key)
            next_count = (candidate.count if candidate else 0) + count_delta
            if next_count >= self._confirm_threshold:
                entry = CorrectionEntry(
                    wrong=wrong,
                    correct=correct,
                    count=next_count,
                    updated_at=now,
                )
                self._entries[wrong] = entry
                self._candidates.pop(key, None)
                self._save()
                return LearnedCorrection(wrong, correct, next_count, True)

            self._candidates[key] = CorrectionEntry(
                wrong=wrong,
                correct=correct,
                count=next_count,
                updated_at=now,
            )
            self._save()
            return LearnedCorrection(wrong, correct, next_count, False)

    def delete_entry(self, wrong: str) -> bool:
        wrong = _clean_term(wrong)
        if not wrong:
            return False
        with self._lock:
            self._reload_if_changed()
            if wrong not in self._entries:
                return False
            self._entries.pop(wrong, None)
            self._save()
            return True

    def delete_candidate(self, wrong: str, correct: str) -> bool:
        wrong = _clean_term(wrong)
        correct = _clean_term(correct)
        if not wrong or not correct:
            return False
        with self._lock:
            self._reload_if_changed()
            key = (wrong, correct)
            if key not in self._candidates:
                return False
            self._candidates.pop(key, None)
            self._save()
            return True

    def _load(self) -> None:
        if not self._path.exists():
            return
        self._read_from_disk()

    def _reload_if_changed(self) -> None:
        try:
            mtime_ns = self._path.stat().st_mtime_ns
        except FileNotFoundError:
            if self._mtime_ns is not None:
                self._entries = {}
                self._candidates = {}
                self._mtime_ns = None
            return
        if self._mtime_ns is None or mtime_ns != self._mtime_ns:
            self._read_from_disk()

    def _read_from_disk(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[correction] 读取失败 {self._path}: {e}")
            return
        if not isinstance(raw, dict):
            return
        entries = {}
        candidates = {}
        for row in _rows(raw.get("entries")):
            entry = _entry_from_row(row)
            if entry is not None:
                entries[entry.wrong] = entry
        for row in _rows(raw.get("candidates")):
            entry = _entry_from_row(row)
            if entry is not None:
                candidates[(entry.wrong, entry.correct)] = entry
        self._entries = entries
        self._candidates = candidates
        try:
            self._mtime_ns = self._path.stat().st_mtime_ns
        except FileNotFoundError:
            self._mtime_ns = None

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "entries": [_entry_to_row(entry) for entry in self._entries.values()],
            "candidates": [_entry_to_row(entry) for entry in self._candidates.values()],
        }
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._mtime_ns = self._path.stat().st_mtime_ns


class CorrectionLearningTracker:
    def __init__(
        self,
        memory: CorrectionMemory,
        read_current_text: Callable[[], str | CorrectionTextSnapshot | None],
        *,
        read_screen_text: Callable[[str], str | CorrectionTextSnapshot | None] | None = None,
        observe_window_seconds: float = 30.0,
        max_pending: int = 5,
        screen_ocr_after_edit_seconds: float = 0.8,
        clock: Callable[[], float] = time.time,
        debug: bool = False,
    ):
        self._memory = memory
        self._read_current_text = read_current_text
        self._read_screen_text = read_screen_text
        self._observe_window_seconds = max(1.0, float(observe_window_seconds or 30.0))
        self._observe_grace_seconds = 1.0
        self._max_pending = max(1, int(max_pending or 5))
        self._screen_ocr_after_edit_seconds = max(
            0.1,
            float(screen_ocr_after_edit_seconds or 0.8),
        )
        self._clock = clock
        self._debug = bool(debug)
        self._pending: deque[_PendingCorrectionObservation] = deque(maxlen=self._max_pending)

    @classmethod
    def from_config(
        cls,
        cfg: dict | None,
        memory: CorrectionMemory,
        read_current_text: Callable[[], str | CorrectionTextSnapshot | None],
        read_screen_text: Callable[[str], str | CorrectionTextSnapshot | None] | None = None,
    ) -> "CorrectionLearningTracker":
        cfg = cfg or {}
        screen_ocr_enabled = bool(cfg.get("screen_ocr_fallback", True))
        return cls(
            memory,
            read_current_text,
            read_screen_text=read_screen_text if screen_ocr_enabled else None,
            observe_window_seconds=float(cfg.get("observe_window_seconds", 30.0) or 30.0),
            max_pending=int(cfg.get("max_pending", 5) or 5),
            screen_ocr_after_edit_seconds=float(
                cfg.get("screen_ocr_after_edit_seconds", 0.8) or 0.8
            ),
            debug=bool(cfg.get("debug", False)),
        )

    def remember_inserted(self, text: str) -> None:
        if not self._memory.enabled or not text:
            self._pending.clear()
            return
        value = str(text)
        self._pending.append(
            _PendingCorrectionObservation(
                text=value,
                inserted_at=self._clock(),
                shadow_text=value,
                caret=len(value),
            )
        )

    def record_key_press(self, key: object) -> None:
        if not self._pending:
            return
        pending = self._pending[-1]
        action = _key_action(key)
        if action == "backspace":
            if pending.composition_text:
                pending.composition_text = pending.composition_text[:-1]
                pending.inserted_at = self._clock()
                return
            if pending.caret <= 0:
                return
            _record_pending_deletion(pending, pending.caret - 1, pending.caret)
            deleted = pending.shadow_text[pending.caret - 1:pending.caret]
            pending.shadow_text = (
                pending.shadow_text[:pending.caret - 1]
                + pending.shadow_text[pending.caret:]
            )
            pending.caret -= 1
            pending.shadow_changed = True
            pending.keyboard_edit_seen = True
            pending.inserted_at = self._clock()
            pending.awaiting_ime_commit = bool(_CJK_RE.search(deleted))
            pending.composition_text = ""
            return
        if action == "delete":
            if pending.caret >= len(pending.shadow_text):
                return
            _record_pending_deletion(pending, pending.caret, pending.caret + 1)
            deleted = pending.shadow_text[pending.caret:pending.caret + 1]
            pending.shadow_text = (
                pending.shadow_text[:pending.caret]
                + pending.shadow_text[pending.caret + 1:]
            )
            pending.shadow_changed = True
            pending.keyboard_edit_seen = True
            pending.inserted_at = self._clock()
            pending.awaiting_ime_commit = bool(_CJK_RE.search(deleted))
            pending.composition_text = ""
            return
        if action == "left":
            pending.caret = max(0, pending.caret - 1)
            return
        if action == "right":
            pending.caret = min(len(pending.shadow_text), pending.caret + 1)
            return
        if action == "home":
            pending.caret = 0
            return
        if action == "end":
            pending.caret = len(pending.shadow_text)
            return
        text = _key_text(key)
        if not text:
            return
        if pending.awaiting_ime_commit:
            if _CJK_RE.search(text):
                _record_committed_replacement_evidence(pending, text)
                pending.composition_text = ""
                pending.awaiting_ime_commit = False
            elif _ime_composition_key_text(text):
                pending.composition_text += text
                pending.inserted_at = self._clock()
                return
            elif text in (" ", "\n") and pending.composition_text:
                pending.inserted_at = self._clock()
                return
            else:
                pending.inserted_at = self._clock()
                return
        pending.shadow_text = (
            pending.shadow_text[:pending.caret]
            + text
            + pending.shadow_text[pending.caret:]
        )
        pending.caret += len(text)
        pending.shadow_changed = True
        pending.keyboard_edit_seen = True
        pending.inserted_at = self._clock()

    def record_committed_text(self, text: str) -> bool:
        if not self._pending:
            return False
        value = str(text or "")
        if not value or not _CJK_RE.search(value):
            return False
        pending = self._pending[-1]
        if pending.awaiting_ime_commit:
            _record_committed_replacement_evidence(pending, value)
        pending.shadow_text = (
            pending.shadow_text[:pending.caret]
            + value
            + pending.shadow_text[pending.caret:]
        )
        pending.caret += len(value)
        pending.shadow_changed = True
        pending.keyboard_edit_seen = True
        pending.awaiting_ime_commit = False
        pending.composition_text = ""
        pending.inserted_at = self._clock()
        self._debug_log(f"IME 提交文本 text={_preview(value)!r}")
        return True

    def observe_current_text(self) -> CorrectionObservationResult:
        if not self._pending:
            return CorrectionObservationResult()
        now = self._clock()
        self._discard_expired(now)
        if not self._pending:
            return CorrectionObservationResult()

        try:
            snapshot = _coerce_snapshot(self._read_current_text())
        except Exception as e:
            print(f"[correction] 读取当前文本失败: {e}")
            return CorrectionObservationResult()
        if not snapshot.text:
            shadow_ready = any(
                pending.shadow_changed
                for pending in self._pending
            )
            if not shadow_ready:
                decision = CorrectionCaptureDecision(
                    decision="unsupported",
                    reason="empty_current_text",
                    source=snapshot.source,
                    detail=snapshot.detail,
                )
                self._debug_decision(decision)
                return CorrectionObservationResult(decisions=(decision,))

        decisions: list[CorrectionCaptureDecision] = []
        candidates: list[LearnedCorrection] = []
        for pending in list(self._pending):
            result = self._observe_pending(pending, snapshot)
            if result is None:
                continue
            decisions.extend(result.decisions)
            candidates.extend(result.candidates)
            if result.confirmed:
                self._remove_pending(pending)
                return CorrectionObservationResult(
                    candidates=tuple(candidates),
                    confirmed=result.confirmed,
                    decisions=tuple(decisions),
                )
        return CorrectionObservationResult(
            candidates=tuple(candidates),
            decisions=tuple(decisions),
        )

    def _discard_expired(self, now: float) -> None:
        kept = []
        max_age = self._observe_window_seconds + self._observe_grace_seconds
        for pending in self._pending:
            if now - pending.inserted_at <= max_age:
                kept.append(pending)
            else:
                self._debug_log(f"观察窗口已过期 before={_preview(pending.text)!r}")
        self._pending.clear()
        self._pending.extend(kept)

    def _observe_pending(
        self,
        pending: _PendingCorrectionObservation,
        snapshot: CorrectionTextSnapshot,
    ) -> CorrectionObservationResult | None:
        before = pending.text
        snapshot = self._maybe_read_screen_snapshot(pending, snapshot)
        observed, source = _choose_observed_text(pending, before, snapshot)
        inferred = _merge_inferred_corrections(
            infer_correction_pairs(before, observed),
            _committed_replacement_inferred(pending),
        )
        self._debug_decision(
            CorrectionCaptureDecision(
                decision="observed",
                reason="snapshot",
                source=source,
                detail=snapshot.detail,
                before=before,
                after=observed,
                inferred=inferred,
            )
        )
        if before in observed:
            decision = CorrectionCaptureDecision(
                decision="waiting",
                reason="before_still_present",
                source=source,
                detail=snapshot.detail,
                before=before,
                after=observed,
                inferred=inferred,
            )
            self._debug_decision(decision)
            return CorrectionObservationResult(decisions=(decision,))
        if pending.awaiting_ime_commit and _looks_like_incomplete_ime_edit(before, observed):
            decision = CorrectionCaptureDecision(
                decision="waiting",
                reason="awaiting_ime_commit",
                source=source,
                detail=snapshot.detail,
                before=before,
                after=observed,
                inferred=inferred,
            )
            self._debug_decision(decision)
            return CorrectionObservationResult(decisions=(decision,))
        if (
            not pending.keyboard_edit_seen
            and not _looks_like_same_segment_edit(before, observed)
            and not inferred
        ):
            decision = CorrectionCaptureDecision(
                decision="skipped",
                reason="no_keyboard_edit_for_new_content",
                source=source,
                detail=snapshot.detail,
                before=before,
                after=observed,
                inferred=inferred,
            )
            self._debug_decision(decision)
            return CorrectionObservationResult(decisions=(decision,))
        if not inferred:
            decision = CorrectionCaptureDecision(
                decision="skipped",
                reason="no_inferred_pairs",
                source=source,
                detail=snapshot.detail,
                before=before,
                after=observed,
                inferred=inferred,
            )
            self._debug_decision(decision)
            return CorrectionObservationResult(decisions=(decision,))
        result = self._record_new_evidence(pending, inferred)
        if result.confirmed:
            decision_name = "learned"
        elif result.candidates:
            decision_name = "candidate"
        else:
            decision_name = "skipped"
        reason = "confirmed" if result.confirmed else "candidate" if result.candidates else "duplicate_observation"
        decision = CorrectionCaptureDecision(
            decision=decision_name,
            reason=reason,
            source=source,
            detail=snapshot.detail,
            before=before,
            after=observed,
            inferred=inferred,
        )
        self._debug_decision(decision)
        return CorrectionObservationResult(
            candidates=result.candidates,
            confirmed=result.confirmed,
            decisions=(decision,),
        )

    def _maybe_read_screen_snapshot(
        self,
        pending: _PendingCorrectionObservation,
        snapshot: CorrectionTextSnapshot,
    ) -> CorrectionTextSnapshot:
        if self._read_screen_text is None:
            return snapshot
        if not _should_try_screen_ocr(
            pending,
            snapshot,
            now=self._clock(),
            after_edit_seconds=self._screen_ocr_after_edit_seconds,
        ):
            return snapshot
        try:
            screen_snapshot = _coerce_snapshot(self._read_screen_text(pending.text))
        except Exception as e:
            print(f"[correction] 屏幕 OCR 读取失败: {e}")
            return snapshot
        if not screen_snapshot.text:
            self._debug_log(
                "屏幕 OCR 无文本 "
                f"source={screen_snapshot.source} detail={screen_snapshot.detail!r}"
            )
            return snapshot
        if _screen_ocr_snapshot_is_self_ui(screen_snapshot):
            self._debug_log("屏幕 OCR 已跳过：当前是 Voice Keyboard 自己的窗口")
            return snapshot
        if not _screen_ocr_snapshot_is_relevant(pending.text, screen_snapshot.text):
            self._debug_log(
                "屏幕 OCR 已跳过：与待学习片段重叠不足 "
                f"source={screen_snapshot.source} text={_preview(screen_snapshot.text)!r}"
            )
            return snapshot
        return screen_snapshot

    def _record_new_evidence(
        self,
        pending: _PendingCorrectionObservation,
        inferred: tuple[InferredCorrection, ...],
    ) -> CorrectionObservationResult:
        candidates: list[LearnedCorrection] = []
        confirmed: list[LearnedCorrection] = []
        for correction in inferred:
            key = (correction.wrong, correction.correct)
            previous = pending.recorded_evidence.get(key, 0)
            delta = correction.evidence_count - previous
            if delta <= 0:
                continue
            learned = self._memory.learn(
                correction.wrong,
                correction.correct,
                evidence_count=delta,
            )
            if learned is None:
                continue
            pending.recorded_evidence[key] = max(previous, correction.evidence_count)
            if learned.newly_confirmed:
                confirmed.append(learned)
            else:
                candidates.append(learned)
        return CorrectionObservationResult(
            candidates=tuple(candidates),
            confirmed=tuple(confirmed),
        )

    def _debug_decision(self, decision: CorrectionCaptureDecision) -> None:
        if not self._debug:
            return None
        inferred = ", ".join(
            f"{item.wrong}->{item.correct}x{item.evidence_count}"
            for item in decision.inferred
        )
        inferred_part = f" inferred={inferred}" if inferred else ""
        before_part = f" before={_preview(decision.before)!r}" if decision.before else ""
        after_part = f" after={_preview(decision.after)!r}" if decision.after else ""
        detail_part = f" detail={decision.detail!r}" if decision.detail else ""
        print(
            "[correction-capture] "
            f"decision={decision.decision} reason={decision.reason} "
            f"source={decision.source}"
            f"{detail_part}{before_part}{after_part}{inferred_part}"
        )

    def _remove_pending(self, pending: _PendingCorrectionObservation) -> None:
        self._pending = deque(
            (item for item in self._pending if item != pending),
            maxlen=self._max_pending,
        )

    def _debug_log(self, message: str) -> None:
        if self._debug:
            print(f"[correction] {message}")


class CorrectionObservationScheduler:
    def __init__(
        self,
        tracker: CorrectionLearningTracker,
        on_confirmed: Callable[[LearnedCorrection], None],
        *,
        delays: tuple[float, ...] = (2.0, 6.0, 15.0, 30.0),
        edit_delays: tuple[float, ...] | None = None,
    ):
        self._tracker = tracker
        self._on_confirmed = on_confirmed
        self._delays = tuple(float(delay) for delay in delays if float(delay) > 0)
        self._edit_delays = tuple(
            float(delay)
            for delay in (edit_delays or _with_final_observe_delay((0.8, 2.0, 5.0), max(self._delays or (30.0,))))
            if float(delay) > 0
        )
        self._lock = threading.Lock()
        self._timers: list[threading.Timer] = []

    @classmethod
    def from_config(
        cls,
        cfg: dict | None,
        tracker: CorrectionLearningTracker,
        on_confirmed: Callable[[LearnedCorrection], None],
    ) -> "CorrectionObservationScheduler":
        cfg = cfg or {}
        window_seconds = float(cfg.get("observe_window_seconds", 30.0) or 30.0)
        raw_delays = cfg.get("observe_delays")
        if isinstance(raw_delays, list):
            delays = _with_final_observe_delay(_float_tuple(raw_delays), window_seconds)
        else:
            delays = (2.0, 6.0, 15.0, window_seconds)
        edit_delays = _with_final_observe_delay((0.8, 2.0, 5.0), window_seconds)
        return cls(tracker, on_confirmed, delays=delays, edit_delays=edit_delays)

    def schedule(self) -> None:
        self._schedule_delays(self._delays)

    def schedule_after_edit(self) -> None:
        self._schedule_delays(self._edit_delays)

    def _schedule_delays(self, delays: tuple[float, ...]) -> None:
        self.stop()
        timers: list[threading.Timer] = []
        for delay in delays:
            timer = threading.Timer(delay, self._observe)
            timer.daemon = True
            timers.append(timer)
        with self._lock:
            self._timers = timers
        for timer in timers:
            timer.start()

    def stop(self) -> None:
        with self._lock:
            timers = self._timers
            self._timers = []
        for timer in timers:
            timer.cancel()

    def _observe(self) -> None:
        result = self._tracker.observe_current_text()
        for correction in result.confirmed:
            self._on_confirmed(correction)


def infer_correction_pairs(before: str, after: str) -> tuple[InferredCorrection, ...]:
    before = str(before or "").strip()
    after = _best_after_segment(before, str(after or "").strip())
    if not before or not after or before == after:
        return ()
    if len(before) > 240 or len(after) > 320:
        return ()
    if not (_CJK_RE.search(before) and _CJK_RE.search(after)):
        return ()

    changes = _replacement_changes(before, after)
    if not changes:
        return ()

    counts: dict[tuple[str, str], int] = {}
    for start, end, replacement in changes:
        for wrong, correct in set(_candidate_terms(before, start, end, replacement)):
            counts[(wrong, correct)] = counts.get((wrong, correct), 0) + 1
    if not counts:
        return ()

    selected = _select_correction_counts(counts)
    return tuple(
        InferredCorrection(wrong, correct, count)
        for (wrong, correct), count in sorted(
            selected.items(),
            key=lambda item: (-item[1], -len(item[0][0]), item[0][0]),
        )
    )


def _select_correction_counts(
    counts: dict[tuple[str, str], int]
) -> dict[tuple[str, str], int]:
    repeated = {
        pair: count
        for pair, count in counts.items()
        if count >= 2
    }
    grouped: dict[tuple[str, str], int] = {}
    by_correct: dict[str, dict[str, int]] = {}
    for (wrong, correct), count in counts.items():
        if not _one_char_replacement(wrong, correct):
            continue
        by_correct.setdefault(correct, {})[wrong] = count

    for correct, wrong_counts in by_correct.items():
        total = sum(wrong_counts.values())
        if total < 2:
            continue
        for wrong, count in wrong_counts.items():
            grouped[(wrong, correct)] = max(count, total)

    selected = dict(repeated)
    for pair, count in grouped.items():
        selected[pair] = max(selected.get(pair, 0), count)
    if selected:
        return _filter_subsumed_correction_counts(selected)

    return dict([max(
        counts.items(),
        key=lambda item: (item[1], len(item[0][0]), len(item[0][1])),
    )])


def _filter_subsumed_correction_counts(
    counts: dict[tuple[str, str], int],
) -> dict[tuple[str, str], int]:
    selected = dict(counts)
    items = list(counts.items())
    for (wrong, correct), count in items:
        for (long_wrong, long_correct), long_count in items:
            if (wrong, correct) == (long_wrong, long_correct):
                continue
            if long_count < count:
                continue
            if len(long_wrong) <= len(wrong) or len(long_correct) <= len(correct):
                continue
            start = long_wrong.find(wrong)
            if start < 0:
                continue
            if long_correct[start:start + len(correct)] != correct:
                continue
            if _allowed_prefixed_alias(
                wrong,
                correct,
                long_wrong,
                long_correct,
                start=start,
            ):
                continue
            selected.pop((wrong, correct), None)
            break
    return selected


def _allowed_prefixed_alias(
    wrong: str,
    correct: str,
    long_wrong: str,
    long_correct: str,
    *,
    start: int,
) -> bool:
    if start <= 0:
        return False
    wrong_prefix = long_wrong[:start]
    correct_prefix = long_correct[:start]
    if wrong_prefix != correct_prefix:
        return False
    if not all(char in _NICKNAME_PREFIXES for char in wrong_prefix):
        return False
    return long_wrong[start:] == wrong and long_correct[start:] == correct


def _record_committed_replacement_evidence(
    pending: _PendingCorrectionObservation,
    replacement: str,
) -> None:
    replacement = _replacement_term(replacement)
    if not replacement or len(replacement) != 1 or not _CJK_RE.search(replacement):
        return
    context = pending.last_deleted_context or pending.text
    context_index = pending.last_deleted_context_index
    for wrong, correct in _event_replacement_candidates(
        context,
        replacement,
        context_index=context_index,
        deleted_text=pending.last_deleted_text,
    ):
        key = (wrong, correct)
        pending.committed_replacement_evidence[key] = (
            pending.committed_replacement_evidence.get(key, 0) + 1
        )


def _record_pending_deletion(
    pending: _PendingCorrectionObservation,
    start: int,
    end: int,
) -> None:
    text = pending.shadow_text
    deleted = text[start:end]
    context_start = max(0, start - 2)
    context_end = min(len(text), end + 2)
    pending.last_deleted_text = deleted
    pending.last_deleted_context = text[context_start:context_end]
    pending.last_deleted_context_index = max(0, start - context_start)


def _event_replacement_candidates(
    text: str,
    replacement: str,
    *,
    context_index: int | None = None,
    deleted_text: str = "",
) -> Iterable[tuple[str, str]]:
    text = str(text or "")
    replacement = _replacement_term(replacement)
    if not text or len(replacement) != 1 or not _CJK_RE.search(replacement):
        return
    emitted: set[tuple[str, str]] = set()
    indexes: Iterable[int]
    if context_index is not None:
        indexes = (max(0, min(int(context_index), len(text) - 1)),)
    else:
        indexes = range(len(text))
    for index in indexes:
        char = text[index]
        if deleted_text and char != deleted_text:
            continue
        if char == replacement or not _CJK_RE.search(char):
            continue
        max_right = min(2, len(text) - index - 1)
        for left in (1, 2):
            start = index - left
            if start < 0:
                continue
            for right in range(0, max_right + 1):
                suffix = text[index + 1:index + 1 + right]
                wrong = _clean_term(text[start:index + 1] + suffix)
                correct = _clean_term(text[start:index] + replacement + suffix)
                if _valid_pair(wrong, correct) and (wrong, correct) not in emitted:
                    emitted.add((wrong, correct))
                    yield wrong, correct


def _committed_replacement_inferred(
    pending: _PendingCorrectionObservation,
) -> tuple[InferredCorrection, ...]:
    return tuple(
        InferredCorrection(wrong, correct, count)
        for (wrong, correct), count in sorted(
            pending.committed_replacement_evidence.items(),
            key=lambda item: (-item[1], -len(item[0][0]), item[0][0]),
        )
    )


def _merge_inferred_corrections(
    *groups: tuple[InferredCorrection, ...],
) -> tuple[InferredCorrection, ...]:
    counts: dict[tuple[str, str], int] = {}
    for group in groups:
        for item in group:
            key = (item.wrong, item.correct)
            counts[key] = max(counts.get(key, 0), item.evidence_count)
    counts = _filter_subsumed_correction_counts(counts)
    return tuple(
        InferredCorrection(wrong, correct, count)
        for (wrong, correct), count in sorted(
            counts.items(),
            key=lambda item: (-item[1], -len(item[0][0]), item[0][0]),
        )
    )


def _coerce_snapshot(value: str | CorrectionTextSnapshot | None) -> CorrectionTextSnapshot:
    if isinstance(value, CorrectionTextSnapshot):
        return value
    return CorrectionTextSnapshot(str(value or ""), source="legacy")


def _should_try_screen_ocr(
    pending: _PendingCorrectionObservation,
    snapshot: CorrectionTextSnapshot,
    *,
    now: float,
    after_edit_seconds: float,
) -> bool:
    if not pending.shadow_changed:
        return False
    if not pending.keyboard_edit_seen:
        return False
    if now - pending.inserted_at < after_edit_seconds:
        return False
    current = str(snapshot.text or "")
    if pending.awaiting_ime_commit:
        return True
    if not current:
        return True
    if snapshot.source == "tracked_segment":
        return True
    if pending.text in current:
        return True
    return _looks_like_incomplete_ime_edit(pending.text, current)


def _screen_ocr_snapshot_is_relevant(before: str, text: str) -> bool:
    before = str(before or "").strip()
    text = str(text or "").strip()
    if not before or not text:
        return False
    segment = _best_after_segment(before, text)
    if infer_correction_pairs(before, segment):
        return True
    if before in text:
        return True
    ratio = difflib.SequenceMatcher(a=before, b=segment, autojunk=False).ratio()
    if ratio >= 0.45:
        return True
    before_terms = _cjk_terms(before)
    text_terms = _cjk_terms(segment)
    if not before_terms or not text_terms:
        return False
    return bool(before_terms & text_terms)


def _screen_ocr_snapshot_is_self_ui(snapshot: CorrectionTextSnapshot) -> bool:
    text = str(snapshot.text or "")
    if "Voice Keyboard" not in text:
        return False
    markers = ("设置", "快捷键", "历史", "词典", "输入诊断", "权限")
    return sum(1 for marker in markers if marker in text) >= 2


def _cjk_terms(text: str) -> set[str]:
    terms = set()
    for token in _PUNCTUATION_SPLIT_RE.split(str(text or "")):
        token = _clean_term(token)
        if len(token) >= 2 and _CJK_TERM_RE.match(token):
            terms.add(token)
    return terms


def _choose_observed_text(
    pending: _PendingCorrectionObservation,
    before: str,
    snapshot: CorrectionTextSnapshot,
) -> tuple[str, str]:
    current = str(snapshot.text or "")
    if not pending.shadow_changed:
        return current, snapshot.source
    if not current:
        return pending.shadow_text, f"shadow+{snapshot.source}:empty_current_text"
    if before in current:
        return pending.shadow_text, f"shadow+{snapshot.source}:before_present"
    shadow_inferred = infer_correction_pairs(before, pending.shadow_text)
    current_inferred = infer_correction_pairs(before, current)
    if shadow_inferred and not current_inferred:
        return pending.shadow_text, f"shadow+{snapshot.source}:inferred"
    if pending.awaiting_ime_commit and _looks_like_incomplete_ime_edit(before, current):
        return current, snapshot.source
    return current, snapshot.source


def _looks_like_incomplete_ime_edit(before: str, observed: str) -> bool:
    before = str(before or "").strip()
    observed = _best_after_segment(before, str(observed or "").strip())
    if not before or not observed:
        return False
    if not (_CJK_RE.search(before) and _CJK_RE.search(observed)):
        return False
    if len(observed) >= len(before):
        return False
    ratio = difflib.SequenceMatcher(a=before, b=observed, autojunk=False).ratio()
    return ratio >= 0.55


def _replacement_changes(before: str, after: str) -> list[tuple[int, int, str]]:
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    changes: list[tuple[int, int, str]] = []
    for tag, a0, a1, b0, b1 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "insert":
            inserted = after[b0:b1]
            if _punctuation_only(inserted) or a0 in (0, len(before)):
                continue
            return []
        if tag == "delete":
            deleted = before[a0:a1]
            if _punctuation_only(deleted):
                continue
            return []
        wrong = before[a0:a1]
        replacement = _replacement_term(after[b0:b1])
        if not wrong or not replacement or len(wrong) > 4 or len(replacement) > 4:
            return []
        changes.append((a0, a1, replacement))
    return changes


def _candidate_terms(
    before: str,
    start: int,
    end: int,
    replacement: str,
) -> Iterable[tuple[str, str]]:
    wrong_piece = before[start:end]
    max_left = min(2, start)
    max_right = min(2, len(before) - end)
    left_lengths = range(0, max_left + 1)
    if len(wrong_piece) == 1:
        left_lengths = range(1, max_left + 1)
    for left_len in left_lengths:
        for right_len in range(0, max_right + 1):
            prefix = before[start - left_len:start]
            suffix = before[end:end + right_len]
            wrong = prefix + wrong_piece + suffix
            correct = prefix + replacement + suffix
            wrong = _clean_term(wrong)
            correct = _clean_term(correct)
            if _valid_pair(wrong, correct):
                yield wrong, correct


def _best_after_segment(before: str, after: str) -> str:
    if not before or not after or len(after) <= len(before) + 40:
        return after
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    blocks = [block for block in matcher.get_matching_blocks() if block.size > 0]
    if not blocks:
        return after[-min(len(after), len(before) + 40):]
    start = max(0, min(block.b for block in blocks) - 12)
    end = min(len(after), max(block.b + block.size for block in blocks) + 12)
    return after[start:end].strip()


def _valid_pair(wrong: str, correct: str) -> bool:
    if not wrong or not correct or wrong == correct:
        return False
    if len(wrong) < _MIN_TERM_LENGTH or len(correct) < _MIN_TERM_LENGTH:
        return False
    if len(wrong) > _MAX_TERM_LENGTH or len(correct) > _MAX_TERM_LENGTH:
        return False
    if _SPACE_RE.search(wrong) or _SPACE_RE.search(correct):
        return False
    if _punctuation_only(wrong) or _punctuation_only(correct):
        return False
    return bool(_CJK_TERM_RE.match(wrong) and _CJK_TERM_RE.match(correct))


def _looks_like_same_segment_edit(before: str, current: str) -> bool:
    before = str(before or "").strip()
    current = _best_after_segment(before, str(current or "").strip())
    if not before or not current or before == current:
        return False
    if len(current) > len(before) + 24:
        return False
    if len(current) < max(1, len(before) - 24):
        return False
    ratio = difflib.SequenceMatcher(a=before, b=current, autojunk=False).ratio()
    return ratio >= 0.55


def _one_char_replacement(wrong: str, correct: str) -> bool:
    if len(wrong) != len(correct):
        return False
    return sum(1 for left, right in zip(wrong, correct) if left != right) == 1


def _clean_term(text: str) -> str:
    return _strip_edge_punctuation(str(text or "").strip())


def _strip_edge_punctuation(text: str) -> str:
    return _EDGE_PUNCTUATION_RE.sub("", str(text or "")).strip()


def _replacement_term(text: str) -> str:
    cleaned = _strip_edge_punctuation(text)
    parts = [part for part in _PUNCTUATION_SPLIT_RE.split(cleaned) if part]
    return parts[0] if parts else cleaned


def _punctuation_only(text: str) -> bool:
    return bool(_PUNCTUATION_ONLY_RE.match(str(text or "")))


def _rows(value) -> list[dict]:
    return [row for row in value or [] if isinstance(row, dict)]


def _preview(text: str, limit: int = 80) -> str:
    value = str(text or "").replace("\n", "\\n")
    suffix = "..." if len(value) > limit else ""
    return value[:limit] + suffix


def _float_tuple(values: list) -> tuple[float, ...]:
    out = []
    for value in values:
        try:
            out.append(float(value))
        except (TypeError, ValueError):
            continue
    return tuple(out)


def _with_final_observe_delay(
    delays: tuple[float, ...],
    observe_window_seconds: float,
) -> tuple[float, ...]:
    window = max(1.0, float(observe_window_seconds or 30.0))
    values = [delay for delay in delays if delay > 0]
    if not values or max(values) < window - 0.25:
        values.append(window)
    return tuple(sorted(set(values)))


def _key_action(key: object) -> str:
    name = _key_name(key)
    aliases = {
        "backspace": "backspace",
        "delete": "delete",
        "delete_forward": "delete",
        "left": "left",
        "right": "right",
        "home": "home",
        "end": "end",
    }
    return aliases.get(name, "")


def _key_text(key: object) -> str:
    char = getattr(key, "char", None)
    if isinstance(char, str) and len(char) == 1 and _printable_key_text(char):
        return char
    name = _key_name(key)
    if name == "space":
        return " "
    if name == "enter":
        return "\n"
    return ""


def _key_name(key: object) -> str:
    name = getattr(key, "name", None)
    if isinstance(name, str):
        return name.lower()
    text = str(key)
    if text.startswith("Key."):
        return text[4:].lower()
    return ""


def _printable_key_text(char: str) -> bool:
    if not char or char in ("\x7f", "\b"):
        return False
    if unicodedata.category(char).startswith("C"):
        return False
    return char.isprintable()


def _ime_composition_key_text(text: str) -> bool:
    return bool(len(text) == 1 and text.isascii() and text.isalnum())


def _entry_from_row(row: dict) -> CorrectionEntry | None:
    wrong = _clean_term(row.get("wrong", ""))
    correct = _clean_term(row.get("correct", ""))
    if not _valid_pair(wrong, correct):
        return None
    try:
        count = int(row.get("count", 1) or 1)
    except (TypeError, ValueError):
        count = 1
    try:
        updated_at = float(row.get("updated_at", 0.0) or 0.0)
    except (TypeError, ValueError):
        updated_at = 0.0
    return CorrectionEntry(
        wrong=wrong,
        correct=correct,
        count=max(1, count),
        source=str(row.get("source", "manual_edit") or "manual_edit"),
        updated_at=updated_at,
    )


def _entry_to_row(entry: CorrectionEntry) -> dict:
    return {
        "wrong": entry.wrong,
        "correct": entry.correct,
        "count": entry.count,
        "source": entry.source,
        "updated_at": entry.updated_at,
    }
