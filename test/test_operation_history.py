import unittest

from agent.operation_history import OperationEffect, OperationHistory


class OperationHistoryTests(unittest.TestCase):
    def test_history_keeps_configured_limit(self):
        history = OperationHistory(limit=2)

        history.push(OperationEffect.insert("one"))
        history.push(OperationEffect.insert("two"))
        history.push(OperationEffect.insert("three"))

        self.assertEqual(history.snapshot(), (
            OperationEffect.insert("two"),
            OperationEffect.insert("three"),
        ))

    def test_pop_returns_latest_effect_first(self):
        history = OperationHistory()
        replace = OperationEffect.replace("old", "new")
        delete = OperationEffect.delete("gone")

        history.push(replace)
        history.push(delete)

        self.assertEqual(history.pop(), delete)
        self.assertEqual(history.pop(), replace)
        self.assertIsNone(history.pop())

    def test_effect_constructors_name_reversal_shape(self):
        self.assertEqual(
            OperationEffect.replace("old", "new"),
            OperationEffect("replace", old_text="old", new_text="new"),
        )
        self.assertEqual(
            OperationEffect.insert("new"),
            OperationEffect("insert", new_text="new"),
        )
        self.assertEqual(
            OperationEffect.delete("old"),
            OperationEffect("delete", old_text="old"),
        )


if __name__ == "__main__":
    unittest.main()
