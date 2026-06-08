import unittest


class TrainingServerReviewPageTests(unittest.TestCase):
    def test_review_page_contains_review_workflow_controls(self):
        from training_server.review_page import render_review_page

        html = render_review_page()

        self.assertIn("<!doctype html>", html.lower())
        self.assertIn("Voice Keyboard Intent Review", html)
        self.assertIn("/v1/intent-samples", html)
        self.assertIn("/v1/stats", html)
        self.assertIn("Authorization", html)
        self.assertIn("review_label", html)
        self.assertIn("corrected_intent", html)
        self.assertIn("wrong_intent", html)
        self.assertIn("missing_shortcut", html)
        self.assertIn("intent_type", html)
        self.assertIn("tokenInput", html)
        self.assertIn("sampleRows", html)


if __name__ == "__main__":
    unittest.main()
