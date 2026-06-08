import tempfile
import unittest
from pathlib import Path


class IntentEvaluationTests(unittest.TestCase):
    def test_evaluate_reviewed_samples_scores_corrected_intents(self):
        from agent.intent_evaluation import evaluate_reviewed_samples
        from agent.intent_overrides import append_override

        with tempfile.TemporaryDirectory() as td:
            samples = Path(td) / "samples.jsonl"
            overrides = Path(td) / "overrides.jsonl"
            samples.write_text(
                '{"text": "表格里查一下", "shortcut_names": ["查找"], '
                '"corrected_intent": {"type": "shortcut", "name": "查找"}}\n'
                '{"text": "删一下", "corrected_intent": {"type": "delete"}}\n'
                '{"text": "你好", "review_label": ""}\n',
                encoding="utf-8",
            )
            append_override(
                "表格里查一下",
                {"type": "shortcut", "name": "查找"},
                path=overrides,
            )

            report = evaluate_reviewed_samples(samples, override_path=overrides)

            self.assertEqual(report["total"], 2)
            self.assertEqual(report["correct"], 1)
            self.assertEqual(report["wrong"], 1)
            self.assertEqual(report["accuracy"], 0.5)
            self.assertEqual(report["accuracy_label"], "50.0%")
            self.assertEqual(report["mismatches"][0]["text"], "删一下")
            self.assertEqual(report["mismatches"][0]["expected"], {"type": "delete"})
            self.assertEqual(report["mismatches"][0]["actual"]["type"], "chat")

    def test_evaluate_reviewed_samples_uses_expected_shortcut_as_available_catalog(self):
        from agent.intent_evaluation import evaluate_reviewed_samples

        with tempfile.TemporaryDirectory() as td:
            samples = Path(td) / "samples.jsonl"
            samples.write_text(
                '{"text": "查找", "corrected_intent": {"type": "shortcut", "name": "查找"}}\n',
                encoding="utf-8",
            )

            report = evaluate_reviewed_samples(samples)

            self.assertEqual(report["total"], 1)
            self.assertEqual(report["correct"], 1)


if __name__ == "__main__":
    unittest.main()
