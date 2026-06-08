import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from agent.ai_intent import (
    IntentContext,
    IntentFallbackOptions,
    ShortcutIntentEntry,
    classify_intent,
    classify_intent_details,
    memo_records,
)
from agent.memo import MemoRecord


class AIIntentTests(unittest.TestCase):
    def memo_record(self, key: str, value: str = "") -> MemoRecord:
        return MemoRecord(key=key, value=value)

    def test_selected_edit_instruction_overrides_chat_by_default(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"请提供内容"}'

        result = classify_intent(llm, IntentContext(
            text="帮我润色一下",
            selected="这是一段原文",
        ))

        self.assertEqual(result, {"type": "edit"})

    def test_corrected_intent_override_classifies_same_text_locally(self):
        from agent.intent_overrides import append_override

        with tempfile.TemporaryDirectory() as td:
            override_path = Path(td) / "intent_overrides.jsonl"
            append_override(
                "表格里查一下",
                {"type": "shortcut", "name": "查找"},
                path=override_path,
            )
            llm = MagicMock()
            llm.chat.return_value = '{"type":"chat","reply":"x"}'

            result = classify_intent(
                llm,
                IntentContext(text="表格里查一下", shortcuts=("查找",)),
                IntentFallbackOptions(intent_overrides_path=str(override_path)),
            )

            self.assertEqual(result, {"type": "shortcut", "name": "查找"})
            llm.chat.assert_not_called()

    def test_corrected_shortcut_override_is_ignored_when_shortcut_is_unavailable(self):
        from agent.intent_overrides import append_override

        with tempfile.TemporaryDirectory() as td:
            override_path = Path(td) / "intent_overrides.jsonl"
            append_override(
                "表格里查一下",
                {"type": "shortcut", "name": "查找"},
                path=override_path,
            )
            llm = MagicMock()
            llm.chat.return_value = '{"type":"chat","reply":"没有这个动作"}'

            result = classify_intent(
                llm,
                IntentContext(text="表格里查一下", shortcuts=("保存",)),
                IntentFallbackOptions(intent_overrides_path=str(override_path)),
            )

            self.assertEqual(result, {"type": "chat", "reply": "没有这个动作"})
            llm.chat.assert_called_once()

    def test_local_intent_model_classifies_before_llm(self):
        from agent.intent_model import train_intent_model

        with tempfile.TemporaryDirectory() as td:
            samples = Path(td) / "samples.jsonl"
            model_path = Path(td) / "intent_model.json"
            samples.write_text(
                '{"text": "表格里查一下", "corrected_intent": {"type": "shortcut", "name": "查找"}}\n',
                encoding="utf-8",
            )
            train_intent_model(samples, model_path)
            llm = MagicMock()
            llm.chat.return_value = '{"type":"chat","reply":"x"}'

            details = classify_intent_details(
                llm,
                IntentContext(text="表格里查一下", shortcuts=("查找",)),
                IntentFallbackOptions(intent_model=True, intent_model_path=str(model_path)),
            )

            self.assertEqual(details.result["type"], "shortcut")
            self.assertEqual(details.result["name"], "查找")
            self.assertEqual(details.source, "local")
            llm.chat.assert_not_called()

    def test_local_intent_model_can_match_high_similarity_variant(self):
        from agent.intent_model import train_intent_model

        with tempfile.TemporaryDirectory() as td:
            samples = Path(td) / "samples.jsonl"
            model_path = Path(td) / "intent_model.json"
            samples.write_text(
                '{"text": "查找一下", "corrected_intent": {"type": "shortcut", "name": "查找"}}\n',
                encoding="utf-8",
            )
            train_intent_model(samples, model_path)
            llm = MagicMock()
            llm.chat.return_value = '{"type":"chat","reply":"x"}'

            result = classify_intent(
                llm,
                IntentContext(text="帮我查找一下", shortcuts=("查找",)),
                IntentFallbackOptions(
                    intent_model=True,
                    intent_model_path=str(model_path),
                    intent_model_min_similarity=0.8,
                ),
            )

            self.assertEqual(result, {"type": "shortcut", "name": "查找"})
            llm.chat.assert_not_called()

    def test_selected_translation_instruction_overrides_write_by_default(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"write"}'

        result = classify_intent(llm, IntentContext(
            text="把这段话翻译成文言文",
            selected="A gentle breeze brings the fragrance of osmanthus.",
        ))

        self.assertEqual(result, {"type": "edit"})

    def test_selected_edit_override_can_be_disabled(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"write"}'

        result = classify_intent(
            llm,
            IntentContext(
                text="把这段话翻译成文言文",
                selected="A gentle breeze brings the fragrance of osmanthus.",
            ),
            IntentFallbackOptions(selected_edit_override=False),
        )

        self.assertEqual(result, {"type": "write"})

    def test_edit_hint_without_selection_uses_recent_text_by_default(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"请提供内容"}'

        result = classify_intent(llm, IntentContext(
            text="把上一句翻译成英文",
            recent_text="上一句",
        ))

        self.assertEqual(result, {"type": "edit"})
        llm.chat.assert_not_called()

    def test_edit_word_without_selection_uses_recent_text_by_default(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"请提供内容"}'

        result = classify_intent(llm, IntentContext(
            text="编辑一下",
            recent_text="刚写出来的内容",
        ))

        self.assertEqual(result, {"type": "edit"})
        llm.chat.assert_not_called()

    def test_compliance_hint_without_selection_uses_recent_text_by_default(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"请提供内容"}'

        result = classify_intent(llm, IntentContext(
            text="改得合规一点",
            recent_text="刚写出来的内容",
        ))

        self.assertEqual(result, {"type": "edit"})
        llm.chat.assert_not_called()

    def test_write_request_with_edit_hint_without_target_stays_write(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"write"}'

        result = classify_intent(llm, IntentContext(text="写一封英文邮件"))

        self.assertEqual(result, {"type": "write"})
        llm.chat.assert_not_called()

    def test_write_request_is_classified_locally_without_target(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"x"}'

        result = classify_intent(llm, IntentContext(text="\u5e2e\u6211\u8d77\u8349\u4e00\u6bb5\u5ba2\u6237\u56de\u590d"))

        self.assertEqual(result, {"type": "write"})
        llm.chat.assert_not_called()

    def test_write_request_stays_write_with_recent_text_when_clear_new_content(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"edit"}'

        result = classify_intent(llm, IntentContext(
            text="\u5e2e\u6211\u5199\u4e00\u5c01\u82f1\u6587\u90ae\u4ef6",
            recent_text="\u521a\u624d\u8f93\u5165\u7684\u6587\u5b57",
        ))

        self.assertEqual(result, {"type": "write"})
        llm.chat.assert_not_called()

    def test_selected_delete_instruction_is_classified_locally(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"x"}'

        result = classify_intent(llm, IntentContext(
            text="\u5220\u6389\u9009\u4e2d\u7684\u5185\u5bb9",
            selected="\u8fd9\u6bb5\u8981\u5220\u9664",
        ))

        self.assertEqual(result, {"type": "delete"})
        llm.chat.assert_not_called()

    def test_whole_delete_instruction_is_classified_locally(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"请先选中"}'

        result = classify_intent(llm, IntentContext(text="删除全文"))

        self.assertEqual(result, {"type": "delete"})
        llm.chat.assert_not_called()

    def test_whole_delete_fallback_overrides_llm_chat(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"请先选中"}'

        result = classify_intent(
            llm,
            IntentContext(text="把输入框里面的内容全部删掉"),
            IntentFallbackOptions(selected_edit_override=False),
        )

        self.assertEqual(result, {"type": "delete"})

    def test_chat_can_fuzzy_match_saved_memo_key(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"不知道"}'

        result = classify_intent(llm, IntentContext(
            text="我的手机号是多少",
            memo_records=(self.memo_record("手机号"),),
        ))

        self.assertEqual(result, {"type": "memo_recall", "key": "手机号"})
        llm.chat.assert_not_called()

    def test_memo_recall_from_llm_is_validated_against_request(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"memo_recall","key":"儿子"}'

        result = classify_intent(llm, IntentContext(
            text="我的手机号码是多少",
            memo_records=(
                self.memo_record("儿子"),
                self.memo_record("手机号"),
            ),
        ))

        self.assertEqual(result, {"type": "memo_recall", "key": "手机号"})

    def test_memo_recall_from_llm_rejects_unrelated_key(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"memo_recall","key":"儿子"}'

        result = classify_intent(llm, IntentContext(
            text="我的手机号码是多少",
            memo_records=(self.memo_record("儿子"),),
        ))

        self.assertEqual(result, {"type": "chat", "reply": "没有找到匹配的备忘"})

    def test_chat_does_not_fuzzy_match_saved_memo_key_without_lookup_shape(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"不知道"}'

        result = classify_intent(llm, IntentContext(
            text="手机号这个词是什么意思",
            memo_records=(self.memo_record("手机号"),),
        ))

        self.assertEqual(result, {"type": "chat", "reply": "不知道"})

    def test_memo_fuzzy_recall_can_be_disabled(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"不知道"}'

        result = classify_intent(
            llm,
            IntentContext(
                text="我的手机号是多少",
                memo_records=(self.memo_record("手机号"),),
            ),
            IntentFallbackOptions(memo_fuzzy_recall=False),
        )

        self.assertEqual(result, {"type": "chat", "reply": "不知道"})

    def test_legacy_memo_fuzzy_recall_config_still_disables_memo_fallback(self):
        self.assertEqual(
            IntentFallbackOptions.from_config({"memo_fuzzy_recall": False}),
            IntentFallbackOptions(memo_fuzzy_recall=False),
        )

    def test_memo_records_include_saved_values(self):
        memory_entries = MagicMock()
        memory_entries.keys.return_value = ["白光宇最喜欢说的话"]
        memory_entries.get.return_value = "大美女"

        records = memo_records(memory_entries)

        self.assertEqual(records[0].key, "白光宇最喜欢说的话")
        self.assertEqual(records[0].value, "大美女")
        self.assertEqual(records[0].aliases, ())

    def test_classifier_keeps_structured_result(self):
        llm = MagicMock()
        llm.chat.return_value = '```json\n{"type":"shortcut","name":"保存"}\n```'

        result = classify_intent(llm, IntentContext(
            text="保存",
            active_application="Codex (com.openai.codex)",
            shortcuts=("保存",),
        ))

        self.assertEqual(result, {"type": "shortcut", "name": "保存"})

    def test_undo_intent_is_normalized_to_application_shortcut(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"undo"}'

        result = classify_intent(llm, IntentContext(
            text="撤销",
            shortcuts=("撤销",),
        ))

        self.assertEqual(result, {"type": "shortcut", "name": "撤销"})

    def test_classifier_prompt_includes_active_application_shortcuts(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"shortcut","name":"发送"}'

        classify_intent(llm, IntentContext(
            text="这个按钮怎么发送",
            active_application="Codex (com.openai.codex)",
            shortcuts=("发送",),
        ))

        _system, user = llm.chat.call_args.args
        self.assertIn("当前活动应用：Codex (com.openai.codex)", user)
        self.assertIn("当前活动应用可用 Shortcut Catalog：发送", user)

    def test_classifier_can_resolve_office_action_from_shortcut_catalog(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"shortcut","name":"插入批注"}'

        result = classify_intent(llm, IntentContext(
            text="插入批注",
            active_application="Microsoft Word (com.microsoft.Word)",
            shortcuts=("插入批注", "加粗", "标题 1"),
        ))

        self.assertEqual(result, {"type": "shortcut", "name": "插入批注"})

    def test_open_app_utterance_exactly_matches_local_shortcut_catalog(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"我不能打开应用"}'

        result = classify_intent(llm, IntentContext(
            text="打开飞书。",
            shortcuts=("打开飞书", "加粗"),
        ))

        self.assertEqual(result, {"type": "shortcut", "name": "打开飞书"})

    def test_open_app_utterance_matches_catalog_with_prefix_and_suffix(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"shortcut","name":"打开系统设置"}'

        result = classify_intent(llm, IntentContext(
            text="帮我打开飞书应用。",
            shortcuts=("打开系统设置", "打开飞书"),
        ))

        self.assertEqual(result, {"type": "shortcut", "name": "打开飞书"})

    def test_unknown_open_app_does_not_fall_back_to_open_settings(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"shortcut","name":"打开系统设置"}'

        result = classify_intent(llm, IntentContext(
            text="打开不存在的应用。",
            shortcuts=("打开系统设置", "打开飞书"),
        ))

        self.assertEqual(result, {"type": "chat", "reply": "没有找到可打开的应用"})

    def test_google_browser_open_utterance_matches_catalog(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"shortcut","name":"打开系统设置"}'

        result = classify_intent(llm, IntentContext(
            text="我打开谷歌浏览器。",
            shortcuts=("打开系统设置", "打开谷歌浏览器"),
        ))

        self.assertEqual(result, {"type": "shortcut", "name": "打开谷歌浏览器"})

    def test_open_app_utterance_tolerates_stt_open_homophone(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"x"}'

        result = classify_intent(llm, IntentContext(
            text="\u6253\u4e2a\u5fae\u4fe1",
            shortcuts=("\u6253\u5f00\u5fae\u4fe1",),
        ))

        self.assertEqual(result, {"type": "shortcut", "name": "\u6253\u5f00\u5fae\u4fe1"})
        llm.chat.assert_not_called()

    def test_switch_to_app_utterance_matches_catalog(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"x"}'

        result = classify_intent(llm, IntentContext(
            text="\u5207\u6362\u5230\u5fae\u4fe1",
            shortcuts=("\u5207\u6362\u5230\u5fae\u4fe1", "\u6253\u5f00\u5fae\u4fe1"),
        ))

        self.assertEqual(result, {"type": "shortcut", "name": "\u5207\u6362\u5230\u5fae\u4fe1"})
        llm.chat.assert_not_called()

    def test_open_app_utterance_matches_catalog_case_insensitively(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"x"}'

        result = classify_intent(llm, IntentContext(
            text="打开stocks。",
            shortcuts=("打开Stocks",),
        ))

        self.assertEqual(result, {"type": "shortcut", "name": "打开Stocks"})
        llm.chat.assert_not_called()

    def test_macos_window_utterance_matches_system_shortcut_catalog(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"我不能调整窗口"}'

        result = classify_intent(llm, IntentContext(
            text="把窗口移到左边。",
            shortcuts=("窗口左半屏", "窗口右半屏", "窗口最大化"),
        ))

        self.assertEqual(result, {"type": "shortcut", "name": "窗口左半屏"})
        llm.chat.assert_not_called()

    def test_undo_utterance_is_classified_locally(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"x"}'

        result = classify_intent(llm, IntentContext(
            text="撤回。",
            shortcuts=("撤销",),
        ))

        self.assertEqual(result, {"type": "shortcut", "name": "撤销"})
        llm.chat.assert_not_called()

    def test_exact_shortcut_utterance_is_classified_locally(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"x"}'

        result = classify_intent(llm, IntentContext(
            text="加粗。",
            shortcuts=("加粗", "撤销", "确认"),
        ))

        self.assertEqual(result, {"type": "shortcut", "name": "加粗"})
        llm.chat.assert_not_called()

    def test_common_save_alias_is_classified_locally(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"x"}'

        result = classify_intent(llm, IntentContext(
            text="\u5e2e\u6211\u4fdd\u5b58\u4e00\u4e0b",
            shortcuts=("\u4fdd\u5b58", "\u64a4\u9500", "\u786e\u8ba4"),
        ))

        self.assertEqual(result, {"type": "shortcut", "name": "\u4fdd\u5b58"})
        llm.chat.assert_not_called()

    def test_common_send_alias_is_classified_locally(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"x"}'

        result = classify_intent(llm, IntentContext(
            text="\u53d1\u51fa\u53bb",
            shortcuts=("\u53d1\u9001", "\u64a4\u9500", "\u786e\u8ba4"),
        ))

        self.assertEqual(result, {"type": "shortcut", "name": "\u53d1\u9001"})
        llm.chat.assert_not_called()

    def test_structured_shortcut_alias_is_classified_locally(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"x"}'

        result = classify_intent(llm, IntentContext(
            text="\u53d1\u4e00\u4e0b",
            shortcuts=("\u53d1\u9001",),
            shortcut_entries=(ShortcutIntentEntry(
                name="\u53d1\u9001",
                aliases=("\u53d1\u4e00\u4e0b",),
            ),),
        ))

        self.assertEqual(result, {"type": "shortcut", "name": "\u53d1\u9001"})
        llm.chat.assert_not_called()

    def test_intent_details_include_local_source_and_confidence(self):
        llm = MagicMock()

        details = classify_intent_details(llm, IntentContext(
            text="\u53d1\u51fa\u53bb",
            shortcuts=("\u53d1\u9001",),
        ))

        self.assertEqual(details.source, "local")
        self.assertEqual(details.confidence, "high")
        self.assertEqual(details.result["_intent_source"], "local")
        llm.chat.assert_not_called()

    def test_llm_intent_result_is_cached(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"x"}'
        ctx = IntentContext(
            text="\u8fd9\u4e2a\u6309\u94ae\u600e\u4e48\u7528",
            active_application="Test App",
            shortcuts=("\u4fdd\u5b58",),
        )

        first = classify_intent_details(llm, ctx)
        second = classify_intent_details(llm, ctx)

        self.assertEqual(first.source, "llm")
        self.assertEqual(second.source, "cache")
        self.assertTrue(second.cache_hit)
        self.assertEqual(llm.chat.call_count, 1)

    def test_plain_left_side_utterance_matches_window_shortcut_catalog(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"shortcut","name":""}'

        result = classify_intent(llm, IntentContext(
            text="放到左边。",
            shortcuts=("窗口左半屏", "窗口右半屏", "窗口最大化"),
        ))

        self.assertEqual(result, {"type": "shortcut", "name": "窗口左半屏"})

    def test_application_window_left_utterance_matches_window_shortcut_catalog(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"shortcut","name":""}'

        result = classify_intent(llm, IntentContext(
            text="应用窗口放左边。",
            shortcuts=("窗口左半屏", "窗口右半屏", "窗口最大化"),
        ))

        self.assertEqual(result, {"type": "shortcut", "name": "窗口左半屏"})

    def test_macos_window_utterance_uses_clear_available_alias(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"我不能调整窗口"}'

        result = classify_intent(llm, IntentContext(
            text="窗口右移。",
            shortcuts=("窗口左移", "窗口右移"),
        ))

        self.assertEqual(result, {"type": "shortcut", "name": "窗口右移"})

    def test_spreadsheet_search_is_not_rewritten_without_surface_context(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"请打开表格里的查找功能"}'

        result = classify_intent(llm, IntentContext(
            text="表格查找。",
            active_application="飞书 (com.bytedance.macos.feishu)",
            shortcuts=("加粗", "撤销", "确认"),
        ))

        self.assertEqual(result, {"type": "chat", "reply": "请打开表格里的查找功能"})

    def test_plain_feishu_common_shortcut_stays_shortcut(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"shortcut","name":"加粗"}'

        result = classify_intent(llm, IntentContext(
            text="加粗",
            active_application="飞书 (com.bytedance.macos.feishu)",
            shortcuts=("加粗", "撤销", "确认"),
        ))

        self.assertEqual(result, {"type": "shortcut", "name": "加粗"})

    def test_current_runtime_asks_to_split_multi_step_instruction(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"edit"}'

        result = classify_intent(llm, IntentContext(
            text="先删掉第一句，然后把剩下的润色",
            recent_text="第一句。第二句。",
        ))

        self.assertEqual(result, {
            "type": "chat",
            "reply": "这个需要分步执行，请先说第一步",
        })

    def test_current_runtime_asks_to_split_same_kind_multi_step_instruction(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"shortcut","name":"保存"}'

        result = classify_intent(llm, IntentContext(
            text="保存然后关闭标签",
            shortcuts=("保存", "关闭标签"),
        ))

        self.assertEqual(result, {
            "type": "chat",
            "reply": "这个需要分步执行，请先说第一步",
        })


if __name__ == "__main__":
    unittest.main()
