"""Offline evaluation for reviewed intent samples."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Mapping

from agent.ai_intent import IntentContext, IntentFallbackOptions, classify_intent
from agent.intent_overrides import normalize_intent


class _FallbackLLM:
    def chat(self, system: str, user: str) -> str:
        return '{"type":"chat","reply":"未命中本地规则"}'


def evaluate_reviewed_samples(
    source: Path | str,
    *,
    override_path: Path | str | None = None,
) -> dict:
    cases = list(_evaluation_cases(_load_jsonl(Path(source).expanduser())))
    correct = 0
    mismatches = []
    for case in cases:
        expected = normalize_intent(case["expected"])
        actual = _classify_case(case, override_path=override_path)
        if _intent_matches(actual, expected):
            correct += 1
        else:
            mismatches.append({
                "text": case["text"],
                "expected": expected,
                "actual": actual,
            })
    total = len(cases)
    accuracy = correct / total if total else 0.0
    return {
        "total": total,
        "correct": correct,
        "wrong": total - correct,
        "accuracy": accuracy,
        "accuracy_label": f"{accuracy * 100:.1f}%",
        "mismatches": mismatches,
    }


def _classify_case(case: dict, *, override_path: Path | str | None) -> dict:
    expected = normalize_intent(case["expected"])
    shortcuts = tuple(case.get("shortcut_names") or ())
    if expected.get("type") == "shortcut" and expected.get("name") and expected["name"] not in shortcuts:
        shortcuts = shortcuts + (expected["name"],)
    fallback_kwargs = {"llm_cache": False}
    if override_path is not None:
        fallback_kwargs["intent_overrides_path"] = str(override_path)
    return classify_intent(
        _FallbackLLM(),
        IntentContext(
            text=str(case.get("text") or ""),
            shortcuts=shortcuts,
        ),
        IntentFallbackOptions(**fallback_kwargs),
    )


def _evaluation_cases(rows: Iterable[Mapping]) -> Iterable[dict]:
    for row in rows:
        corrected = row.get("corrected_intent")
        if not isinstance(corrected, Mapping) or not corrected.get("type"):
            continue
        text = str(row.get("text") or "")
        if not text:
            continue
        yield {
            "text": text,
            "expected": corrected,
            "shortcut_names": _shortcut_names(row),
        }


def _shortcut_names(row: Mapping) -> tuple[str, ...]:
    names = row.get("shortcut_names")
    if isinstance(names, list):
        return tuple(str(name) for name in names if name)
    count = int(row.get("shortcut_count") or 0)
    return () if count else ()


def _intent_matches(actual: Mapping, expected: Mapping) -> bool:
    expected_type = str(expected.get("type") or "")
    if str(actual.get("type") or "") != expected_type:
        return False
    if expected_type == "shortcut":
        return str(actual.get("name") or "") == str(expected.get("name") or "")
    if expected_type in {"memo_save", "memo_recall", "memo_delete"}:
        return str(actual.get("key") or "") == str(expected.get("key") or "")
    return True


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows
