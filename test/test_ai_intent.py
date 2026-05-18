import unittest
from unittest.mock import MagicMock

from agent.ai_intent import IntentContext, classify_intent


class AIIntentTests(unittest.TestCase):
    def test_selected_edit_instruction_overrides_chat(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"请提供内容"}'

        result = classify_intent(llm, IntentContext(
            text="帮我润色一下",
            selected="这是一段原文",
        ))

        self.assertEqual(result, {"type": "edit"})

    def test_edit_hint_without_selection_but_recent_text_is_still_edit_operation(self):
        llm = MagicMock()
        llm.chat.return_value = '{"type":"chat","reply":"请提供内容"}'

        result = classify_intent(llm, IntentContext(
            text="把上一句翻译成英文",
            recent_text="上一句",
        ))

        self.assertEqual(result, {"type": "edit"})

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

    def test_classifier_keeps_structured_result(self):
        llm = MagicMock()
        llm.chat.return_value = '```json\n{"type":"shortcut","name":"保存"}\n```'

        result = classify_intent(llm, IntentContext(
            text="保存",
            active_application="Codex (com.openai.codex)",
            shortcuts=("保存",),
        ))

        self.assertEqual(result, {"type": "shortcut", "name": "保存"})

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
        self.assertIn("当前活动应用可用快捷键（实验性）：发送", user)


if __name__ == "__main__":
    unittest.main()
