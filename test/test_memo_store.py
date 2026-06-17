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

    def test_writes_canonical_record_shape_when_saving(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "memo.json"
            store = MemoStore(path)

            store.save("地址", "上海")

            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"地址": {
                    "value": "上海",
                    "aliases": [],
                    "value_type": "",
                    "sensitive": False,
                }},
            )

    def test_reads_canonical_records_with_metadata(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "memo.json"
            path.write_text(
                json.dumps({
                    "工作邮箱": {
                        "value": "me@example.com",
                        "aliases": ["公司邮箱"],
                        "value_type": "contact.email",
                        "sensitive": True,
                    }
                }, ensure_ascii=False),
                encoding="utf-8",
            )

            store = MemoStore(path)
            records = store.records()

            self.assertEqual(store.get("工作邮箱"), "me@example.com")
            self.assertEqual(store.keys(), ["工作邮箱"])
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].key, "工作邮箱")
            self.assertEqual(records[0].value, "me@example.com")
            self.assertEqual(records[0].aliases, ("公司邮箱",))
            self.assertEqual(records[0].value_type, "contact.email")
            self.assertTrue(records[0].sensitive)

    def test_records_promote_flat_json_to_default_metadata(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "memo.json"
            path.write_text(
                json.dumps({"地址": "上海"}, ensure_ascii=False),
                encoding="utf-8",
            )

            store = MemoStore(path)

            self.assertEqual(store.records()[0].key, "地址")
            self.assertEqual(store.records()[0].value, "上海")
            self.assertEqual(store.records()[0].aliases, ())
            self.assertEqual(store.records()[0].value_type, "")
            self.assertFalse(store.records()[0].sensitive)

    def test_saving_existing_record_preserves_metadata(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "memo.json"
            path.write_text(
                json.dumps({
                    "工作邮箱": {
                        "value": "old@example.com",
                        "aliases": ["公司邮箱"],
                        "value_type": "contact.email",
                        "sensitive": True,
                    }
                }, ensure_ascii=False),
                encoding="utf-8",
            )
            store = MemoStore(path)

            store.save("工作邮箱", "new@example.com")

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {
                "工作邮箱": {
                    "value": "new@example.com",
                    "aliases": ["公司邮箱"],
                    "value_type": "contact.email",
                    "sensitive": True,
                }
            })

    def test_save_record_updates_aliases_and_preserves_metadata(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "memo.json"
            path.write_text(
                json.dumps({
                    "工作邮箱": {
                        "value": "old@example.com",
                        "aliases": ["公司邮箱"],
                        "value_type": "contact.email",
                        "sensitive": True,
                    }
                }, ensure_ascii=False),
                encoding="utf-8",
            )
            store = MemoStore(path)

            store.save_record("工作邮箱", "new@example.com", aliases=("邮箱", "email", "邮箱"))

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {
                "工作邮箱": {
                    "value": "new@example.com",
                    "aliases": ["邮箱", "email"],
                    "value_type": "contact.email",
                    "sensitive": True,
                }
            })

    def test_save_record_writes_aliases_for_new_record(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "memo.json"
            store = MemoStore(path)

            store.save_record("工作邮箱", "me@example.com", aliases=(" 公司邮箱 ", "email", ""))

            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"工作邮箱": {
                    "value": "me@example.com",
                    "aliases": ["公司邮箱", "email"],
                    "value_type": "",
                    "sensitive": False,
                }},
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
                {"邮箱": {
                    "value": "me@example.com",
                    "aliases": [],
                    "value_type": "",
                    "sensitive": False,
                }},
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
                {"地址": {
                    "value": "上海",
                    "aliases": [],
                    "value_type": "",
                    "sensitive": False,
                }},
            )

if __name__ == "__main__":
    unittest.main()
