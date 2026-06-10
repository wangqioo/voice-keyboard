import tempfile
import unittest
from pathlib import Path


class WindowsMainWindowTests(unittest.TestCase):
    def test_build_corrected_intent_for_shortcut(self):
        from agent.windows_main_window import build_corrected_intent

        self.assertEqual(
            build_corrected_intent("shortcut", "Save"),
            {"type": "shortcut", "name": "Save"},
        )

    def test_build_corrected_intent_for_memo_save_keeps_value(self):
        from agent.windows_main_window import build_corrected_intent

        self.assertEqual(
            build_corrected_intent("memo_save", "project", "notes"),
            {"type": "memo_save", "key": "project", "value": "notes"},
        )

    def test_build_corrected_intent_returns_none_without_type(self):
        from agent.windows_main_window import build_corrected_intent

        self.assertIsNone(build_corrected_intent("", "ignored"))



    def test_split_words_accepts_common_separators(self):
        from agent.windows_main_window import _split_words

        self.assertEqual(
            _split_words("\u8bb0\u4e00\u4e0b\uff0c\u8bb0\u4f4f, \u5907\u5fd8\u3001\u6536\u4e00\u4e0b"),
            ["\u8bb0\u4e00\u4e0b", "\u8bb0\u4f4f", "\u5907\u5fd8", "\u6536\u4e00\u4e0b"],
        )

    def test_format_sync_evaluation_message_for_local_loop(self):
        from agent.windows_main_window import format_sync_evaluation_message

        message = format_sync_evaluation_message(
            sync={"synced": 2, "skipped": 1, "compacted": 3},
            evaluation={"accuracy_label": "75.0%", "wrong": 1, "total": 4},
        )

        self.assertIn("Local sync complete", message)
        self.assertIn("synced=2", message)
        self.assertIn("accuracy=75.0%", message)

    def test_training_server_config_round_trips(self):
        import agent.windows_main_window as window

        with tempfile.TemporaryDirectory() as td:
            old_user_dir = window._USER_DIR
            old_config = window._CONFIG
            try:
                window._USER_DIR = Path(td)
                window._CONFIG = Path(td) / "config.yaml"
                window.save_intent_training_server_config(" http://127.0.0.1:8000 ", " token ")

                self.assertEqual(
                    window.intent_training_server_config(),
                    {"server": "http://127.0.0.1:8000", "token": "token"},
                )
            finally:
                window._USER_DIR = old_user_dir
                window._CONFIG = old_config

if __name__ == "__main__":
    unittest.main()