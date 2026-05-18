"""Small deterministic punctuation cleanup for generated Chinese text."""

from __future__ import annotations

import re


_SPACE_RE = re.compile(r"\s+")
_COLON_AFTER_EXAMPLE_RE = re.compile(r"(例如|比如|包括|如下)(?![：:])")
_EMPTY_COLON_RE = re.compile(r"(例如|比如|包括|如下)[：:][。！？!?]+$")


def normalize_spoken_punctuation(text: str) -> str:
    """Normalize common spoken punctuation names into symbols.

    This is intentionally small and deterministic. Speech Interpretation
    Providers often return literal words such as "冒号" when the user meant the
    punctuation mark, and Instruction Mode writing sometimes misses rhetorical
    punctuation. The cleanup handles clear cases without trying to rewrite prose.
    """
    out = str(text or "")
    if not out:
        return out
    out = _normalize_named_punctuation(out)
    out = _COLON_AFTER_EXAMPLE_RE.sub(r"\1：", out)
    out = _cleanup_symbol_spacing(out)
    out = _EMPTY_COLON_RE.sub(r"\1：", out)
    return out


def _normalize_named_punctuation(text: str) -> str:
    replacements = (
        ("破折号", "——"),
        ("省略号", "……"),
        ("冒号", "："),
        ("分号", "；"),
        ("感叹号", "！"),
        ("叹号", "！"),
        ("问号", "？"),
        ("逗号", "，"),
        ("句号", "。"),
    )
    out = text
    for spoken, symbol in replacements:
        out = out.replace(spoken, symbol)
    return out


def _cleanup_symbol_spacing(text: str) -> str:
    out = _SPACE_RE.sub(" ", text).strip()
    out = re.sub(r"\s*([：；，。！？])\s*", r"\1", out)
    out = re.sub(r"\s*(——|……)\s*", r"\1", out)
    return out
