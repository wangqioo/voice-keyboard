import os
import tempfile
import unittest
from pathlib import Path


class IntentModelUITests(unittest.TestCase):
    def test_get_latest_model_report_summary_reads_newest_report(self):
        from agent.intent_model_ui import get_latest_model_report_summary

        with tempfile.TemporaryDirectory() as td:
            reports = Path(td)
            old = reports / "old.json"
            new = reports / "new.json"
            old.write_text('{"accuracy_label":"50.0%","wrong":1,"total":2}', encoding="utf-8")
            new.write_text('{"accuracy_label":"100.0%","wrong":0,"total":2}', encoding="utf-8")
            os.utime(old, (1, 1))
            os.utime(new, (2, 2))

            summary = get_latest_model_report_summary(reports)

            self.assertEqual(summary["accuracy_label"], "100.0%")
            self.assertEqual(summary["wrong"], 0)
            self.assertEqual(summary["path"], str(new))

    def test_train_local_model_for_ui_registers_version_and_report(self):
        from agent.intent_model_ui import get_model_status, train_local_model_for_ui

        with tempfile.TemporaryDirectory() as td:
            samples = Path(td) / "samples.jsonl"
            overrides = Path(td) / "overrides.jsonl"
            registry = Path(td) / "models"
            reports = Path(td) / "reports"
            samples.write_text(
                '{"text": "查找", "corrected_intent": {"type": "shortcut", "name": "查找"}}\n',
                encoding="utf-8",
            )

            result = train_local_model_for_ui(
                sample_path=samples,
                registry_dir=registry,
                report_dir=reports,
                override_path=overrides,
                version="ui-v1",
                min_similarity=0.8,
            )
            status = get_model_status(registry)

            self.assertEqual(result["model"]["version"], "ui-v1")
            self.assertEqual(result["model"]["registered"], True)
            self.assertEqual(result["evaluation"]["report"]["intent_model_min_similarity"], 0.8)
            self.assertEqual(status["current_version"], "ui-v1")
            self.assertEqual(status["version_count"], 1)

    def test_rollback_model_for_ui_reports_previous_current_version(self):
        from agent.intent_model import train_intent_model
        from agent.intent_model_ui import get_model_status, rollback_model_for_ui

        with tempfile.TemporaryDirectory() as td:
            first = Path(td) / "first.jsonl"
            second = Path(td) / "second.jsonl"
            registry = Path(td) / "models"
            first.write_text(
                '{"text": "查找", "corrected_intent": {"type": "shortcut", "name": "查找"}}\n',
                encoding="utf-8",
            )
            second.write_text(
                '{"text": "保存", "corrected_intent": {"type": "shortcut", "name": "保存"}}\n',
                encoding="utf-8",
            )
            train_intent_model(first, registry / "current.json", version="v1", registry_dir=registry)
            train_intent_model(second, registry / "current.json", version="v2", registry_dir=registry)

            result = rollback_model_for_ui(registry)
            status = get_model_status(registry)

            self.assertEqual(result["version"], "v1")
            self.assertEqual(result["previous_version"], "v2")
            self.assertEqual(status["current_version"], "v1")


if __name__ == "__main__":
    unittest.main()
