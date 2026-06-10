"""Offline evaluation for reviewed intent samples."""

from __future__ import annotations

import json
import time
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
    intent_model_path: Path | str | None = None,
    intent_model_min_similarity: float = 1.0,
) -> dict:
    cases = list(_evaluation_cases(_load_jsonl(Path(source).expanduser())))
    correct = 0
    mismatches = []
    for case in cases:
        expected = normalize_intent(case["expected"])
        actual = _classify_case(
            case,
            override_path=override_path,
            intent_model_path=intent_model_path,
            intent_model_min_similarity=intent_model_min_similarity,
        )
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


def build_evaluation_dataset(source: Path | str, output: Path | str, *, limit: int | None = None) -> dict:
    rows = _load_jsonl(Path(source).expanduser())
    cases = []
    seen = set()
    for case in _evaluation_cases(rows):
        expected = normalize_intent(case["expected"])
        key = (case["text"], json.dumps(expected, ensure_ascii=False, sort_keys=True))
        if key in seen:
            continue
        seen.add(key)
        cases.append({
            "text": case["text"],
            "expected": expected,
            "shortcut_names": list(case.get("shortcut_names") or ()),
        })
        if limit is not None and len(cases) >= max(0, limit):
            break

    out_path = Path(output).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        "".join(json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n" for case in cases),
        encoding="utf-8",
    )
    return {
        "source": str(Path(source).expanduser()),
        "output": str(out_path),
        "source_total": len(rows),
        "written": len(cases),
    }


def write_evaluation_report(
    source: Path | str,
    report_dir: Path | str,
    *,
    override_path: Path | str | None = None,
    intent_model_path: Path | str | None = None,
    intent_model_min_similarity: float = 1.0,
    version: str | None = None,
) -> dict:
    report = evaluate_reviewed_samples(
        source,
        override_path=override_path,
        intent_model_path=intent_model_path,
        intent_model_min_similarity=intent_model_min_similarity,
    )
    report = {
        **report,
        "source": str(Path(source).expanduser()),
        "override_path": str(Path(override_path).expanduser()) if override_path is not None else "",
        "intent_model_path": str(Path(intent_model_path).expanduser()) if intent_model_path is not None else "",
        "intent_model_min_similarity": float(intent_model_min_similarity),
        "created_at": time.time(),
    }
    clean_version = _safe_version(version or time.strftime("%Y%m%d-%H%M%S"))
    out_dir = Path(report_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{clean_version}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "path": str(out_path),
        "report": report,
    }


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

def _classify_case(
    case: dict,
    *,
    override_path: Path | str | None,
    intent_model_path: Path | str | None,
    intent_model_min_similarity: float,
) -> dict:
    expected = normalize_intent(case.get("expected") or case.get("corrected_intent") or {})
    shortcuts = tuple(case.get("shortcut_names") or ())
    if expected.get("type") == "shortcut" and expected.get("name") and expected["name"] not in shortcuts:
        shortcuts = shortcuts + (expected["name"],)
    fallback_kwargs = {"llm_cache": False}
    if override_path is not None:
        fallback_kwargs["intent_overrides_path"] = str(override_path)
    if intent_model_path is not None:
        fallback_kwargs["intent_model"] = True
        fallback_kwargs["intent_model_path"] = str(intent_model_path)
        fallback_kwargs["intent_model_min_similarity"] = float(intent_model_min_similarity)
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
        corrected = row.get("expected") or row.get("corrected_intent")
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


def _safe_version(value: str) -> str:
    clean = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in str(value))
    return clean.strip(".-") or "report"
