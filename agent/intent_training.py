"""Local intent-training sample collection.

The collector is intentionally local-only. It records sanitized instruction
metadata that can later be exported for rule tuning or model training.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

_DEFAULT_PATH = Path.home() / ".voice-keyboard" / "intent_samples.jsonl"
_MAX_TEXT_LENGTH = 240
_REVIEW_LABELS = {
    "",
    "correct",
    "wrong_intent",
    "wrong_target",
    "unsafe_should_confirm",
    "missing_shortcut",
    "unclear",
}

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d -]{7,}\d)(?!\d)")
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_SECRET_RE = re.compile(
    r"(?i)\b(?:api[_ -]?key|token|secret|password|passwd|access[_ -]?key)\s*[:=]\s*\S+"
)
_LONG_HEX_RE = re.compile(r"\b[a-fA-F0-9]{24,}\b")


@dataclass(frozen=True)
class IntentTrainingConfig:
    enabled: bool = False
    path: Path = _DEFAULT_PATH
    capture_text: bool = True
    max_text_length: int = _MAX_TEXT_LENGTH

    @classmethod
    def from_config(cls, cfg: dict | None) -> "IntentTrainingConfig":
        if not isinstance(cfg, dict):
            return cls()
        sample_cfg = cfg.get("intent_training") or cfg.get("training") or {}
        if not isinstance(sample_cfg, dict):
            return cls()
        path = Path(str(sample_cfg.get("path") or _DEFAULT_PATH)).expanduser()
        return cls(
            enabled=bool(sample_cfg.get("enabled", False)),
            path=path,
            capture_text=bool(sample_cfg.get("capture_text", True)),
            max_text_length=int(sample_cfg.get("max_text_length", _MAX_TEXT_LENGTH)),
        )


class IntentTrainingRecorder:
    def __init__(self, config: IntentTrainingConfig | None = None):
        self._config = config or IntentTrainingConfig()

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    @property
    def path(self) -> Path:
        return self._config.path

    def record(
        self,
        *,
        text: str,
        active_application: str = "",
        selected: str = "",
        recent_text: str = "",
        shortcuts: Iterable[str] = (),
        intent_result: dict | None = None,
        status: str = "",
        detail: str = "",
    ) -> None:
        if not self._config.enabled:
            return
        result = intent_result or {}
        sample = {
            "ts": time.time(),
            "text": _sanitize_text(text, self._config.max_text_length)
            if self._config.capture_text
            else "",
            "text_hash": _hash_text(text),
            "active_application": _sanitize_text(active_application, 120),
            "has_selection": bool(selected),
            "selected_length": len(selected or ""),
            "has_recent_text": bool(recent_text),
            "recent_text_length": len(recent_text or ""),
            "shortcut_count": len(tuple(shortcuts or ())),
            "intent_type": str(result.get("type") or ""),
            "intent_name": _sanitize_text(str(result.get("name") or ""), 120),
            "intent_key": _sanitize_text(str(result.get("key") or ""), 120),
            "intent_source": str(result.get("_intent_source") or ""),
            "intent_confidence": str(result.get("_intent_confidence") or ""),
            "intent_cache_hit": bool(result.get("_intent_cache_hit")),
            "status": status,
            "detail": _sanitize_text(detail, 240),
            "review_label": "",
            "review_note": "",
        }
        try:
            self._config.path.parent.mkdir(parents=True, exist_ok=True)
            with self._config.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(sample, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[intent-training] write failed: {e}")


def export_samples(
    source: Path | str = _DEFAULT_PATH,
    target: Path | str | None = None,
    *,
    fmt: str = "jsonl",
) -> Path:
    source_path = Path(source).expanduser()
    fmt = fmt.lower()
    if target is None:
        target_path = source_path.with_suffix(".csv" if fmt == "csv" else ".export.jsonl")
    else:
        target_path = Path(target).expanduser()
    rows = _load_samples(source_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "csv":
        _write_csv(target_path, rows)
    elif fmt == "jsonl":
        with target_path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    else:
        raise ValueError("fmt must be 'jsonl' or 'csv'")
    return target_path


def load_samples(
    source: Path | str = _DEFAULT_PATH,
    *,
    limit: int = 300,
) -> list[dict]:
    rows = _load_samples(Path(source).expanduser())
    if limit > 0:
        return rows[-limit:]
    return rows


def update_sample_review(
    source: Path | str,
    index: int,
    *,
    label: str,
    note: str = "",
) -> dict:
    path = Path(source).expanduser()
    rows = _load_samples(path)
    if index < 0 or index >= len(rows):
        raise IndexError("sample index out of range")
    normalized_label = str(label or "").strip()
    if normalized_label not in _REVIEW_LABELS:
        raise ValueError(f"unsupported review label: {normalized_label}")
    rows[index]["review_label"] = normalized_label
    rows[index]["review_note"] = _sanitize_text(note, 240)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return rows[index]


def _load_samples(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def _write_csv(path: Path, rows: list[dict]) -> None:
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _sanitize_text(text: str, limit: int) -> str:
    value = str(text or "")
    value = _SECRET_RE.sub("[SECRET]", value)
    value = _EMAIL_RE.sub("[EMAIL]", value)
    value = _PHONE_RE.sub("[PHONE]", value)
    value = _URL_RE.sub("[URL]", value)
    value = _LONG_HEX_RE.sub("[SECRET]", value)
    value = " ".join(value.split())
    if len(value) > limit:
        return value[:limit] + "..."
    return value


def _hash_text(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:16]
