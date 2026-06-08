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

    def test_build_evaluation_dataset_deduplicates_corrected_samples(self):
        from agent.intent_evaluation import build_evaluation_dataset

        with tempfile.TemporaryDirectory() as td:
            samples = Path(td) / "samples.jsonl"
            dataset = Path(td) / "dataset.jsonl"
            samples.write_text(
                '{"text": "查找", "shortcut_names": ["查找"], '
                '"corrected_intent": {"type": "shortcut", "name": "查找"}}\n'
                '{"text": "查找", "shortcut_names": ["查找"], '
                '"corrected_intent": {"type": "shortcut", "name": "查找"}}\n'
                '{"text": "你好", "corrected_intent": {"type": "chat", "reply": "hi"}}\n'
                '{"text": "无修正"}\n',
                encoding="utf-8",
            )

            summary = build_evaluation_dataset(samples, dataset)

            self.assertEqual(summary["written"], 2)
            self.assertEqual(summary["source_total"], 4)
            rows = dataset.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(rows), 2)
            self.assertIn('"text": "查找"', rows[0])
            self.assertIn('"expected"', rows[0])

    def test_write_evaluation_report_saves_versioned_json(self):
        from agent.intent_evaluation import write_evaluation_report

        with tempfile.TemporaryDirectory() as td:
            samples = Path(td) / "samples.jsonl"
            reports = Path(td) / "reports"
            samples.write_text(
                '{"text": "查找", "corrected_intent": {"type": "shortcut", "name": "查找"}}\n',
                encoding="utf-8",
            )

            result = write_evaluation_report(samples, reports, version="unit")

            self.assertEqual(result["report"]["total"], 1)
            self.assertTrue(Path(result["path"]).exists())
            self.assertEqual(Path(result["path"]).name, "unit.json")

    def test_evaluation_can_use_local_intent_model_similarity(self):
        from agent.intent_evaluation import evaluate_reviewed_samples, write_evaluation_report
        from agent.intent_model import train_intent_model

        with tempfile.TemporaryDirectory() as td:
            samples = Path(td) / "samples.jsonl"
            model_samples = Path(td) / "model_samples.jsonl"
            model_path = Path(td) / "intent_model.json"
            reports = Path(td) / "reports"
            samples.write_text(
                '{"text": "帮我查找一下", "corrected_intent": {"type": "shortcut", "name": "查找"}}\n',
                encoding="utf-8",
            )
            model_samples.write_text(
                '{"text": "查找一下", "corrected_intent": {"type": "shortcut", "name": "查找"}}\n',
                encoding="utf-8",
            )
            train_intent_model(model_samples, model_path)

            report = evaluate_reviewed_samples(
                samples,
                intent_model_path=model_path,
                intent_model_min_similarity=0.8,
            )
            result = write_evaluation_report(
                samples,
                reports,
                version="model",
                intent_model_path=model_path,
                intent_model_min_similarity=0.8,
            )

            self.assertEqual(report["accuracy_label"], "100.0%")
            self.assertEqual(result["report"]["intent_model_path"], str(model_path))
            self.assertEqual(result["report"]["intent_model_min_similarity"], 0.8)

    def test_generated_dataset_can_be_reported_directly(self):
        from agent.intent_evaluation import build_evaluation_dataset, write_evaluation_report

        with tempfile.TemporaryDirectory() as td:
            samples = Path(td) / "samples.jsonl"
            dataset = Path(td) / "dataset.jsonl"
            reports = Path(td) / "reports"
            samples.write_text(
                '{"text": "查找", "corrected_intent": {"type": "shortcut", "name": "查找"}}\n'
                '{"text": "删一下", "corrected_intent": {"type": "delete"}}\n',
                encoding="utf-8",
            )

            build_evaluation_dataset(samples, dataset)
            result = write_evaluation_report(dataset, reports, version="dataset")

            self.assertEqual(result["report"]["total"], 2)
            self.assertEqual(result["report"]["accuracy_label"], "50.0%")


if __name__ == "__main__":
    unittest.main()
