"""Sync reviewed corrected intents into local overrides."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Mapping

from agent.intent_overrides import append_override, compact_overrides


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
    compacted = compact_overrides(path=override_path)
    return {
        "synced": synced,
        "skipped": skipped,
        "compacted": compacted.get("removed", 0),
    }


def sync_local_corrected_intents(
    sample_path: Path | str,
    *,
    override_path: Path | str,
) -> dict:
    rows = []
    source = Path(sample_path).expanduser()
    if not source.exists():
        return {"synced": 0, "skipped": 0}
    for line in source.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, Mapping):
            rows.append(row)
    return sync_corrected_intents(rows, override_path=override_path)
