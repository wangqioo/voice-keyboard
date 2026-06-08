import tempfile
import unittest
from pathlib import Path


class IntentDiagnosticsTests(unittest.TestCase):
    def test_load_diagnostics_rows_returns_newest_first_with_source_index(self):
        from agent.intent_diagnostics import load_diagnostics_rows

        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "samples.jsonl"
            source.write_text(
                '{"ts": 100, "text": "one", "intent_type": "chat"}\n'
                '{"ts": 200, "text": "two", "intent_type": "shortcut"}\n',
                encoding="utf-8",
            )

            rows = load_diagnostics_rows(source, limit=10)

            self.assertEqual([row["text"] for row in rows], ["two", "one"])
            self.assertEqual([row["source_index"] for row in rows], [1, 0])

    def test_load_diagnostics_rows_filters_by_intent_type(self):
        from agent.intent_diagnostics import load_diagnostics_rows

        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "samples.jsonl"
            source.write_text(
                '{"ts": 100, "text": "one", "intent_type": "chat"}\n'
                '{"ts": 200, "text": "two", "intent_type": "shortcut"}\n'
                '{"ts": 300, "text": "three", "intent_type": "chat"}\n',
                encoding="utf-8",
            )

            rows = load_diagnostics_rows(source, limit=10, intent_type="chat")

            self.assertEqual([row["text"] for row in rows], ["three", "one"])
            self.assertEqual([row["source_index"] for row in rows], [2, 0])

    def test_load_diagnostics_rows_filters_by_review_state(self):
        from agent.intent_diagnostics import load_diagnostics_rows

        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "samples.jsonl"
            source.write_text(
                '{"ts": 100, "text": "one", "review_label": ""}\n'
                '{"ts": 200, "text": "two", "review_label": "correct"}\n'
                '{"ts": 300, "text": "three"}\n',
                encoding="utf-8",
            )

            reviewed = load_diagnostics_rows(source, limit=10, review_state="reviewed")
            unreviewed = load_diagnostics_rows(source, limit=10, review_state="unreviewed")

            self.assertEqual([row["text"] for row in reviewed], ["two"])
            self.assertEqual([row["text"] for row in unreviewed], ["three", "one"])

    def test_save_review_updates_underlying_sample(self):
        from agent.intent_diagnostics import load_diagnostics_rows, save_diagnostics_review
        from agent.intent_training import load_samples

        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "samples.jsonl"
            source.write_text(
                '{"ts": 100, "text": "one", "intent_type": "chat"}\n'
                '{"ts": 200, "text": "two", "intent_type": "shortcut"}\n',
                encoding="utf-8",
            )
            newest = load_diagnostics_rows(source, limit=10)[0]

            updated = save_diagnostics_review(
                source,
                newest,
                label="wrong_target",
                note="target should be current input",
            )

            self.assertEqual(updated["review_label"], "wrong_target")
            rows = load_samples(source, limit=0)
            self.assertEqual(rows[1]["review_label"], "wrong_target")
            self.assertEqual(rows[1]["review_note"], "target should be current input")


if __name__ == "__main__":
    unittest.main()
