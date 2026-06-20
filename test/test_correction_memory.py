import json
import tempfile
import threading
import unittest
from types import SimpleNamespace
from pathlib import Path

from agent.correction_memory import (
    CorrectionTextSnapshot,
    CorrectionLearningTracker,
    CorrectionMemory,
    CorrectionObservationScheduler,
    infer_correction_pairs,
)


class CorrectionMemoryTests(unittest.TestCase):
    def test_infers_repeated_name_correction_from_manual_edit(self):
        corrections = infer_correction_pairs("王琦王琦小王琦", "王齐，王齐，小王齐")

        self.assertEqual(
            [(item.wrong, item.correct, item.evidence_count) for item in corrections],
            [("王琦", "王齐", 3)],
        )

    def test_does_not_learn_punctuation_only_change(self):
        self.assertEqual(
            infer_correction_pairs("王琦王琦小王琦", "王琦，王琦，小王琦"),
            (),
        )

    def test_does_not_store_more_than_five_character_terms(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = CorrectionMemory(Path(tmp) / "correction.json", confirm_threshold=1)

            learned = memory.learn("中华人民共和国", "中华人民共和果")

            self.assertIsNone(learned)
            self.assertEqual(memory.entries, ())

    def test_does_not_learn_english_word_corrections(self):
        self.assertEqual(
            infer_correction_pairs("codex codex", "codecs codecs"),
            (),
        )

    def test_does_not_infer_mixed_pinyin_or_symbol_candidate(self):
        self.assertEqual(
            infer_correction_pairs("宋海丽，宋海丽，宋海丽", "宋海丽，宋海丽，宋海cao"),
            (),
        )
        self.assertEqual(
            infer_correction_pairs("宋海丽，宋海丽，宋海丽", "宋海丽，宋海丽，宋海]cao3"),
            (),
        )

    def test_allows_input_environment_context_around_edited_segment(self):
        corrections = infer_correction_pairs(
            "王琦王琦小王琦",
            "今天：王齐，王齐，小王齐，谢谢",
        )

        self.assertEqual(
            [(item.wrong, item.correct, item.evidence_count) for item in corrections],
            [("王琦", "王齐", 3)],
        )

    def test_learns_after_threshold_and_applies_confirmed_dictionary(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = CorrectionMemory(Path(tmp) / "correction.json", confirm_threshold=2)

            first = memory.learn("王琦", "王齐")
            second = memory.learn("王琦", "王齐")

            self.assertIsNotNone(first)
            self.assertFalse(first.newly_confirmed)
            self.assertIsNotNone(second)
            self.assertTrue(second.newly_confirmed)
            self.assertEqual(memory.apply("王琦今天来了"), "王齐今天来了")

    def test_exposes_candidates_path_and_threshold_for_dictionary_ui(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "correction.json"
            memory = CorrectionMemory(path, confirm_threshold=3)

            memory.learn("李长寿", "李长守")

            self.assertEqual(memory.path, path)
            self.assertEqual(memory.confirm_threshold, 3)
            self.assertEqual(memory.entries, ())
            self.assertEqual(
                [(item.wrong, item.correct, item.count) for item in memory.candidates],
                [("李长寿", "李长守", 1)],
            )

    def test_deletes_confirmed_dictionary_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "correction.json"
            memory = CorrectionMemory(path, confirm_threshold=1)
            memory.learn("王之行", "王知行")

            self.assertTrue(memory.delete_entry("王之行"))
            self.assertFalse(memory.delete_entry("王之行"))
            self.assertEqual(memory.apply("王之行来了"), "王之行来了")

            reloaded = CorrectionMemory(path, confirm_threshold=1)
            self.assertEqual(reloaded.entries, ())

    def test_deletes_candidate_dictionary_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "correction.json"
            memory = CorrectionMemory(path, confirm_threshold=2)
            memory.learn("王之行", "王知行")

            self.assertTrue(memory.delete_candidate("王之行", "王知行"))
            self.assertFalse(memory.delete_candidate("王之行", "王知行"))
            self.assertEqual(memory.candidates, ())

            reloaded = CorrectionMemory(path, confirm_threshold=2)
            self.assertEqual(reloaded.candidates, ())

    def test_repeated_evidence_from_single_segment_can_confirm(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = CorrectionMemory(Path(tmp) / "correction.json", confirm_threshold=2)

            result = memory.record_observation("王琦王琦小王琦", "王齐，王齐，小王齐")

            self.assertEqual(
                [(item.wrong, item.correct, item.newly_confirmed) for item in result.confirmed],
                [("王琦", "王齐", True)],
            )
            self.assertEqual(memory.apply("小王琦"), "小王齐")

    def test_prefers_full_name_over_inner_two_character_alias(self):
        corrections = infer_correction_pairs(
            "胡任袁，胡任袁，胡任袁",
            "胡任远，胡任远，胡任远",
        )

        self.assertEqual(
            [(item.wrong, item.correct, item.evidence_count) for item in corrections],
            [("胡任袁", "胡任远", 3)],
        )

    def test_infers_repeated_three_character_name_correction(self):
        corrections = infer_correction_pairs(
            "胡人远，胡人远，胡人远",
            "胡任远，胡任远，胡任远",
        )

        self.assertEqual(
            [(item.wrong, item.correct, item.evidence_count) for item in corrections],
            [("胡人远", "胡任远", 3)],
        )

    def test_keeps_nickname_alias_when_full_prefixed_name_is_seen(self):
        corrections = infer_correction_pairs("小王琦，小王琦", "小王齐，小王齐")

        self.assertEqual(
            [(item.wrong, item.correct, item.evidence_count) for item in corrections],
            [("小王琦", "小王齐", 2), ("王琦", "王齐", 2)],
        )

    def test_tracker_observes_pending_dictation_against_current_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            current = {"text": "王齐，王齐，小王齐"}
            memory = CorrectionMemory(Path(tmp) / "correction.json", confirm_threshold=2)
            tracker = CorrectionLearningTracker(memory, lambda: current["text"])

            tracker.remember_inserted("王琦王琦小王琦")
            result = tracker.observe_current_text()

            self.assertEqual(
                [(item.wrong, item.correct) for item in result.confirmed],
                [("王琦", "王齐")],
            )

    def test_tracker_keeps_earlier_pending_dictation_when_another_utterance_arrives(self):
        with tempfile.TemporaryDirectory() as tmp:
            current = {"text": "现在已经好了，王齐王齐小王齐现在"}
            memory = CorrectionMemory(Path(tmp) / "correction.json", confirm_threshold=2)
            tracker = CorrectionLearningTracker(memory, lambda: current["text"])

            tracker.remember_inserted("现在已经好了，王琦王琪小王琦")
            tracker.remember_inserted("现在")
            result = tracker.observe_current_text()

            self.assertEqual(
                [(item.wrong, item.correct) for item in result.confirmed],
                [("王琦", "王齐"), ("王琪", "王齐")],
            )

    def test_tracker_reconstructs_manual_correction_from_key_events_when_caret_text_is_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            current = {"text": "王琦"}
            memory = CorrectionMemory(Path(tmp) / "correction.json", confirm_threshold=1)
            tracker = CorrectionLearningTracker(memory, lambda: current["text"])

            tracker.remember_inserted("王琦")
            tracker.record_key_press(SimpleNamespace(name="backspace"))
            tracker.record_key_press(SimpleNamespace(char="齐"))
            result = tracker.observe_current_text()

            self.assertEqual(
                [(item.wrong, item.correct) for item in result.confirmed],
                [("王琦", "王齐")],
            )

    def test_tracker_reports_capture_source_and_decision_for_observed_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = CorrectionMemory(Path(tmp) / "correction.json", confirm_threshold=2)
            tracker = CorrectionLearningTracker(
                memory,
                lambda: CorrectionTextSnapshot("文净，文净，文净", source="AXValue"),
            )

            tracker.remember_inserted("文静，文静，文静")
            result = tracker.observe_current_text()

            self.assertEqual(
                [(item.wrong, item.correct) for item in result.confirmed],
                [("文静", "文净")],
            )
            self.assertEqual(result.decisions[-1].decision, "learned")
            self.assertEqual(result.decisions[-1].reason, "confirmed")
            self.assertEqual(result.decisions[-1].source, "AXValue")

    def test_tracker_keeps_pending_after_candidate_to_accumulate_more_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            current = {"text": "文静，文静，文净"}
            memory = CorrectionMemory(Path(tmp) / "correction.json", confirm_threshold=2)
            tracker = CorrectionLearningTracker(
                memory,
                lambda: CorrectionTextSnapshot(current["text"], source="AXValue"),
            )

            tracker.remember_inserted("文静，文静，文静")
            first = tracker.observe_current_text()
            current["text"] = "文静，文净，文净"
            second = tracker.observe_current_text()

            self.assertEqual(
                [(item.wrong, item.correct) for item in first.candidates],
                [("文静", "文净")],
            )
            self.assertEqual(
                [(item.wrong, item.correct) for item in second.confirmed],
                [("文静", "文净")],
            )
            self.assertEqual(memory.apply("文静"), "文净")

    def test_tracker_does_not_count_same_candidate_observation_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            current = {"text": "文静，文静，文净"}
            memory = CorrectionMemory(Path(tmp) / "correction.json", confirm_threshold=2)
            tracker = CorrectionLearningTracker(
                memory,
                lambda: CorrectionTextSnapshot(current["text"], source="AXValue"),
            )

            tracker.remember_inserted("文静，文静，文静")
            tracker.observe_current_text()
            duplicate = tracker.observe_current_text()

            self.assertEqual(duplicate.candidates, ())
            self.assertEqual(duplicate.confirmed, ())
            self.assertEqual(memory.apply("文静"), "文静")

    def test_tracker_uses_shadow_when_accessibility_text_is_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = CorrectionMemory(Path(tmp) / "correction.json", confirm_threshold=1)
            tracker = CorrectionLearningTracker(
                memory,
                lambda: CorrectionTextSnapshot("文静", source="AXValue"),
            )

            tracker.remember_inserted("文静")
            tracker.record_key_press(SimpleNamespace(name="backspace"))
            tracker.record_key_press(SimpleNamespace(char="净"))
            result = tracker.observe_current_text()

            self.assertEqual(
                [(item.wrong, item.correct) for item in result.confirmed],
                [("文静", "文净")],
            )
            self.assertTrue(result.decisions[-1].source.startswith("shadow+AXValue"))

    def test_tracker_uses_shadow_when_accessibility_text_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = CorrectionMemory(Path(tmp) / "correction.json", confirm_threshold=1)
            tracker = CorrectionLearningTracker(
                memory,
                lambda: CorrectionTextSnapshot("", source="unsupported", detail="AXWindowScan:no"),
            )

            tracker.remember_inserted("文静")
            tracker.record_key_press(SimpleNamespace(name="backspace"))
            tracker.record_key_press(SimpleNamespace(char="净"))
            result = tracker.observe_current_text()

            self.assertEqual(
                [(item.wrong, item.correct) for item in result.confirmed],
                [("文静", "文净")],
            )
            self.assertEqual(
                result.decisions[-1].source,
                "shadow+unsupported:empty_current_text",
            )

    def test_tracker_ignores_screen_ocr_from_voice_keyboard_own_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = {"value": 100.0}
            memory = CorrectionMemory(Path(tmp) / "correction.json", confirm_threshold=1)
            tracker = CorrectionLearningTracker(
                memory,
                lambda: CorrectionTextSnapshot("", source="unsupported", detail="AXWindowScan:no"),
                read_screen_text=lambda reference: CorrectionTextSnapshot(
                    "Voice Keyboard\n设置\n快捷键\n历史\n词典| 输入诊断\n"
                    "已确认 13条\n胡日远 胡任远",
                    source="ocr_window",
                    detail="app=python",
                ),
                clock=lambda: now["value"],
            )

            tracker.remember_inserted("你知道胡任远是谁吗？")
            tracker.record_key_press(SimpleNamespace(name="backspace"))
            for char in "ma":
                tracker.record_key_press(SimpleNamespace(char=char))
            now["value"] += 1.0
            result = tracker.observe_current_text()

            self.assertEqual(result.confirmed, ())
            self.assertEqual(result.candidates, ())
            self.assertEqual(memory.candidates, ())

    def test_tracker_waits_for_ime_when_only_shadow_deletion_is_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = CorrectionMemory(Path(tmp) / "correction.json", confirm_threshold=1)
            tracker = CorrectionLearningTracker(
                memory,
                lambda: CorrectionTextSnapshot("", source="unsupported", detail="AXWindowScan:no"),
            )

            tracker.remember_inserted("文静")
            tracker.record_key_press(SimpleNamespace(name="backspace"))
            for char in "jing":
                tracker.record_key_press(SimpleNamespace(char=char))
            result = tracker.observe_current_text()

            self.assertEqual(result.confirmed, ())
            self.assertEqual(result.decisions[-1].decision, "waiting")
            self.assertEqual(result.decisions[-1].reason, "awaiting_ime_commit")

    def test_tracker_does_not_record_pinyin_as_shadow_replacement_when_ime_is_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = CorrectionMemory(Path(tmp) / "correction.json", confirm_threshold=1)
            tracker = CorrectionLearningTracker(
                memory,
                lambda: CorrectionTextSnapshot("", source="unsupported", detail="AXWindowScan:no"),
            )

            tracker.remember_inserted("宋海丽，宋海丽，宋海丽")
            tracker.record_key_press(SimpleNamespace(name="backspace"))
            for char in "cao3]cli":
                tracker.record_key_press(SimpleNamespace(char=char))
            result = tracker.observe_current_text()

            self.assertEqual(result.confirmed, ())
            self.assertEqual(result.candidates, ())
            self.assertEqual(memory.candidates, ())
            self.assertEqual(result.decisions[-1].decision, "waiting")

    def test_tracker_learns_from_repeated_committed_replacements_without_text_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = CorrectionMemory(Path(tmp) / "correction.json", confirm_threshold=2)
            tracker = CorrectionLearningTracker(
                memory,
                lambda: CorrectionTextSnapshot("", source="unsupported", detail="AXWindowScan:no"),
            )

            tracker.remember_inserted("文静，文静")
            tracker.record_key_press(SimpleNamespace(name="backspace"))
            tracker.record_committed_text("净")
            first = tracker.observe_current_text()
            for _ in range(3):
                tracker.record_key_press(SimpleNamespace(name="left"))
            tracker.record_key_press(SimpleNamespace(name="backspace"))
            tracker.record_committed_text("净")
            second = tracker.observe_current_text()

            self.assertEqual(first.confirmed, ())
            self.assertEqual(
                [(item.wrong, item.correct) for item in second.confirmed],
                [("文静", "文净")],
            )

    def test_tracker_prefers_full_three_character_name_from_committed_middle_replacements(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = CorrectionMemory(Path(tmp) / "correction.json", confirm_threshold=2)
            tracker = CorrectionLearningTracker(
                memory,
                lambda: CorrectionTextSnapshot("", source="unsupported", detail="AXWindowScan:no"),
            )

            tracker.remember_inserted("胡人远，胡人远")
            tracker.record_key_press(SimpleNamespace(name="left"))
            tracker.record_key_press(SimpleNamespace(name="backspace"))
            tracker.record_committed_text("任")
            tracker.record_key_press(SimpleNamespace(name="home"))
            tracker.record_key_press(SimpleNamespace(name="right"))
            tracker.record_key_press(SimpleNamespace(name="right"))
            tracker.record_key_press(SimpleNamespace(name="backspace"))
            tracker.record_committed_text("任")
            result = tracker.observe_current_text()

            self.assertEqual(
                [(item.wrong, item.correct) for item in result.confirmed],
                [("胡人远", "胡任远")],
            )
            self.assertEqual(memory.apply("胡人远"), "胡任远")
            self.assertEqual(memory.apply("胡人"), "胡人")

    def test_tracker_waits_for_ime_when_accessibility_text_is_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = CorrectionMemory(Path(tmp) / "correction.json", confirm_threshold=1)
            tracker = CorrectionLearningTracker(
                memory,
                lambda: CorrectionTextSnapshot("文静，文静，文", source="AXValue"),
            )

            tracker.remember_inserted("文静，文静，文静")
            tracker.record_key_press(SimpleNamespace(name="backspace"))
            for char in "jing":
                tracker.record_key_press(SimpleNamespace(char=char))
            tracker.record_key_press(SimpleNamespace(name="space"))
            result = tracker.observe_current_text()

            self.assertEqual(result.confirmed, ())
            self.assertEqual(result.decisions[-1].decision, "waiting")
            self.assertEqual(result.decisions[-1].reason, "awaiting_ime_commit")

    def test_tracker_uses_screen_ocr_when_ime_commit_is_not_observable(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = {"value": 100.0}
            ocr_calls = []
            memory = CorrectionMemory(Path(tmp) / "correction.json", confirm_threshold=1)
            tracker = CorrectionLearningTracker(
                memory,
                lambda: CorrectionTextSnapshot("", source="unsupported", detail="AXWindowScan:no"),
                read_screen_text=lambda reference: (
                    ocr_calls.append(reference)
                    or CorrectionTextSnapshot(
                        "李立夫，李立夫，李立夫",
                        source="ocr_window",
                        detail="VisionOCR:ok(lines=1)",
                    )
                ),
                clock=lambda: now["value"],
            )

            tracker.remember_inserted("李丽夫，李丽夫，李丽夫")
            tracker.record_key_press(SimpleNamespace(name="backspace"))
            for char in "fu":
                tracker.record_key_press(SimpleNamespace(char=char))
            now["value"] += 1.0
            result = tracker.observe_current_text()

            self.assertEqual(ocr_calls, ["李丽夫，李丽夫，李丽夫"])
            self.assertEqual(
                [(item.wrong, item.correct) for item in result.confirmed],
                [("李丽夫", "李立夫")],
            )
            self.assertEqual(result.decisions[-1].source, "ocr_window")

    def test_tracker_uses_screen_ocr_for_repeated_three_character_name_when_ime_commit_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = {"value": 100.0}
            memory = CorrectionMemory(Path(tmp) / "correction.json", confirm_threshold=1)
            tracker = CorrectionLearningTracker(
                memory,
                lambda: CorrectionTextSnapshot("", source="unsupported", detail="AXWindowScan:no"),
                read_screen_text=lambda reference: CorrectionTextSnapshot(
                    "胡任远，胡任远，胡任远",
                    source="ocr_screen_below_window",
                    detail="VisionOCRBelowWindow:ok(lines=1)",
                ),
                clock=lambda: now["value"],
            )

            tracker.remember_inserted("无人远，无人远，无人远")
            tracker.record_key_press(SimpleNamespace(name="backspace"))
            for char in "hu ":
                tracker.record_key_press(SimpleNamespace(char=char))
            now["value"] += 1.0
            result = tracker.observe_current_text()

            self.assertEqual(
                [(item.wrong, item.correct) for item in result.confirmed],
                [("无人远", "胡任远")],
            )
            self.assertEqual(result.decisions[-1].source, "ocr_screen_below_window")

    def test_tracker_waits_before_trying_screen_ocr_after_recent_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = {"value": 100.0}
            ocr_calls = []
            memory = CorrectionMemory(Path(tmp) / "correction.json", confirm_threshold=1)
            tracker = CorrectionLearningTracker(
                memory,
                lambda: CorrectionTextSnapshot("", source="unsupported", detail="AXWindowScan:no"),
                read_screen_text=lambda reference: (
                    ocr_calls.append(reference)
                    or CorrectionTextSnapshot("李立夫", source="ocr_window")
                ),
                clock=lambda: now["value"],
            )

            tracker.remember_inserted("李丽夫")
            tracker.record_key_press(SimpleNamespace(name="backspace"))
            for char in "fu":
                tracker.record_key_press(SimpleNamespace(char=char))
            now["value"] += 0.2
            result = tracker.observe_current_text()

            self.assertEqual(ocr_calls, [])
            self.assertEqual(result.confirmed, ())
            self.assertEqual(result.decisions[-1].reason, "awaiting_ime_commit")

    def test_tracker_refreshes_observation_window_when_user_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = {"value": 100.0}
            current = {"text": "王琦"}
            memory = CorrectionMemory(Path(tmp) / "correction.json", confirm_threshold=1)
            tracker = CorrectionLearningTracker(
                memory,
                lambda: current["text"],
                observe_window_seconds=5,
                clock=lambda: now["value"],
            )

            tracker.remember_inserted("王琦")
            now["value"] = 104.9
            tracker.record_key_press(SimpleNamespace(name="backspace"))
            tracker.record_key_press(SimpleNamespace(char="齐"))
            now["value"] = 109.0
            result = tracker.observe_current_text()

            self.assertEqual(
                [(item.wrong, item.correct) for item in result.confirmed],
                [("王琦", "王齐")],
            )

    def test_tracker_does_not_treat_pinyin_composition_keys_as_committed_chinese(self):
        with tempfile.TemporaryDirectory() as tmp:
            current = {"text": "胡任袁"}
            memory = CorrectionMemory(Path(tmp) / "correction.json", confirm_threshold=1)
            tracker = CorrectionLearningTracker(memory, lambda: current["text"])

            tracker.remember_inserted("胡任袁")
            tracker.record_key_press(SimpleNamespace(name="backspace"))
            for char in "yuan":
                tracker.record_key_press(SimpleNamespace(char=char))
            tracker.record_key_press(SimpleNamespace(name="space"))
            result = tracker.observe_current_text()

            self.assertEqual(result.confirmed, ())
            self.assertEqual(memory.apply("胡任袁"), "胡任袁")

    def test_tracker_can_learn_ime_correction_when_real_text_becomes_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            current = {"text": "胡任远"}
            memory = CorrectionMemory(Path(tmp) / "correction.json", confirm_threshold=1)
            tracker = CorrectionLearningTracker(memory, lambda: current["text"])

            tracker.remember_inserted("胡任袁")
            tracker.record_key_press(SimpleNamespace(name="backspace"))
            for char in "yuan":
                tracker.record_key_press(SimpleNamespace(char=char))
            tracker.record_key_press(SimpleNamespace(name="space"))
            result = tracker.observe_current_text()

            self.assertEqual(
                [(item.wrong, item.correct) for item in result.confirmed],
                [("胡任袁", "胡任远")],
            )

    def test_tracker_reconstructs_ime_committed_chinese_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            current = {"text": "文静"}
            memory = CorrectionMemory(Path(tmp) / "correction.json", confirm_threshold=1)
            tracker = CorrectionLearningTracker(memory, lambda: current["text"])

            tracker.remember_inserted("文静")
            tracker.record_key_press(SimpleNamespace(name="backspace"))
            for char in "jing":
                tracker.record_key_press(SimpleNamespace(char=char))
            tracker.record_committed_text("净")
            result = tracker.observe_current_text()

            self.assertEqual(
                [(item.wrong, item.correct) for item in result.confirmed],
                [("文静", "文净")],
            )

    def test_tracker_does_not_learn_unedited_previous_dictation_from_next_utterance(self):
        with tempfile.TemporaryDirectory() as tmp:
            current = {"text": "白光宇，白光宇胡日月，胡日月，胡日月"}
            memory = CorrectionMemory(Path(tmp) / "correction.json", confirm_threshold=1)
            tracker = CorrectionLearningTracker(memory, lambda: current["text"])

            tracker.remember_inserted("白光宇，白光宇")
            tracker.remember_inserted("胡日月，胡日月，胡日月")
            result = tracker.observe_current_text()

            self.assertEqual(result.confirmed, ())
            self.assertEqual(memory.apply("白光宇"), "白光宇")

    def test_tracker_debug_mode_keeps_same_observation_behavior(self):
        with tempfile.TemporaryDirectory() as tmp:
            current = {"text": "小王齐，小王齐"}
            memory = CorrectionMemory(Path(tmp) / "correction.json", confirm_threshold=2)
            tracker = CorrectionLearningTracker(
                memory,
                lambda: current["text"],
                debug=True,
            )

            tracker.remember_inserted("小王琦，小王琦")
            result = tracker.observe_current_text()

            self.assertEqual(
                [(item.wrong, item.correct) for item in result.confirmed],
                [("小王琦", "小王齐"), ("王琦", "王齐")],
            )

    def test_scheduler_reports_confirmed_corrections(self):
        with tempfile.TemporaryDirectory() as tmp:
            current = {"text": "王齐，王齐，小王齐"}
            memory = CorrectionMemory(Path(tmp) / "correction.json", confirm_threshold=2)
            tracker = CorrectionLearningTracker(memory, lambda: current["text"])
            observed = []
            done = threading.Event()
            scheduler = CorrectionObservationScheduler(
                tracker,
                lambda correction: (observed.append(correction), done.set()),
                delays=(0.01,),
            )

            tracker.remember_inserted("王琦王琦小王琦")
            scheduler.schedule()

            self.assertTrue(done.wait(1.0))
            scheduler.stop()
            self.assertEqual([(item.wrong, item.correct) for item in observed], [("王琦", "王齐")])

    def test_scheduler_adds_final_observation_at_configured_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = CorrectionMemory(Path(tmp) / "correction.json")
            tracker = CorrectionLearningTracker(memory, lambda: "")
            scheduler = CorrectionObservationScheduler.from_config(
                {
                    "observe_delays": [0.8, 2, 5, 12],
                    "observe_window_seconds": 30,
                },
                tracker,
                lambda correction: None,
            )

            self.assertEqual(scheduler._delays, (0.8, 2.0, 5.0, 12.0, 30.0))
            self.assertEqual(scheduler._edit_delays, (0.8, 2.0, 5.0, 30.0))

    def test_scheduler_can_observe_shortly_after_manual_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            current = {"text": "文净，文净，文净"}
            memory = CorrectionMemory(Path(tmp) / "correction.json", confirm_threshold=2)
            tracker = CorrectionLearningTracker(memory, lambda: current["text"])
            observed = []
            done = threading.Event()
            scheduler = CorrectionObservationScheduler(
                tracker,
                lambda correction: (observed.append(correction), done.set()),
                delays=(30.0,),
            )

            tracker.remember_inserted("文静，文静，文静")
            scheduler.schedule_after_edit()

            self.assertTrue(done.wait(1.5))
            scheduler.stop()
            self.assertEqual([(item.wrong, item.correct) for item in observed], [("文静", "文净")])

    def test_loads_existing_confirmed_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "correction.json"
            path.write_text(
                json.dumps({
                    "entries": [
                        {"wrong": "白光雨", "correct": "白光宇", "count": 2},
                    ],
                }, ensure_ascii=False),
                encoding="utf-8",
            )

            memory = CorrectionMemory(path)

            self.assertEqual(memory.apply("白光雨最喜欢说的话"), "白光宇最喜欢说的话")


if __name__ == "__main__":
    unittest.main()
