import tempfile
import unittest
from pathlib import Path

from training_server.store import IntentTrainingStore, SampleQuery, parse_jsonl


class TrainingServerStoreTests(unittest.TestCase):
    def test_store_inserts_lists_reviews_and_counts_samples(self):
        with tempfile.TemporaryDirectory() as td:
            store = IntentTrainingStore(Path(td) / "training.db")
            batch_id = store.create_batch(source="unit-test")
            inserted = store.insert_samples(batch_id, [
                {
                    "text": "save",
                    "text_hash": "h1",
                    "intent_type": "shortcut",
                    "intent_name": "保存",
                    "intent_source": "local",
                    "intent_confidence": "high",
                    "status": "ok",
                    "corrected_intent": {"type": "shortcut", "name": "保存"},
                },
                {
                    "text": "what is this",
                    "text_hash": "h2",
                    "intent_type": "chat",
                    "intent_source": "llm",
                    "status": "ok",
                },
            ])

            self.assertEqual(inserted, 2)
            shortcuts = store.list_samples(SampleQuery(intent_type="shortcut"))
            self.assertEqual(len(shortcuts), 1)
            self.assertEqual(shortcuts[0]["corrected_intent"], {"type": "shortcut", "name": "保存"})
            reviewed = store.review_sample(
                shortcuts[0]["id"],
                label="wrong_intent",
                note="ok",
                corrected_intent={"type": "chat", "reply": "我先不执行"},
            )
            self.assertEqual(reviewed["review_label"], "wrong_intent")
            self.assertEqual(reviewed["corrected_intent"], {"type": "chat", "reply": "我先不执行"})
            stats = store.stats()
            self.assertEqual(stats["total"], 2)
            self.assertEqual(stats["by_intent"]["shortcut"], 1)
            self.assertEqual(stats["by_source"]["llm"], 1)
            self.assertEqual(stats["corrected_total"], 1)
            self.assertEqual(stats["by_corrected_type"], {"chat": 1})
            corrections = store.list_corrected_samples()
            self.assertEqual(len(corrections), 1)
            self.assertEqual(corrections[0]["text"], "save")
            self.assertEqual(corrections[0]["corrected_intent"], {"type": "chat", "reply": "我先不执行"})

    def test_store_lists_phrase_groups_and_reviews_matching_text(self):
        with tempfile.TemporaryDirectory() as td:
            store = IntentTrainingStore(Path(td) / "training.db")
            batch_id = store.create_batch(source="unit-test")
            store.insert_samples(batch_id, [
                {"text": "save", "intent_type": "chat", "intent_source": "llm", "status": "ok"},
                {"text": "save", "intent_type": "shortcut", "intent_source": "local", "status": "ok"},
                {"text": "delete it", "intent_type": "delete", "intent_source": "local", "status": "ok"},
                {"text": "", "intent_type": "chat", "intent_source": "llm", "status": "ok"},
            ])

            phrases = store.list_phrase_groups(limit=10)

            self.assertEqual(phrases[0]["text"], "save")
            self.assertEqual(phrases[0]["count"], 2)
            self.assertEqual(phrases[0]["reviewed_count"], 0)
            self.assertEqual(phrases[0]["corrected_count"], 0)
            self.assertEqual(phrases[0]["by_intent"], {"chat": 1, "shortcut": 1})

            result = store.review_matching_text(
                "save",
                label="wrong_intent",
                note="same phrase",
                corrected_intent={"type": "shortcut", "name": "保存"},
            )

            self.assertEqual(result["updated"], 2)
            rows = store.list_samples(SampleQuery(review_label="wrong_intent"))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["corrected_intent"], {"type": "shortcut", "name": "保存"})

    def test_parse_jsonl_rejects_non_object_rows(self):
        with self.assertRaises(ValueError):
            parse_jsonl('["bad"]\n')

    def test_store_counts_high_risk_confirmation_metrics(self):
        with tempfile.TemporaryDirectory() as td:
            store = IntentTrainingStore(Path(td) / "training.db")
            batch_id = store.create_batch(source="unit-test")
            store.insert_samples(batch_id, [
                {
                    "text": "发送",
                    "intent_type": "shortcut",
                    "intent_name": "发送",
                    "status": "ok",
                    "operation_risk": "high",
                    "confirmation_triggered": True,
                    "user_cancelled": False,
                },
                {
                    "text": "关闭窗口",
                    "intent_type": "shortcut",
                    "intent_name": "关闭窗口",
                    "status": "cancelled",
                    "operation_risk": "high",
                    "confirmation_triggered": True,
                    "user_cancelled": True,
                    "review_label": "unsafe_should_confirm",
                },
                {
                    "text": "保存",
                    "intent_type": "shortcut",
                    "intent_name": "保存",
                    "status": "ok",
                    "operation_risk": "normal",
                    "confirmation_triggered": False,
                    "user_cancelled": False,
                },
            ])

            stats = store.stats()

            self.assertEqual(stats["by_operation_risk"], {"high": 2, "normal": 1})
            self.assertEqual(stats["confirmation_triggered_total"], 2)
            self.assertEqual(stats["user_cancelled_total"], 1)
            self.assertEqual(stats["high_risk_total"], 2)
            self.assertEqual(stats["unsafe_should_confirm_total"], 1)


if __name__ == "__main__":
    unittest.main()
