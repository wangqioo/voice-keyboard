"""Intent diagnostics helpers for desktop review UIs."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from agent.intent_training import load_samples, update_sample_review


def load_diagnostics_rows(
    source: Path | str,
    *,
    limit: int = 300,
    intent_type: str = "",
    review_state: str = "",
) -> list[dict]:
    rows = load_samples(source, limit=0)
    indexed = []
    for index, row in enumerate(rows):
        if intent_type and str(row.get("intent_type", "")) != intent_type:
            continue
        review_label = str(row.get("review_label", "") or "")
        if review_state == "reviewed" and not review_label:
            continue
        if review_state == "unreviewed" and review_label:
            continue
        view_row = dict(row)
        view_row["source_index"] = index
        indexed.append(view_row)
    if limit > 0:
        indexed = indexed[-limit:]
    return list(reversed(indexed))


def save_diagnostics_review(
    source: Path | str,
    row: Mapping,
    *,
    label: str,
    note: str = "",
) -> dict:
    index = int(row["source_index"])
    updated = update_sample_review(source, index, label=label, note=note)
    view_row = dict(updated)
    view_row["source_index"] = index
    return view_row
