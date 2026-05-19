import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agent.reusable_text_memory_store import ReusableTextMemoryStore


class ReusableTextMemoryStoreTests(unittest.TestCase):
    def test_reads_flat_json_shape(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "reusable_text_memory.json"
            path.write_text(
                json.dumps({"邮箱": "me@example.com"}, ensure_ascii=False),
                encoding="utf-8",
            )

            store = ReusableTextMemoryStore(path)

            self.assertEqual(store.get("邮箱"), "me@example.com")
            self.assertEqual(store.keys(), ["邮箱"])

    def test_keeps_flat_json_format_when_saving(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "reusable_text_memory.json"
            store = ReusableTextMemoryStore(path)

            store.save("地址", "上海")

            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"地址": "上海"},
            )

    def test_imports_legacy_memos_json_when_new_store_is_missing(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy_path = root / "memos.json"
            new_path = root / "reusable_text_memory.json"
            legacy_path.write_text(
                json.dumps({"邮箱": "me@example.com"}, ensure_ascii=False),
                encoding="utf-8",
            )

            store = ReusableTextMemoryStore(new_path, legacy_path=legacy_path)

            self.assertEqual(store.get("邮箱"), "me@example.com")
            self.assertEqual(
                json.loads(new_path.read_text(encoding="utf-8")),
                {"邮箱": "me@example.com"},
            )

if __name__ == "__main__":
    unittest.main()
