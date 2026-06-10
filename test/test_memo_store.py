import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agent.memo_store import MemoStore


class MemoStoreTests(unittest.TestCase):
    def test_reads_flat_json_shape(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "memo.json"
            path.write_text(
                json.dumps({"邮箱": "me@example.com"}, ensure_ascii=False),
                encoding="utf-8",
            )

            store = MemoStore(path)

            self.assertEqual(store.get("邮箱"), "me@example.com")
            self.assertEqual(store.keys(), ["邮箱"])

    def test_keeps_flat_json_format_when_saving(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "memo.json"
            store = MemoStore(path)

            store.save("地址", "上海")

            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"地址": "上海"},
            )

    def test_imports_legacy_memos_json_when_new_store_is_missing(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy_path = root / "memos.json"
            new_path = root / "memo.json"
            legacy_path.write_text(
                json.dumps({"邮箱": "me@example.com"}, ensure_ascii=False),
                encoding="utf-8",
            )

            store = MemoStore(new_path, legacy_path=legacy_path)

            self.assertEqual(store.get("邮箱"), "me@example.com")
            self.assertEqual(
                json.loads(new_path.read_text(encoding="utf-8")),
                {"邮箱": "me@example.com"},
            )

    def test_existing_instance_reloads_when_file_changes(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "memo.json"
            first = MemoStore(path)
            second = MemoStore(path)

            second.save("手机号", "15850752485")

            self.assertEqual(first.get("手机号"), "15850752485")
            self.assertEqual(first.keys(), ["手机号"])

    def test_imports_legacy_reusable_text_memory_json_when_new_store_is_missing(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy_path = root / "reusable_text_memory.json"
            new_path = root / "memo.json"
            legacy_path.write_text(
                json.dumps({"地址": "上海"}, ensure_ascii=False),
                encoding="utf-8",
            )

            store = MemoStore(new_path, legacy_path=legacy_path)

            self.assertEqual(store.get("地址"), "上海")
            self.assertEqual(
                json.loads(new_path.read_text(encoding="utf-8")),
                {"地址": "上海"},
            )

if __name__ == "__main__":
    unittest.main()
