"""Helpers for detecting unsafe local configuration secrets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_SECRET_KEYS = {
    "api_key",
    "token",
    "secret",
    "password",
    "passwd",
    "access_key",
    "access_key_secret",
    "access_token",
}


def find_plaintext_secrets(config_path: Path | str) -> list[dict]:
    """Return secret-looking YAML entries that are literal values.

    Environment placeholders such as ``${LLM_API_KEY}`` and ``$LLM_API_KEY`` are
    considered safe references. Findings intentionally omit the secret value.
    """
    path = Path(config_path).expanduser()
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    try:
        parsed = yaml.safe_load(text) or {}
    except Exception:
        return []
    line_index = _secret_line_index(text)
    findings = []
    for key_path, value in _walk_secret_values(parsed):
        if not _is_plaintext_secret(value):
            continue
        dotted = ".".join(key_path)
        findings.append({
            "path": dotted,
            "line": line_index.get(dotted, 0),
        })
    return findings


def _walk_secret_values(value: Any, prefix: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], Any]]:
    if isinstance(value, dict):
        rows = []
        for key, child in value.items():
            key_text = str(key)
            next_prefix = (*prefix, key_text)
            if _is_secret_key(key_text):
                rows.append((next_prefix, child))
            rows.extend(_walk_secret_values(child, next_prefix))
        return rows
    if isinstance(value, list):
        rows = []
        for index, child in enumerate(value):
            rows.extend(_walk_secret_values(child, (*prefix, str(index))))
        return rows
    return []


def _is_secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in _SECRET_KEYS or normalized.endswith("_api_key") or normalized.endswith("_token")


def _is_plaintext_secret(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    return not (text.startswith("${") and text.endswith("}")) and not text.startswith("$")


def _secret_line_index(text: str) -> dict[str, int]:
    stack: list[tuple[int, str]] = []
    index: dict[str, int] = {}
    for number, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        key = stripped.split(":", 1)[0].strip().strip("'\"")
        while stack and stack[-1][0] >= indent:
            stack.pop()
        path = ".".join([part for _, part in stack] + [key])
        if _is_secret_key(key):
            index[path] = number
        if not stripped.endswith(":"):
            continue
        stack.append((indent, key))
    return index
