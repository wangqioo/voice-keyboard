import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
