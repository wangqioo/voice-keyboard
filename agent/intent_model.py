"""Lightweight local intent model built from corrected samples."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from agent.intent_overrides import normalize_instruction_text, normalize_intent


@dataclass(frozen=True)
class IntentModel:
    examples: dict[str, dict]
    version: str = ""

    def match(self, text: str, *, min_similarity: float = 0.0) -> dict | None:
        text_key = normalize_instruction_text(text)
        if not text_key:
            return None
        intent = self.examples.get(text_key)
        if intent:
            return dict(intent)
        if min_similarity <= 0 or min_similarity >= 1.0:
            return None
        best_intent = None
        best_score = 0.0
        for candidate_key, candidate_intent in self.examples.items():
            score = _text_similarity(text_key, candidate_key)
            if score > best_score:
                best_score = score
                best_intent = candidate_intent
        return dict(best_intent) if best_intent and best_score >= min_similarity else None


def train_intent_model(source: Path | str, output: Path | str, *, version: str = "") -> dict:
    rows = _load_jsonl(Path(source).expanduser())
    examples: dict[str, dict] = {}
    source_total = 0
    skipped = 0
    for row in rows:
        source_total += 1
        text = str(row.get("text") or "")
        text_key = normalize_instruction_text(text)
        corrected = row.get("expected") or row.get("corrected_intent")
        if not text_key or not isinstance(corrected, Mapping):
            skipped += 1
            continue
        try:
            examples[text_key] = normalize_intent(corrected)
        except Exception:
            skipped += 1

    payload = {
        "version": version or time.strftime("%Y%m%d-%H%M%S"),
        "created_at": time.time(),
        "examples": examples,
    }
    out_path = Path(output).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "source": str(Path(source).expanduser()),
        "output": str(out_path),
        "source_total": source_total,
        "examples": len(examples),
        "skipped": skipped,
        "version": payload["version"],
    }


def load_intent_model(path: Path | str) -> IntentModel | None:
    source = Path(path).expanduser()
    if not source.exists():
        return None
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except Exception:
        return None
    raw_examples = payload.get("examples") if isinstance(payload, dict) else None
    if not isinstance(raw_examples, dict):
        return None
    examples: dict[str, dict] = {}
    for text_key, intent in raw_examples.items():
        if not text_key or not isinstance(intent, Mapping):
            continue
        try:
            examples[str(text_key)] = normalize_intent(intent)
        except Exception:
            continue
    return IntentModel(examples=examples, version=str(payload.get("version") or ""))


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


def _text_similarity(left: str, right: str) -> float:
    if left == right:
        return 1.0
    left_parts = _char_ngrams(left)
    right_parts = _char_ngrams(right)
    if not left_parts or not right_parts:
        return 0.0
    overlap = len(left_parts & right_parts)
    jaccard = overlap / len(left_parts | right_parts)
    containment = overlap / min(len(left_parts), len(right_parts))
    return max(jaccard, containment)


def _char_ngrams(text: str) -> set[str]:
    clean = str(text or "")
    if len(clean) <= 1:
        return {clean} if clean else set()
    return {clean[i:i + 2] for i in range(len(clean) - 1)}
