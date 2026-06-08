import unittest

from agent.memo import (
    MemoResolver,
    MemoOperationResult,
    MemoRecord,
    Memo,
    MemoMatcher,
    parse_memo_edit_command,
    redact_memo_value,
    fuzzy_match_memo_key,
)


class FakeMemoStore:
    def __init__(self):
        self.data = {}

    def save(self, key: str, value: str) -> None:
        self.data[key] = value

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def delete(self, key: str) -> bool:
        if key in self.data:
            del self.data[key]
            return True
        return False

    def keys(self) -> list[str]:
        return list(self.data.keys())


class MemoTests(unittest.TestCase):
    def test_save_uses_explicit_selection_before_classifier_value(self):
        store = FakeMemoStore()
        memo = Memo(store)

        result = memo.save("邮箱", "wrong@example.com", selected="me@example.com")

        self.assertEqual(store.data, {"邮箱": "me@example.com"})
        self.assertEqual(result, MemoOperationResult.show("已记住「邮箱」"))

    def test_recall_returns_insert_result(self):
        store = FakeMemoStore()
        store.data["地址"] = "上海"
        memo = Memo(store)

        result = memo.recall("地址")

        self.assertEqual(result, MemoOperationResult.insert("上海"))

    def test_missing_store_returns_disabled_message(self):
        memo = Memo(None)

        result = memo.list_all()

        self.assertEqual(result, MemoOperationResult.show("备忘功能未启用"))

    def test_list_all_formats_saved_memos(self):
        store = FakeMemoStore()
        store.data["邮箱"] = "me@example.com"
        store.data["地址"] = "上海"
        memo = Memo(store)

        result = memo.list_all()

        self.assertEqual(result, MemoOperationResult.insert("邮箱: me@example.com\n地址: 上海"))

    def test_list_all_redacts_sensitive_memo_values(self):
        store = FakeMemoStore()
        store.data["小米的api密钥"] = "test-only-dummy-api-key"
        store.data["访问我家服务器的地址"] = "ssh -p 10281 wq@5.tcp.cpolar.cn"
        memo = Memo(store)

        result = memo.list_all()

        self.assertEqual(result, MemoOperationResult.insert(
            "小米的api密钥: [已隐藏]\n访问我家服务器的地址: [已隐藏]"
        ))
        self.assertNotIn("sk-", result.text)
        self.assertNotIn("ssh -p", result.text)

    def test_delete_reports_removed_memo(self):
        store = FakeMemoStore()
        store.data["邮箱"] = "me@example.com"
        memo = Memo(store)

        result = memo.delete("邮箱")

        self.assertEqual(store.data, {})
        self.assertEqual(result, MemoOperationResult.show("已忘掉「邮箱」"))

    def test_edit_text_renames_key_and_updates_value(self):
        store = FakeMemoStore()
        store.data["mac的密码"] = "mac password"
        memo = Memo(store)

        result = memo.edit_text("mac的密码", "mac", "macOS")

        self.assertEqual(result, MemoOperationResult.show("已更新「macOS的密码」"))
        self.assertEqual(store.data, {"macOS的密码": "macOS password"})

    def test_edit_text_reports_ambiguous_memo(self):
        store = FakeMemoStore()
        store.data["mac的密码"] = "one"
        store.data["mac的账号"] = "two"
        memo = Memo(store)

        result = memo.edit_text("", "mac", "macOS")

        self.assertEqual(
            result,
            MemoOperationResult.show("找到多个备忘：mac的密码、mac的账号，请说得更具体"),
        )

    def test_matcher_finds_saved_key_from_spoken_memo_request(self):
        matcher = MemoMatcher()

        self.assertEqual(
            matcher.match_key("我的手机号是多少", ("手机号", "家庭地址")),
            "手机号",
        )

    def test_matcher_treats_phone_number_as_phone_key(self):
        matcher = MemoMatcher()

        self.assertEqual(
            matcher.match_key("我的手机号码是多少", ("手机号", "家庭地址")),
            "手机号",
        )

    def test_matcher_does_not_match_unrelated_saved_key(self):
        matcher = MemoMatcher()

        self.assertIsNone(matcher.match_key("我的手机号码是多少", ("儿子",)))

    def test_fuzzy_match_memo_key_keeps_matching_rule_in_memo_module(self):
        self.assertEqual(
            fuzzy_match_memo_key("白光宇说什么", ("白光宇最喜欢说的话",)),
            "白光宇最喜欢说的话",
        )

    def test_redact_memo_value_leaves_normal_text_visible(self):
        self.assertEqual(redact_memo_value("爱吃的雪糕", "伊利雪糕"), "伊利雪糕")

    def test_parse_recent_memo_edit_command(self):
        command = parse_memo_edit_command("刚刚说的mac的密码，那个mac实际上是macOS")

        self.assertIsNotNone(command)
        self.assertEqual(command.target, "mac的密码")
        self.assertEqual(command.old, "mac")
        self.assertEqual(command.new, "macOS")


class MemoResolverTests(unittest.TestCase):
    def resolve(self, text: str, *records: MemoRecord):
        return MemoResolver().resolve(text, records)

    def test_single_email_type_query_resolves_unique_memo(self):
        result = self.resolve(
            "我的邮箱地址是什么",
            MemoRecord("工作邮箱", "me@example.com"),
        )

        self.assertEqual(result.status, "unique")
        self.assertEqual(result.key, "工作邮箱")

    def test_multiple_email_type_query_is_ambiguous(self):
        result = self.resolve(
            "我的邮箱是什么",
            MemoRecord("个人邮箱", "me@example.com"),
            MemoRecord("工作邮箱", "work@example.com"),
        )

        self.assertEqual(result.status, "ambiguous")
        self.assertEqual(result.candidates, ("个人邮箱", "工作邮箱"))

    def test_specific_email_alias_selects_one_of_multiple_email_memories(self):
        result = self.resolve(
            "我的工作邮箱是什么",
            MemoRecord("个人邮箱", "me@example.com"),
            MemoRecord("工作邮箱", "work@example.com"),
        )

        self.assertTrue(result.can_recall)
        self.assertEqual(result.key, "工作邮箱")

    def test_address_type_does_not_hide_more_specific_repo_address(self):
        result = self.resolve(
            "量化项目仓库地址是什么",
            MemoRecord("家庭地址", "上海"),
            MemoRecord("量化项目仓库地址", "https://github.com/example/repo.git"),
        )

        self.assertTrue(result.can_recall)
        self.assertEqual(result.key, "量化项目仓库地址")

    def test_unrelated_query_returns_none(self):
        result = self.resolve(
            "我的手机号码是多少",
            MemoRecord("儿子", "白光宇"),
        )

        self.assertEqual(result.status, "none")

    def test_ssh_endpoint_is_not_treated_as_email_memo(self):
        result = self.resolve(
            "我的邮箱是什么",
            MemoRecord("访问我家服务器的地址", "ssh -p 10281 wq@5.tcp.cpolar.cn"),
        )

        self.assertEqual(result.status, "none")

    def test_alias_resolves_memo_key(self):
        result = self.resolve(
            "小白说什么",
            MemoRecord("白光宇最喜欢说的话", "大美女", aliases=("小白",)),
        )

        self.assertTrue(result.can_recall)
        self.assertEqual(result.key, "白光宇最喜欢说的话")


if __name__ == "__main__":
    unittest.main()
