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
            corrections = store.list_corrected_samples()
            self.assertEqual(len(corrections), 1)
            self.assertEqual(corrections[0]["text"], "save")
            self.assertEqual(corrections[0]["corrected_intent"], {"type": "chat", "reply": "我先不执行"})

    def test_parse_jsonl_rejects_non_object_rows(self):
        with self.assertRaises(ValueError):
            parse_jsonl('["bad"]\n')


if __name__ == "__main__":
    unittest.main()
