import json
import tempfile
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover - dependency may be absent in desktop env
    TestClient = None

from training_server.config import ServerConfig


@unittest.skipIf(TestClient is None, "fastapi is not installed")
class TrainingServerApiTests(unittest.TestCase):
    def test_review_page_returns_html(self):
        from training_server.api import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(ServerConfig(
                database_url=f"sqlite:///{td}/training.db",
                upload_token="secret",
            ))
            client = TestClient(app)

            response = client.get("/review")

            self.assertEqual(response.status_code, 200)
            self.assertIn("text/html", response.headers["content-type"])
            self.assertIn("Voice Keyboard Intent Review", response.text)
            self.assertIn("/v1/intent-samples", response.text)

    def test_upload_list_review_and_stats_api(self):
        from training_server.api import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(ServerConfig(
                database_url=f"sqlite:///{td}/training.db",
                upload_token="secret",
            ))
            client = TestClient(app)
            headers = {"Authorization": "Bearer secret", "Content-Type": "application/jsonl"}

            response = client.post(
                "/v1/intent-samples/batches",
                params={"source": "unit"},
                headers=headers,
                content=(
                    '{"text":"save","intent_type":"shortcut","status":"ok",'
                    '"corrected_intent":{"type":"shortcut","name":"保存"}}\n'
                ),
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["inserted"], 1)

            rows = client.get("/v1/intent-samples", headers={"Authorization": "Bearer secret"}).json()["items"]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["corrected_intent"], {"type": "shortcut", "name": "保存"})

            review = client.post(
                f"/v1/intent-samples/{rows[0]['id']}/review",
                headers={"Authorization": "Bearer secret"},
                json={
                    "label": "wrong_intent",
                    "note": "ok",
                    "corrected_intent": {"type": "chat", "reply": "我先不执行"},
                },
            )
            self.assertEqual(review.status_code, 200)
            self.assertEqual(review.json()["review_label"], "wrong_intent")
            self.assertEqual(review.json()["corrected_intent"], {"type": "chat", "reply": "我先不执行"})

            stats = client.get("/v1/stats", headers={"Authorization": "Bearer secret"})
            self.assertEqual(stats.status_code, 200)
            self.assertEqual(stats.json()["total"], 1)

    def test_phrase_group_and_bulk_review_api(self):
        from training_server.api import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(ServerConfig(
                database_url=f"sqlite:///{td}/training.db",
                upload_token="secret",
            ))
            client = TestClient(app)
            headers = {"Authorization": "Bearer secret", "Content-Type": "application/jsonl"}

            response = client.post(
                "/v1/intent-samples/batches",
                params={"source": "unit"},
                headers=headers,
                content=(
                    '{"text":"save","intent_type":"chat","status":"ok"}\n'
                    '{"text":"save","intent_type":"shortcut","status":"ok"}\n'
                ),
            )
            self.assertEqual(response.status_code, 200)

            groups = client.get(
                "/v1/intent-phrases",
                headers={"Authorization": "Bearer secret"},
            )
            self.assertEqual(groups.status_code, 200)
            self.assertEqual(groups.json()["items"][0]["text"], "save")
            self.assertEqual(groups.json()["items"][0]["count"], 2)

            review = client.post(
                "/v1/intent-phrases/review",
                headers={"Authorization": "Bearer secret"},
                json={
                    "text": "save",
                    "label": "wrong_intent",
                    "note": "same phrase",
                    "corrected_intent": {"type": "shortcut", "name": "保存"},
                },
            )
            self.assertEqual(review.status_code, 200)
            self.assertEqual(review.json()["updated"], 2)

            rows = client.get(
                "/v1/intent-samples",
                params={"review_label": "wrong_intent", "text": "save"},
                headers={"Authorization": "Bearer secret"},
            ).json()["items"]
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["corrected_intent"], {"type": "shortcut", "name": "保存"})

    def test_upload_requires_token_when_configured(self):
        from training_server.api import create_app

        with tempfile.TemporaryDirectory() as td:
            app = create_app(ServerConfig(
                database_url=f"sqlite:///{td}/training.db",
                upload_token="secret",
            ))
            client = TestClient(app)

            response = client.get("/v1/stats")

            self.assertEqual(response.status_code, 401)

    def test_published_model_api_returns_metadata_and_download(self):
        from training_server.api import create_app

        with tempfile.TemporaryDirectory() as td:
            model_dir = Path(td) / "models"
            model_dir.mkdir()
            (model_dir / "current.json").write_text(
                json.dumps({
                    "version": "server-v1",
                    "created_at": 123.0,
                    "examples": {
                        "查找": {"type": "shortcut", "name": "查找"},
                        "保存": {"type": "shortcut", "name": "保存"},
                    },
                }, ensure_ascii=False),
                encoding="utf-8",
            )
            app = create_app(ServerConfig(
                database_url=f"sqlite:///{td}/training.db",
                upload_token="secret",
                model_dir=str(model_dir),
            ))
            client = TestClient(app)
            headers = {"Authorization": "Bearer secret"}

            metadata = client.get("/v1/intent-models/published", headers=headers)
            self.assertEqual(metadata.status_code, 200)
            self.assertEqual(metadata.json(), {
                "version": "server-v1",
                "examples": 2,
                "created_at": 123.0,
            })

            download = client.get("/v1/intent-models/published/download", headers=headers)
            self.assertEqual(download.status_code, 200)
            self.assertEqual(download.headers["content-type"], "application/json")
            self.assertEqual(download.json()["version"], "server-v1")

    def test_publish_model_api_registers_metadata_and_updates_current(self):
        from training_server.api import create_app

        with tempfile.TemporaryDirectory() as td:
            model_dir = Path(td) / "models"
            version_path = model_dir / "versions" / "server-v2.json"
            version_path.parent.mkdir(parents=True)
            version_path.write_text(
                json.dumps({
                    "version": "server-v2",
                    "created_at": 456.0,
                    "examples": {
                        "发送": {"type": "shortcut", "name": "发送"},
                    },
                }, ensure_ascii=False),
                encoding="utf-8",
            )
            app = create_app(ServerConfig(
                database_url=f"sqlite:///{td}/training.db",
                upload_token="secret",
                model_dir=str(model_dir),
            ))
            client = TestClient(app)
            headers = {"Authorization": "Bearer secret"}

            publish = client.post(
                "/v1/intent-models/published",
                headers=headers,
                json={
                    "version": "server-v2",
                    "model_path": str(version_path),
                    "dataset_version": "dataset-20260619",
                    "evaluation_report": {
                        "path": "reports/server-v2.json",
                        "accuracy": 1.0,
                        "total": 1,
                    },
                    "notes": "first semantic model candidate",
                },
            )
            metadata = client.get("/v1/intent-models/published", headers=headers)

            self.assertEqual(publish.status_code, 200)
            self.assertEqual(publish.json()["version"], "server-v2")
            self.assertTrue((model_dir / "current.json").exists())
            self.assertEqual(metadata.status_code, 200)
            self.assertEqual(metadata.json()["version"], "server-v2")
            self.assertEqual(metadata.json()["dataset_version"], "dataset-20260619")
            self.assertEqual(metadata.json()["evaluation_report"]["accuracy"], 1.0)

    def test_published_model_api_returns_404_without_current_model(self):
        from training_server.api import create_app

        with tempfile.TemporaryDirectory() as td:
            model_dir = Path(td) / "models"
            app = create_app(ServerConfig(
                database_url=f"sqlite:///{td}/training.db",
                upload_token="secret",
                model_dir=str(model_dir),
            ))
            client = TestClient(app)
            headers = {"Authorization": "Bearer secret"}

            metadata = client.get("/v1/intent-models/published", headers=headers)
            download = client.get("/v1/intent-models/published/download", headers=headers)

            self.assertEqual(metadata.status_code, 404)
            self.assertEqual(download.status_code, 404)


if __name__ == "__main__":
    unittest.main()
