import json
import tempfile
import unittest
from pathlib import Path

from agent.intent_training import (
    IntentTrainingConfig,
    IntentTrainingRecorder,
    export_samples,
    load_samples,
    update_sample_review,
)


class IntentTrainingTests(unittest.TestCase):
    def test_recorder_is_disabled_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "samples.jsonl"
            recorder = IntentTrainingRecorder(IntentTrainingConfig(path=path))

            recorder.record(text="save", intent_result={"type": "chat"})

            self.assertFalse(path.exists())

    def test_recorder_writes_sanitized_sample_when_enabled(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "samples.jsonl"
            recorder = IntentTrainingRecorder(IntentTrainingConfig(
                enabled=True,
                path=path,
            ))

            recorder.record(
                text="my email is user@example.com token=abc123456789 and phone 13800138000",
                active_application="Test App",
                selected="secret selected text",
                recent_text="recent text",
                shortcuts=("保存", "发送"),
                intent_result={
                    "type": "shortcut",
                    "name": "保存",
                    "_intent_source": "local",
                    "_intent_confidence": "high",
                },
                status="ok",
                detail="done",
            )

            row = json.loads(path.read_text(encoding="utf-8").strip())
            self.assertIn("[EMAIL]", row["text"])
            self.assertIn("[SECRET]", row["text"])
            self.assertIn("[PHONE]", row["text"])
            self.assertNotIn("secret selected text", json.dumps(row, ensure_ascii=False))
            self.assertEqual(row["intent_type"], "shortcut")
            self.assertEqual(row["intent_source"], "local")
            self.assertEqual(row["shortcut_count"], 2)
            self.assertEqual(row["review_label"], "")
            self.assertEqual(row["review_note"], "")

    def test_load_samples_respects_limit_from_end(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "samples.jsonl"
            source.write_text(
                '{"text":"one"}\n{"text":"two"}\n{"text":"three"}\n',
                encoding="utf-8",
            )

            rows = load_samples(source, limit=2)

            self.assertEqual([row["text"] for row in rows], ["two", "three"])

    def test_export_samples_to_csv(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "samples.jsonl"
            target = Path(td) / "samples.csv"
            source.write_text('{"text":"save","intent_type":"shortcut"}\n', encoding="utf-8")

            exported = export_samples(source, target, fmt="csv")

            self.assertEqual(exported, target)
            self.assertIn("intent_type", target.read_text(encoding="utf-8"))

    def test_update_sample_review_rewrites_label_and_note(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "samples.jsonl"
            source.write_text(
                '{"text":"save","intent_type":"shortcut"}\n'
                '{"text":"ask","intent_type":"chat"}\n',
                encoding="utf-8",
            )

            row = update_sample_review(
                source,
                1,
                label="wrong_intent",
                note="should be shortcut token=abc123",
            )

            self.assertEqual(row["review_label"], "wrong_intent")
            self.assertIn("[SECRET]", row["review_note"])
            rows = load_samples(source, limit=0)
            self.assertEqual(rows[1]["review_label"], "wrong_intent")

    def test_update_sample_review_rejects_unknown_label(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "samples.jsonl"
            source.write_text('{"text":"save"}\n', encoding="utf-8")

            with self.assertRaises(ValueError):
                update_sample_review(source, 0, label="bad_label")


if __name__ == "__main__":
    unittest.main()
