import tempfile
import unittest
from pathlib import Path


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _HTTPClient:
    def __init__(self):
        self.posts = []
        self.gets = []

    def post(self, url, *, params=None, data=None, headers=None, timeout=None):
        self.posts.append({
            "url": url,
            "params": params,
            "data": data,
            "headers": headers,
            "timeout": timeout,
        })
        return _Response({"inserted": 1})

    def get(self, url, *, params=None, headers=None, timeout=None):
        self.gets.append({
            "url": url,
            "params": params,
            "headers": headers,
            "timeout": timeout,
        })
        return _Response({
            "items": [
                {
                    "text": "表格里查一下",
                    "corrected_intent": {"type": "shortcut", "name": "查找"},
                }
            ]
        })


class IntentLoopTests(unittest.TestCase):
    def test_run_training_loop_uploads_syncs_and_evaluates(self):
        from agent.intent_loop import run_training_loop
        from agent.intent_overrides import find_override

        with tempfile.TemporaryDirectory() as td:
            samples = Path(td) / "samples.jsonl"
            overrides = Path(td) / "overrides.jsonl"
            samples.write_text(
                '{"text": "表格里查一下", "shortcut_names": ["查找"], '
                '"corrected_intent": {"type": "shortcut", "name": "查找"}}\n',
                encoding="utf-8",
            )
            http = _HTTPClient()

            report = run_training_loop(
                sample_path=samples,
                server="http://training.local",
                token="secret",
                override_path=overrides,
                http=http,
            )

            self.assertEqual(http.posts[0]["url"], "http://training.local/v1/intent-samples/batches")
            self.assertEqual(http.gets[0]["url"], "http://training.local/v1/intent-samples/corrections")
            self.assertEqual(http.posts[0]["headers"]["Authorization"], "Bearer secret")
            self.assertEqual(report["upload"]["inserted"], 1)
            self.assertEqual(report["sync"], {"synced": 1, "skipped": 0, "compacted": 0})
            self.assertEqual(report["evaluation"]["accuracy_label"], "100.0%")
            self.assertEqual(
                find_override("表格里查一下", path=overrides),
                {"type": "shortcut", "name": "查找"},
            )

    def test_run_training_loop_can_train_versioned_model_and_report_it(self):
        from agent.intent_loop import run_training_loop
        from agent.intent_model import load_intent_model

        with tempfile.TemporaryDirectory() as td:
            samples = Path(td) / "samples.jsonl"
            overrides = Path(td) / "overrides.jsonl"
            registry = Path(td) / "models"
            reports = Path(td) / "reports"
            samples.write_text(
                '{"text": "表格里查一下", "shortcut_names": ["查找"], '
                '"corrected_intent": {"type": "shortcut", "name": "查找"}}\n',
                encoding="utf-8",
            )
            http = _HTTPClient()

            report = run_training_loop(
                sample_path=samples,
                server="http://training.local",
                override_path=overrides,
                http=http,
                model_registry_dir=registry,
                model_version="loop-v1",
                model_report_dir=reports,
                model_min_similarity=0.8,
            )
            model = load_intent_model(registry / "current.json")

            self.assertEqual(report["model"]["version"], "loop-v1")
            self.assertEqual(report["model"]["registered"], True)
            self.assertEqual(report["model_evaluation"]["report"]["intent_model_min_similarity"], 0.8)
            self.assertTrue(Path(report["model_evaluation"]["path"]).exists())
            self.assertEqual(model.version, "loop-v1")
            self.assertEqual(model.match("表格里查一下"), {"type": "shortcut", "name": "查找"})


if __name__ == "__main__":
    unittest.main()
