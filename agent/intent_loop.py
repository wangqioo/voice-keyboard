"""One-command intent training loop helpers."""

from __future__ import annotations

from pathlib import Path

from agent.intent_evaluation import evaluate_reviewed_samples, write_evaluation_report
from agent.intent_model import train_intent_model
from agent.intent_sync import sync_corrected_intents


def run_training_loop(
    *,
    sample_path: Path | str,
    server: str,
    token: str = "",
    override_path: Path | str,
    source: str = "",
    limit: int = 1000,
    http,
    model_registry_dir: Path | str | None = None,
    model_version: str = "",
    model_report_dir: Path | str | None = None,
    model_min_similarity: float = 1.0,
) -> dict:
    headers = {"Content-Type": "application/jsonl"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = Path(sample_path).expanduser().read_text(encoding="utf-8")
    upload_response = http.post(
        server.rstrip("/") + "/v1/intent-samples/batches",
        params={"source": source},
        data=body.encode("utf-8"),
        headers=headers,
        timeout=30,
    )
    upload_response.raise_for_status()

    sync_headers = {}
    if token:
        sync_headers["Authorization"] = f"Bearer {token}"
    corrections_response = http.get(
        server.rstrip("/") + "/v1/intent-samples/corrections",
        params={"limit": limit},
        headers=sync_headers,
        timeout=30,
    )
    corrections_response.raise_for_status()
    rows = corrections_response.json().get("items", [])
    sync = sync_corrected_intents(rows, override_path=override_path)
    evaluation = evaluate_reviewed_samples(sample_path, override_path=override_path)
    report = {
        "upload": upload_response.json(),
        "sync": sync,
        "evaluation": evaluation,
    }
    if model_registry_dir is not None:
        registry = Path(model_registry_dir).expanduser()
        current_model_path = registry / "current.json"
        model = train_intent_model(
            sample_path,
            current_model_path,
            version=model_version,
            registry_dir=registry,
        )
        report["model"] = model
        if model_report_dir is not None:
            report["model_evaluation"] = write_evaluation_report(
                sample_path,
                model_report_dir,
                override_path=override_path,
                intent_model_path=current_model_path,
                intent_model_min_similarity=model_min_similarity,
                version=model["version"],
            )
    return report
