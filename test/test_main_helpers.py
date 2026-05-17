import unittest
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


if __name__ == "__main__":
    unittest.main()
