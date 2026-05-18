import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class TypeUpBackendTokenTests(unittest.TestCase):
    def test_auth_loads_latest_tokens_from_cloud_bridge(self):
        from agent.typeup_backend_auth import TypeUpBackendAuth

        with tempfile.TemporaryDirectory() as tmp:
            bridge = Path(tmp) / "cloud-bridge.json"
            bridge.write_text(json.dumps({
                "apiBaseUrl": "http://cloud.example",
                "accessToken": "cloud-access",
                "refreshToken": "cloud-refresh",
            }), encoding="utf-8")

            auth = TypeUpBackendAuth({
                "api_base_url": "http://config.example",
                "access_token": "config-access",
                "refresh_token": "config-refresh",
                "cloud_bridge_path": str(bridge),
            })

            self.assertEqual(auth.api_base_url, "http://cloud.example")
            self.assertEqual(auth.access_token, "cloud-access")
            self.assertEqual(auth.refresh_token, "cloud-refresh")
            self.assertEqual(auth.auth_header(), {"Authorization": "Bearer cloud-access"})

    def test_stt_and_llm_use_shared_auth_adapter(self):
        from agent.stt import _TypeUpBackendSTT
        from agent.llm_editor import _TypeUpBackendLLM

        with tempfile.TemporaryDirectory() as tmp:
            bridge = Path(tmp) / "cloud-bridge.json"
            bridge.write_text(json.dumps({
                "apiBaseUrl": "http://cloud.example",
                "accessToken": "cloud-access",
                "refreshToken": "cloud-refresh",
            }), encoding="utf-8")

            cfg = {
                "api_base_url": "http://config.example",
                "access_token": "config-access",
                "refresh_token": "config-refresh",
                "cloud_bridge_path": str(bridge),
            }

            stt = _TypeUpBackendSTT(cfg)
            llm = _TypeUpBackendLLM(cfg)

            self.assertEqual(stt._auth.api_base_url, "http://cloud.example")
            self.assertEqual(llm._auth.api_base_url, "http://cloud.example")
            self.assertEqual(stt._auth.access_token, "cloud-access")
            self.assertEqual(llm._auth.access_token, "cloud-access")

    def test_refresh_access_token_persists_tokens_to_bridge(self):
        from agent.typeup_backend_auth import TypeUpBackendAuth

        with tempfile.TemporaryDirectory() as tmp:
            bridge = Path(tmp) / "cloud-bridge.json"
            bridge.write_text(json.dumps({"accessToken": "old"}), encoding="utf-8")
            auth = TypeUpBackendAuth({
                "api_base_url": "http://config.example",
                "access_token": "old",
                "refresh_token": "refresh",
                "cloud_bridge_path": str(bridge),
            })
            response = MagicMock()
            response.ok = True
            response.json.return_value = {
                "access_token": "new-access",
                "refresh_token": "new-refresh",
            }

            with patch("agent.typeup_backend_auth.requests.post", return_value=response) as post:
                auth.refresh_access_token()

            post.assert_called_once_with(
                "http://config.example/v1/auth/refresh",
                json={"refresh_token": "refresh"},
                timeout=15,
            )
            payload = json.loads(bridge.read_text(encoding="utf-8"))
            self.assertEqual(payload["accessToken"], "new-access")
            self.assertEqual(payload["refreshToken"], "new-refresh")


if __name__ == "__main__":
    unittest.main()
