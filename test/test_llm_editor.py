import unittest

from agent.input_environment import ReplacementPlan
from agent.llm_editor import _parse_replacement_plan


class LLMEditorTests(unittest.TestCase):
    def test_parse_replacement_plan_accepts_json_fence(self):
        plan = _parse_replacement_plan(
            '```json\n{"target_text":"旧句子","replacement_text":"新句子","confidence":"high"}\n```'
        )

        self.assertEqual(plan, ReplacementPlan("旧句子", "新句子", "high"))

    def test_parse_replacement_plan_fails_closed_on_invalid_json(self):
        plan = _parse_replacement_plan("不是 JSON")

        self.assertEqual(plan, ReplacementPlan(target_text="", confidence="low"))

    def test_parse_replacement_plan_downgrades_unknown_confidence(self):
        plan = _parse_replacement_plan(
            '{"target_text":"旧句子","replacement_text":"新句子","confidence":"certain"}'
        )

        self.assertEqual(plan, ReplacementPlan("旧句子", "新句子", "low"))


if __name__ == "__main__":
    unittest.main()
