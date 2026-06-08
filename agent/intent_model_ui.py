"""Helpers for Mac UI intent-model actions."""

from __future__ import annotations

import time
from pathlib import Path

from agent.intent_evaluation import write_evaluation_report
from agent.intent_model import list_intent_model_versions, load_intent_model, rollback_intent_model, train_intent_model


def get_model_status(registry_dir: Path | str) -> dict:
    registry = Path(registry_dir).expanduser()
    versions = list_intent_model_versions(registry)
    current = next((item for item in versions if item.get("current")), None)
    return {
        "registry_dir": str(registry),
        "current_version": str((current or {}).get("version") or ""),
        "version_count": len(versions),
        "versions": versions,
    }


def train_local_model_for_ui(
    *,
    sample_path: Path | str,
    registry_dir: Path | str,
    report_dir: Path | str,
    override_path: Path | str,
    version: str = "",
    min_similarity: float = 1.0,
) -> dict:
    registry = Path(registry_dir).expanduser()
    current_path = registry / "current.json"
    model_version = version or time.strftime("ui-%Y%m%d-%H%M%S")
    model = train_intent_model(
        sample_path,
        current_path,
        version=model_version,
        registry_dir=registry,
    )
    evaluation = write_evaluation_report(
        sample_path,
        report_dir,
        override_path=override_path,
        intent_model_path=current_path,
        intent_model_min_similarity=min_similarity,
        version=model["version"],
    )
    status = get_model_status(registry)
    return {
        "model": model,
        "evaluation": evaluation,
        "status": status,
    }


def rollback_model_for_ui(registry_dir: Path | str) -> dict:
    summary = rollback_intent_model(registry_dir)
    model = load_intent_model(summary["current"])
    return {
        **summary,
        "examples": len(model.examples) if model is not None else 0,
    }
