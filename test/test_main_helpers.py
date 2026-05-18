import unittest
import os
from unittest.mock import MagicMock, patch


class MainHelperTests(unittest.TestCase):
    def test_generated_text_cleanup_removes_common_model_markup(self):
        typer = MagicMock()
        typer.list_shortcuts.return_value = []
        with patch.dict("sys.modules", {"sounddevice": MagicMock(), "agent.typer": typer}):
            from agent.main import _clean_generated_text, _clean_polished_text

        self.assertEqual(_clean_generated_text("  ### 你好世界  "), "你好世界")
        self.assertEqual(_clean_polished_text("```text\n润色结果：你好世界\n```"), "你好世界")

    def test_llm_configured_accepts_typeup_backend_tokens(self):
        typer = MagicMock()
        typer.list_shortcuts.return_value = []
        with patch.dict("sys.modules", {"sounddevice": MagicMock(), "agent.typer": typer}):
            from agent.main import _llm_configured

        self.assertTrue(_llm_configured({
            "provider": "typeup_backend",
            "api_base_url": "http://localhost:8000",
            "access_token": "token",
        }))
        self.assertFalse(_llm_configured({
            "provider": "typeup_backend",
            "api_base_url": "http://localhost:8000",
            "access_token": "",
        }))
        self.assertTrue(_llm_configured({
            "provider": "openai",
            "api_key": "sk-test",
        }))

    def test_configure_ssl_cert_file_sets_certifi_when_env_is_missing(self):
        typer = MagicMock()
        typer.list_shortcuts.return_value = []
        with (
            patch.dict("sys.modules", {"sounddevice": MagicMock(), "agent.typer": typer}),
            patch.dict(os.environ, {}, clear=True),
        ):
            from agent.main import _configure_ssl_cert_file

            _configure_ssl_cert_file()

            self.assertIn("certifi", os.environ["SSL_CERT_FILE"])
            self.assertEqual(os.environ["SSL_CERT_FILE"], os.environ["REQUESTS_CA_BUNDLE"])

    def test_configure_ssl_cert_file_preserves_existing_valid_env(self):
        typer = MagicMock()
        typer.list_shortcuts.return_value = []
        existing = __file__
        with (
            patch.dict("sys.modules", {"sounddevice": MagicMock(), "agent.typer": typer}),
            patch.dict(os.environ, {
                "SSL_CERT_FILE": existing,
                "REQUESTS_CA_BUNDLE": existing,
            }, clear=True),
        ):
            from agent.main import _configure_ssl_cert_file

            _configure_ssl_cert_file()

            self.assertEqual(os.environ["SSL_CERT_FILE"], existing)
            self.assertEqual(os.environ["REQUESTS_CA_BUNDLE"], existing)


if __name__ == "__main__":
    unittest.main()
