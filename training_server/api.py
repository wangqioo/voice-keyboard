"""FastAPI app for intent-training data ingestion and review."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from training_server.config import ServerConfig, sqlite_path_from_url
from training_server.review_page import render_review_page
from training_server.store import IntentTrainingStore, SampleQuery, parse_jsonl


class UploadResponse(BaseModel):
    batch_id: int
    inserted: int


class ReviewRequest(BaseModel):
    label: str = Field(default="")
    note: str = Field(default="")
    corrected_intent: dict | None = Field(default=None)


class PhraseReviewRequest(ReviewRequest):
    text: str


class PublishModelRequest(BaseModel):
    version: str
    model_path: str = Field(default="")
    dataset_version: str = Field(default="")
    evaluation_report: dict = Field(default_factory=dict)
    notes: str = Field(default="")


def _published_model_path(cfg: ServerConfig):
    return Path(cfg.model_dir).expanduser() / "current.json"


def _published_model_meta_path(cfg: ServerConfig):
    return Path(cfg.model_dir).expanduser() / "current.meta.json"


def _published_model_metadata(cfg: ServerConfig) -> dict:
    path = _published_model_path(cfg)
    if not path or not path.exists():
        raise HTTPException(status_code=404, detail="published model not found")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail="published model is invalid") from e
    examples = payload.get("examples") if isinstance(payload, dict) else None
    if not isinstance(examples, dict):
        raise HTTPException(status_code=500, detail="published model is invalid")
    metadata = {
        "version": str(payload.get("version") or ""),
        "examples": len(examples),
        "created_at": float(payload.get("created_at") or 0),
    }
    meta_path = _published_model_meta_path(cfg)
    if meta_path.exists():
        try:
            sidecar = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            sidecar = {}
        if isinstance(sidecar, dict):
            metadata.update({
                key: sidecar[key]
                for key in ("dataset_version", "evaluation_report", "notes", "published_at")
                if key in sidecar
            })
    return metadata


def create_app(config: ServerConfig | None = None) -> FastAPI:
    cfg = config or ServerConfig.from_env()
    store = IntentTrainingStore(sqlite_path_from_url(cfg.database_url))
    app = FastAPI(title="Voice Keyboard Intent Training Server")

    def require_token(authorization: str = Header(default="")) -> None:
        if not cfg.upload_token:
            return
        expected = f"Bearer {cfg.upload_token}"
        if authorization != expected:
            raise HTTPException(status_code=401, detail="invalid token")

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/review", response_class=HTMLResponse)
    def review_page() -> HTMLResponse:
        return HTMLResponse(render_review_page())

    @app.post("/v1/intent-samples/batches", response_model=UploadResponse)
    async def upload_batch(
        request: Request,
        source: str = Query(default=""),
        _auth: None = Depends(require_token),
    ) -> UploadResponse:
        body = (await request.body()).decode("utf-8")
        try:
            samples = parse_jsonl(body)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        batch_id = store.create_batch(source=source)
        inserted = store.insert_samples(batch_id, samples)
        return UploadResponse(batch_id=batch_id, inserted=inserted)

    @app.get("/v1/intent-samples")
    def list_samples(
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        review_label: str | None = None,
        intent_type: str | None = None,
        status: str | None = None,
        text: str | None = None,
        _auth: None = Depends(require_token),
    ) -> dict:
        rows = store.list_samples(SampleQuery(
            limit=limit,
            offset=offset,
            review_label=review_label,
            intent_type=intent_type,
            status=status,
            text=text,
        ))
        return {"items": rows}

    @app.get("/v1/intent-samples/corrections")
    def list_corrections(
        limit: int = Query(default=1000, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        _auth: None = Depends(require_token),
    ) -> dict:
        return {"items": store.list_corrected_samples(limit=limit, offset=offset)}

    @app.get("/v1/intent-phrases")
    def list_phrases(
        limit: int = Query(default=30, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        _auth: None = Depends(require_token),
    ) -> dict:
        return {"items": store.list_phrase_groups(limit=limit, offset=offset)}

    @app.get("/v1/intent-models/published")
    def published_model_metadata(_auth: None = Depends(require_token)) -> dict:
        return _published_model_metadata(cfg)

    @app.get("/v1/intent-models/published/download")
    def download_published_model(_auth: None = Depends(require_token)) -> FileResponse:
        _published_model_metadata(cfg)
        return FileResponse(
            _published_model_path(cfg),
            media_type="application/json",
            filename="intent_model.json",
        )

    @app.post("/v1/intent-models/published")
    def publish_model(
        payload: PublishModelRequest,
        _auth: None = Depends(require_token),
    ) -> dict:
        source = Path(payload.model_path).expanduser()
        if not source.exists():
            raise HTTPException(status_code=404, detail="model_path not found")
        try:
            model_payload = json.loads(source.read_text(encoding="utf-8"))
        except Exception as e:
            raise HTTPException(status_code=400, detail="model_path is invalid JSON") from e
        examples = model_payload.get("examples") if isinstance(model_payload, dict) else None
        if not isinstance(examples, dict):
            raise HTTPException(status_code=400, detail="model_path is not an intent model")
        version = str(payload.version or model_payload.get("version") or "").strip()
        if not version:
            raise HTTPException(status_code=400, detail="version is required")
        model_payload["version"] = version
        current_path = _published_model_path(cfg)
        current_path.parent.mkdir(parents=True, exist_ok=True)
        current_path.write_text(
            json.dumps(model_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        version_path = current_path.parent / "versions" / f"{_safe_filename(version)}.json"
        version_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(current_path, version_path)
        meta = {
            "version": version,
            "dataset_version": str(payload.dataset_version or ""),
            "evaluation_report": payload.evaluation_report if isinstance(payload.evaluation_report, dict) else {},
            "notes": str(payload.notes or ""),
            "published_at": _now(),
            "model_path": str(version_path),
        }
        _published_model_meta_path(cfg).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        history = current_path.parent / "published_history.jsonl"
        with history.open("a", encoding="utf-8") as f:
            f.write(json.dumps(meta, ensure_ascii=False, sort_keys=True) + "\n")
        return {**_published_model_metadata(cfg), "model_path": str(version_path)}

    @app.post("/v1/intent-samples/{sample_id}/review")
    def review_sample(
        sample_id: int,
        payload: ReviewRequest,
        _auth: None = Depends(require_token),
    ) -> dict:
        try:
            return store.review_sample(
                sample_id,
                label=payload.label,
                note=payload.note,
                corrected_intent=payload.corrected_intent,
            )
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.post("/v1/intent-phrases/review")
    def review_phrase(
        payload: PhraseReviewRequest,
        _auth: None = Depends(require_token),
    ) -> dict:
        try:
            return store.review_matching_text(
                payload.text,
                label=payload.label,
                note=payload.note,
                corrected_intent=payload.corrected_intent,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.get("/v1/stats")
    def stats(_auth: None = Depends(require_token)) -> dict:
        return store.stats()

    return app


app = create_app()


def _safe_filename(value: str) -> str:
    clean = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in str(value))
    return clean.strip(".-") or "model"


def _now() -> float:
    import time
    return time.time()
