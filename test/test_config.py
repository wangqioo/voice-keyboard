import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agent.config as app_config


class ConfigTests(unittest.TestCase):
    def test_yaml_env_placeholders_are_resolved_after_dotenv_load(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = root / "config.yaml"
            env = root / ".env"
            config.write_text(
                """
stt:
  provider: glm_asr_2512
  api_key: ${GLM_API_KEY}
llm:
  provider: zhipuai
  api_key: $GLM_API_KEY
""",
                encoding="utf-8",
            )
            env.write_text("GLM_API_KEY=local-secret\n", encoding="utf-8")

            with patch.object(app_config, "_USER_CONFIG", config), \
                    patch.object(app_config, "_DEV_CONFIG", config), \
                    patch.object(app_config, "_USER_ENV", env), \
                    patch.object(app_config, "_DEV_ENV", env), \
                    patch.dict(os.environ, {}, clear=True):
                cfg = app_config.load()

            self.assertEqual(cfg["stt"]["api_key"], "local-secret")
            self.assertEqual(cfg["llm"]["api_key"], "local-secret")


if __name__ == "__main__":
    unittest.main()
