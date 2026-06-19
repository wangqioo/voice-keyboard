import tempfile
import unittest
from pathlib import Path

from agent.config_hygiene import find_plaintext_secrets


class ConfigHygieneTests(unittest.TestCase):
    def test_find_plaintext_secrets_reports_secret_fields_in_yaml(self):
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "config.yaml"
            config.write_text(
                """
stt:
  provider: glm_asr_2512
  api_key: sk-live-secret
llm:
  provider: zhipuai
  api_key: ${LLM_API_KEY}
typeup:
  managed: true
""",
                encoding="utf-8",
            )

            findings = find_plaintext_secrets(config)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0]["path"], "stt.api_key")
            self.assertEqual(findings[0]["line"], 4)

    def test_find_plaintext_secrets_ignores_env_placeholders_and_empty_values(self):
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "config.yaml"
            config.write_text(
                """
stt:
  api_key: ${STT_API_KEY}
llm:
  token: ""
ai_stt:
  access_key_secret: $AI_STT_SECRET
""",
                encoding="utf-8",
            )

            self.assertEqual(find_plaintext_secrets(config), [])


if __name__ == "__main__":
    unittest.main()
