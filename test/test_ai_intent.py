import unittest
from unittest.mock import MagicMock

from agent.ai_intent import IntentContext, IntentFallbackOptions, classify_intent


class AIIntentTests(unittest.TestCase):
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

    def test_chat_can_fuzzy_match_saved_memo_key(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"不知道"}'

        result = classify_intent(llm, IntentContext(
            text="我的手机号是多少",
            memo_keys=("手机号",),
        ))

        self.assertEqual(result, {"type": "memo_recall", "key": "手机号"})

    def test_chat_does_not_fuzzy_match_saved_memo_key_without_lookup_shape(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"不知道"}'

        result = classify_intent(llm, IntentContext(
            text="手机号这个词是什么意思",
            memo_keys=("手机号",),
        ))

        self.assertEqual(result, {"type": "chat", "reply": "不知道"})

    def test_memo_fuzzy_recall_can_be_disabled(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"不知道"}'

        result = classify_intent(
            llm,
            IntentContext(
                text="我的手机号是多少",
                memo_keys=("手机号",),
            ),
            IntentFallbackOptions(memo_fuzzy_recall=False),
        )

        self.assertEqual(result, {"type": "chat", "reply": "不知道"})

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
