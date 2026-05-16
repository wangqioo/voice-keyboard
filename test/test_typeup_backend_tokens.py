import json
import tempfile
import unittest
from pathlib import Path


class TypeUpBackendTokenTests(unittest.TestCase):
    def test_stt_loads_latest_tokens_from_cloud_bridge(self):
        from agent.stt import _TypeUpBackendSTT

        with tempfile.TemporaryDirectory() as tmp:
            bridge = Path(tmp) / "cloud-bridge.json"
            bridge.write_text(json.dumps({
                "apiBaseUrl": "http://cloud.example",
                "accessToken": "cloud-access",
                "refreshToken": "cloud-refresh",
            }), encoding="utf-8")

            stt = _TypeUpBackendSTT({
                "api_base_url": "http://config.example",
                "access_token": "config-access",
                "refresh_token": "config-refresh",
                "cloud_bridge_path": str(bridge),
            })

            self.assertEqual(stt._api_base_url, "http://cloud.example")
            self.assertEqual(stt._access_token, "cloud-access")
            self.assertEqual(stt._refresh_token, "cloud-refresh")

    def test_llm_loads_latest_tokens_from_cloud_bridge(self):
        from agent.llm_editor import _TypeUpBackendLLM

        with tempfile.TemporaryDirectory() as tmp:
            bridge = Path(tmp) / "cloud-bridge.json"
            bridge.write_text(json.dumps({
                "apiBaseUrl": "http://cloud.example",
                "accessToken": "cloud-access",
                "refreshToken": "cloud-refresh",
            }), encoding="utf-8")

            llm = _TypeUpBackendLLM({
                "api_base_url": "http://config.example",
                "access_token": "config-access",
                "refresh_token": "config-refresh",
                "cloud_bridge_path": str(bridge),
            })

            self.assertEqual(llm._api_base_url, "http://cloud.example")
            self.assertEqual(llm._access_token, "cloud-access")
            self.assertEqual(llm._refresh_token, "cloud-refresh")


if __name__ == "__main__":
    unittest.main()
