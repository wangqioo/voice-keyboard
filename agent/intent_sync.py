"""Sync reviewed corrected intents into local overrides."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Mapping

from agent.intent_overrides import append_override


def sync_corrected_intents(
    rows: Iterable[Mapping],
    *,
    override_path: Path | str,
) -> dict:
    synced = 0
    skipped = 0
    for row in rows:
        text = str(row.get("text") or "")
        corrected = row.get("corrected_intent")
        if not text or not isinstance(corrected, Mapping) or not corrected.get("type"):
            skipped += 1
            continue
        try:
            append_override(text, corrected, path=override_path)
        except Exception:
            skipped += 1
            continue
        synced += 1
    return {"synced": synced, "skipped": skipped}
