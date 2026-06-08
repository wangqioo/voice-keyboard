import tempfile
import unittest
from pathlib import Path


class IntentModelTests(unittest.TestCase):
    def test_train_and_load_exact_match_model(self):
        from agent.intent_model import load_intent_model, train_intent_model

        with tempfile.TemporaryDirectory() as td:
            samples = Path(td) / "samples.jsonl"
            model_path = Path(td) / "intent_model.json"
            samples.write_text(
                '{"text": "查找一下", "corrected_intent": {"type": "shortcut", "name": "查找"}}\n'
                '{"text": "查找一下", "corrected_intent": {"type": "shortcut", "name": "查找"}}\n'
                '{"text": "无修正"}\n',
                encoding="utf-8",
            )

            summary = train_intent_model(samples, model_path)
            model = load_intent_model(model_path)

            self.assertEqual(summary["examples"], 1)
            self.assertEqual(model.match("查找一下"), {"type": "shortcut", "name": "查找"})
            self.assertIsNone(model.match("查找一下别的"))
            self.assertIsNone(model.match("帮我查找一下", min_similarity=1.0))

    def test_model_can_match_high_similarity_variants_when_enabled(self):
        from agent.intent_model import load_intent_model, train_intent_model

        with tempfile.TemporaryDirectory() as td:
            samples = Path(td) / "samples.jsonl"
            model_path = Path(td) / "intent_model.json"
            samples.write_text(
                '{"text": "查找一下", "corrected_intent": {"type": "shortcut", "name": "查找"}}\n',
                encoding="utf-8",
            )
            train_intent_model(samples, model_path)
            model = load_intent_model(model_path)

            self.assertEqual(
                model.match("帮我查找一下", min_similarity=0.8),
                {"type": "shortcut", "name": "查找"},
            )
            self.assertIsNone(model.match("删除全文", min_similarity=0.8))


if __name__ == "__main__":
    unittest.main()
