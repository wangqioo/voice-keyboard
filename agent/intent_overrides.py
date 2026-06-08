"""Local corrected-intent overrides built from reviewed samples."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Mapping

_DEFAULT_PATH = Path("~/.voice-keyboard/intent_overrides.jsonl").expanduser()

_SUPPORTED_TYPES = {
    "shortcut",
    "undo",
    "delete",
    "edit",
    "write",
    "memo_save",
    "memo_recall",
    "memo_delete",
    "memo_list",
    "chat",
}


def normalize_instruction_text(text: str) -> str:
    return "".join(
        char for char in str(text or "").strip().lower()
        if char not in " \t\r\n。.!！?？,，;；:：\"'“”‘’"
    )


def append_override(
    text: str,
    intent: Mapping,
    *,
    path: Path | str = _DEFAULT_PATH,
) -> dict:
    clean_intent = normalize_intent(intent)
    text_key = normalize_instruction_text(text)
    if not text_key:
        raise ValueError("override text cannot be empty")
    row = {
        "ts": time.time(),
        "text": str(text or "")[:240],
        "text_key": text_key,
        "intent": clean_intent,
    }
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def find_override(
    text: str,
    *,
    path: Path | str = _DEFAULT_PATH,
) -> dict | None:
    text_key = normalize_instruction_text(text)
    if not text_key:
        return None
    return load_overrides(path=path).get(text_key)


def load_overrides(*, path: Path | str = _DEFAULT_PATH) -> dict[str, dict]:
    source = Path(path).expanduser()
    if not source.exists():
        return {}
    overrides: dict[str, dict] = {}
    for line in source.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            text_key = str(row.get("text_key") or "")
            intent = normalize_intent(row.get("intent") or {})
        except Exception:
            continue
        if text_key:
            overrides[text_key] = intent
    return overrides


def compact_overrides(*, path: Path | str = _DEFAULT_PATH) -> dict:
    target = Path(path).expanduser()
    if not target.exists():
        return {"kept": 0, "removed": 0}
    latest: dict[str, dict] = {}
    valid_rows = 0
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            text_key = str(row.get("text_key") or "")
            intent = normalize_intent(row.get("intent") or {})
        except Exception:
            continue
        if not text_key:
            continue
        valid_rows += 1
        latest[text_key] = {
            "ts": float(row.get("ts") or time.time()),
            "text": str(row.get("text") or "")[:240],
            "text_key": text_key,
            "intent": intent,
        }
    rows = list(latest.values())
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"kept": len(rows), "removed": max(0, valid_rows - len(rows))}


def normalize_intent(intent: Mapping) -> dict:
    if not isinstance(intent, Mapping):
        raise ValueError("corrected intent must be an object")
    intent_type = str(intent.get("type") or "").strip()
    if intent_type not in _SUPPORTED_TYPES:
        raise ValueError(f"unsupported corrected intent type: {intent_type}")
    clean: dict[str, str] = {"type": intent_type}
    if intent_type == "shortcut":
        name = str(intent.get("name") or "").strip()
        if not name:
            raise ValueError("shortcut override requires name")
        clean["name"] = name[:120]
    elif intent_type in {"memo_save", "memo_recall", "memo_delete"}:
        key = str(intent.get("key") or "").strip()
        if not key:
            raise ValueError(f"{intent_type} override requires key")
        clean["key"] = key[:120]
        if intent_type == "memo_save":
            clean["value"] = str(intent.get("value") or "")[:240]
    elif intent_type == "chat":
        reply = str(intent.get("reply") or "").strip()
        clean["reply"] = (reply or "我先不执行这个操作")[:120]
    return clean
