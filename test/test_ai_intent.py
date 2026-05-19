import unittest
from unittest.mock import MagicMock

from agent.ai_intent import (
    IntentContext,
    IntentFallbackOptions,
    classify_intent,
    reusable_text_memory_records,
)
from agent.reusable_text_memory import ReusableTextMemoryRecord


class AIIntentTests(unittest.TestCase):
    def reusable_text_record(self, key: str, value: str = "") -> ReusableTextMemoryRecord:
        return ReusableTextMemoryRecord(key=key, value=value)

    def test_selected_edit_instruction_overrides_chat_by_default(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"请提供内容"}'

        result = classify_intent(llm, IntentContext(
            text="帮我润色一下",
            selected="这是一段原文",
        ))

        self.assertEqual(result, {"type": "edit"})

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

    def test_edit_hint_without_selection_but_recent_text_does_not_override_by_default(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"请提供内容"}'

        result = classify_intent(llm, IntentContext(
            text="把上一句翻译成英文",
            recent_text="上一句",
        ))

        self.assertEqual(result, {"type": "chat", "reply": "请提供内容"})

    def test_write_request_with_edit_hint_without_target_stays_write(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"write"}'

        result = classify_intent(llm, IntentContext(text="写一封英文邮件"))

        self.assertEqual(result, {"type": "write"})

    def test_chat_can_fuzzy_match_saved_reusable_text_key(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"不知道"}'

        result = classify_intent(llm, IntentContext(
            text="我的手机号是多少",
            reusable_text_memory_records=(self.reusable_text_record("手机号"),),
        ))

        self.assertEqual(result, {"type": "reusable_text_recall", "key": "手机号"})

    def test_reusable_text_recall_from_llm_is_validated_against_request(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"reusable_text_recall","key":"儿子"}'

        result = classify_intent(llm, IntentContext(
            text="我的手机号码是多少",
            reusable_text_memory_records=(
                self.reusable_text_record("儿子"),
                self.reusable_text_record("手机号"),
            ),
        ))

        self.assertEqual(result, {"type": "reusable_text_recall", "key": "手机号"})

    def test_reusable_text_recall_from_llm_rejects_unrelated_key(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"reusable_text_recall","key":"儿子"}'

        result = classify_intent(llm, IntentContext(
            text="我的手机号码是多少",
            reusable_text_memory_records=(self.reusable_text_record("儿子"),),
        ))

        self.assertEqual(result, {"type": "chat", "reply": "没有找到匹配的可复用文本"})

    def test_chat_does_not_fuzzy_match_saved_reusable_text_key_without_lookup_shape(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"不知道"}'

        result = classify_intent(llm, IntentContext(
            text="手机号这个词是什么意思",
            reusable_text_memory_records=(self.reusable_text_record("手机号"),),
        ))

        self.assertEqual(result, {"type": "chat", "reply": "不知道"})

    def test_reusable_text_memory_fuzzy_recall_can_be_disabled(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"不知道"}'

        result = classify_intent(
            llm,
            IntentContext(
                text="我的手机号是多少",
                reusable_text_memory_records=(self.reusable_text_record("手机号"),),
            ),
            IntentFallbackOptions(reusable_text_memory_fuzzy_recall=False),
        )

        self.assertEqual(result, {"type": "chat", "reply": "不知道"})

    def test_legacy_memo_fuzzy_recall_config_still_disables_reusable_text_fallback(self):
        self.assertEqual(
            IntentFallbackOptions.from_config({"memo_fuzzy_recall": False}),
            IntentFallbackOptions(reusable_text_memory_fuzzy_recall=False),
        )

    def test_reusable_text_memory_records_include_personal_aliases(self):
        memory_entries = MagicMock()
        memory_entries.keys.return_value = ["白光宇最喜欢说的话"]
        memory_entries.get.return_value = "大美女"
        lexicon = MagicMock()
        lexicon.aliases_for.return_value = ("小白",)

        records = reusable_text_memory_records(memory_entries, lexicon)

        self.assertEqual(records[0].aliases, ("小白",))
        lexicon.aliases_for.assert_called_once_with("白光宇最喜欢说的话")

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
            text="发送",
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

    def test_macos_window_utterance_matches_system_shortcut_catalog(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"我不能调整窗口"}'

        result = classify_intent(llm, IntentContext(
            text="把窗口移到左边。",
            shortcuts=("窗口左半屏", "窗口右半屏", "窗口最大化"),
        ))

        self.assertEqual(result, {"type": "shortcut", "name": "窗口左半屏"})

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
