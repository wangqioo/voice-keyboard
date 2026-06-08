# AI Intent Accuracy Next Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the current Mac AI intent training loop into a measurable, safer accuracy-improvement pipeline using real samples, model comparisons, activation guards, and review tooling.

**Architecture:** Keep the existing local-first pipeline: samples stay in JSONL, corrections become overrides, models live under `~/.voice-keyboard/intent_models`, and reports live under `~/.voice-keyboard/intent_eval_reports`. New work should add small helpers around existing `agent.intent_evaluation`, `agent.intent_model`, `agent.intent_loop`, and Mac UI code rather than replacing the current runtime.

**Tech Stack:** Python 3, unittest, PyObjC/AppKit for Mac UI, FastAPI training server, JSONL/JSON local artifacts, existing `scripts/test-local.sh`.

---

## Current Baseline

Already implemented and pushed:

- Mac intent diagnostics tab.
- Local `corrected_intent` review and local override sync.
- Remote training server upload/sync.
- Offline evaluation datasets and versioned JSON reports.
- Local lightweight intent model training.
- High-threshold similar-expression matching.
- Model report comparison via `tools/evaluate_intent_samples.py`.
- Model registry, current model activation, and rollback.
- One-command loop that can sync corrections, train a model, and write a model report.
- Mac UI buttons for model training and rollback.

Do not re-implement these. Build on them.

## Files To Touch

- Modify: `agent/intent_evaluation.py`
  - Add comparison summaries between baseline and model reports.
- Modify: `agent/intent_loop.py`
  - Add model activation guard data to the loop result.
- Modify: `agent/intent_model_ui.py`
  - Expose latest model report summary for Mac UI.
- Modify: `agent/ui/main_window.py`
  - Show latest model accuracy and mismatch count.
- Modify: `training_server/review_page.py`
  - Add export/report links to the existing review HTML.
- Modify: `docs/stage-development-plan.md`
  - Keep progress and risks current after each completed task.
- Tests:
  - `test/test_intent_evaluation.py`
  - `test/test_intent_loop.py`
  - `test/test_intent_model_ui.py`
  - Existing training-server review page tests.

## Task 1: Baseline vs Model Comparison Summary

**Files:**
- Modify: `agent/intent_evaluation.py`
- Test: `test/test_intent_evaluation.py`

- [ ] **Step 1: Write the failing test**

Add a test that creates two report dicts and expects a comparison summary:

```python
def test_compare_evaluation_reports_shows_delta_and_regression():
    from agent.intent_evaluation import compare_evaluation_reports

    baseline = {"total": 10, "correct": 7, "wrong": 3, "accuracy": 0.7, "mismatches": [{"text": "a"}]}
    model = {"total": 10, "correct": 8, "wrong": 2, "accuracy": 0.8, "mismatches": [{"text": "b"}]}

    summary = compare_evaluation_reports(baseline, model)

    self.assertEqual(summary["accuracy_delta"], 0.1)
    self.assertEqual(summary["correct_delta"], 1)
    self.assertEqual(summary["wrong_delta"], -1)
    self.assertFalse(summary["regressed"])
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
.venv/bin/python -m unittest discover -s test -p 'test_intent_evaluation.py' -v
```

Expected: fails because `compare_evaluation_reports` does not exist.

- [ ] **Step 3: Implement minimal comparison helper**

Add:

```python
def compare_evaluation_reports(baseline: Mapping, candidate: Mapping) -> dict:
    baseline_accuracy = float(baseline.get("accuracy") or 0.0)
    candidate_accuracy = float(candidate.get("accuracy") or 0.0)
    baseline_correct = int(baseline.get("correct") or 0)
    candidate_correct = int(candidate.get("correct") or 0)
    baseline_wrong = int(baseline.get("wrong") or 0)
    candidate_wrong = int(candidate.get("wrong") or 0)
    return {
        "baseline_accuracy": baseline_accuracy,
        "candidate_accuracy": candidate_accuracy,
        "accuracy_delta": round(candidate_accuracy - baseline_accuracy, 6),
        "correct_delta": candidate_correct - baseline_correct,
        "wrong_delta": candidate_wrong - baseline_wrong,
        "baseline_mismatches": len(baseline.get("mismatches") or []),
        "candidate_mismatches": len(candidate.get("mismatches") or []),
        "regressed": candidate_accuracy < baseline_accuracy or candidate_wrong > baseline_wrong,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run the same unittest command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/intent_evaluation.py test/test_intent_evaluation.py
git commit -m "Compare intent evaluation reports"
```

## Task 2: Activation Guard In Training Loop

**Files:**
- Modify: `agent/intent_loop.py`
- Test: `test/test_intent_loop.py`

- [ ] **Step 1: Write the failing test**

Add a test proving a candidate model report lower than baseline marks activation unsafe:

```python
def test_run_training_loop_marks_regressed_model_activation_unsafe(self):
    from agent.intent_loop import _model_activation_decision

    decision = _model_activation_decision(
        baseline={"accuracy": 0.9, "correct": 9, "wrong": 1, "mismatches": []},
        candidate={"accuracy": 0.8, "correct": 8, "wrong": 2, "mismatches": [{"text": "bad"}]},
    )

    self.assertFalse(decision["should_activate"])
    self.assertEqual(decision["reason"], "candidate_regressed")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m unittest discover -s test -p 'test_intent_loop.py' -v
```

Expected: fails because `_model_activation_decision` does not exist.

- [ ] **Step 3: Implement minimal decision helper**

Use `compare_evaluation_reports`:

```python
def _model_activation_decision(*, baseline: dict, candidate: dict) -> dict:
    comparison = compare_evaluation_reports(baseline, candidate)
    should_activate = not comparison["regressed"]
    return {
        "should_activate": should_activate,
        "reason": "candidate_ok" if should_activate else "candidate_regressed",
        "comparison": comparison,
    }
```

Keep the first version report-only. Do not automatically undo already-activated `current.json` in this task.

- [ ] **Step 4: Include decision in loop result**

When `run_training_loop` writes `model_evaluation`, add:

```python
report["model_activation"] = _model_activation_decision(
    baseline=evaluation,
    candidate=report["model_evaluation"]["report"],
)
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/python -m unittest discover -s test -p 'test_intent_loop.py' -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agent/intent_loop.py test/test_intent_loop.py
git commit -m "Add intent model activation guard"
```

## Task 3: Show Latest Model Report In Mac UI

**Files:**
- Modify: `agent/intent_model_ui.py`
- Modify: `agent/ui/main_window.py`
- Test: `test/test_intent_model_ui.py`

- [ ] **Step 1: Write failing helper test**

```python
def test_get_latest_model_report_summary_reads_newest_report(self):
    from agent.intent_model_ui import get_latest_model_report_summary

    with tempfile.TemporaryDirectory() as td:
        reports = Path(td)
        (reports / "old.json").write_text('{"accuracy_label":"50.0%","wrong":1,"total":2}', encoding="utf-8")
        (reports / "new.json").write_text('{"accuracy_label":"100.0%","wrong":0,"total":2}', encoding="utf-8")

        summary = get_latest_model_report_summary(reports)

        self.assertEqual(summary["accuracy_label"], "100.0%")
        self.assertEqual(summary["wrong"], 0)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m unittest discover -s test -p 'test_intent_model_ui.py' -v
```

- [ ] **Step 3: Implement helper**

Sort report files by `stat().st_mtime`, parse newest JSON, and return `{}` if none exists.

- [ ] **Step 4: Update Mac UI label**

In `_IntentDiagnosticsTab._refresh_model_status`, append latest report accuracy:

```python
report = get_latest_model_report_summary(_INTENT_MODEL_REPORTS)
if report:
    text += f" / 最近评测 {report.get('accuracy_label', '-')} 错例 {report.get('wrong', 0)}"
```

- [ ] **Step 5: Run tests and compile**

```bash
.venv/bin/python -m unittest discover -s test -p 'test_intent_model_ui.py' -v
.venv/bin/python -m compileall agent tools
```

- [ ] **Step 6: Commit**

```bash
git add agent/intent_model_ui.py agent/ui/main_window.py test/test_intent_model_ui.py
git commit -m "Show latest intent model report in Mac UI"
```

## Task 4: Review Page Export And Report Links

**Files:**
- Modify: `training_server/review_page.py`
- Test: `test/test_training_server_review_page.py`

- [ ] **Step 1: Add failing test**

In the existing review page test, assert the HTML includes:

```python
self.assertIn("Export Evaluation Dataset", html)
self.assertIn("Model Reports", html)
self.assertIn("Sync Status", html)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m unittest discover -s test -p 'test_training_server_review_page.py' -v
```

- [ ] **Step 3: Add minimal links/sections**

Add static UI affordances first. Do not implement full server endpoints in this task unless the failing test requires it.

- [ ] **Step 4: Run test**

```bash
.venv/bin/python -m unittest discover -s test -p 'test_training_server_review_page.py' -v
```

- [ ] **Step 5: Commit**

```bash
git add training_server test/test_training_server_review_page.py
git commit -m "Add review page model report links"
```

## Task 5: End-To-End Verification And Documentation

**Files:**
- Modify: `docs/stage-development-plan.md`
- Possibly modify: `docs/intent-training.md`

- [ ] **Step 1: Run targeted tests**

```bash
.venv/bin/python -m unittest discover -s test -p 'test_intent_evaluation.py' -v
.venv/bin/python -m unittest discover -s test -p 'test_intent_loop.py' -v
.venv/bin/python -m unittest discover -s test -p 'test_intent_model_ui.py' -v
.venv/bin/python -m unittest discover -s test -p 'test_training_server_review_page.py' -v
```

Expected: all PASS.

- [ ] **Step 2: Run compile and diff check**

```bash
.venv/bin/python -m compileall agent tools training_server
git diff --check
```

Expected: exit 0.

- [ ] **Step 3: Run full local test script**

```bash
scripts/test-local.sh
```

Expected: all tests PASS; `test_typing.py` remains skipped unless `--include-typing` is passed.

- [ ] **Step 4: Update docs**

Record the completed tasks, latest commits, and remaining risks in `docs/stage-development-plan.md`.

- [ ] **Step 5: Commit and push**

```bash
git add docs/stage-development-plan.md docs/intent-training.md
git commit -m "Update intent accuracy development plan"
git push
```

## Done Criteria

- The latest model report is visible from Mac UI status text.
- The loop result includes a model activation decision.
- Review page exposes report/export affordances.
- All targeted tests pass.
- `scripts/test-local.sh` passes.
- The stage plan reflects the actual current state and remaining work.
