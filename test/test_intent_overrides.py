import tempfile
import unittest
from pathlib import Path


class IntentOverridesTests(unittest.TestCase):
    def test_compact_overrides_keeps_latest_intent_per_text_key(self):
        from agent.intent_overrides import append_override, compact_overrides, find_override

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "overrides.jsonl"
            append_override("表格里查一下", {"type": "chat", "reply": "不执行"}, path=path)
            append_override("发送", {"type": "shortcut", "name": "发送"}, path=path)
            append_override("表格里查一下", {"type": "shortcut", "name": "查找"}, path=path)

            result = compact_overrides(path=path)

            self.assertEqual(result, {"kept": 2, "removed": 1})
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 2)
            self.assertEqual(
                find_override("表格里查一下", path=path),
                {"type": "shortcut", "name": "查找"},
            )


if __name__ == "__main__":
    unittest.main()
