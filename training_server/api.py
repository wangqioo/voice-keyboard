"""FastAPI app for intent-training data ingestion and review."""

from __future__ import annotations

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from training_server.config import ServerConfig, sqlite_path_from_url
from training_server.store import IntentTrainingStore, SampleQuery, parse_jsonl


class UploadResponse(BaseModel):
    batch_id: int
    inserted: int


class ReviewRequest(BaseModel):
    label: str = Field(default="")
    note: str = Field(default="")
    corrected_intent: dict | None = Field(default=None)


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
        _auth: None = Depends(require_token),
    ) -> dict:
        rows = store.list_samples(SampleQuery(
            limit=limit,
            offset=offset,
            review_label=review_label,
            intent_type=intent_type,
            status=status,
        ))
        return {"items": rows}

    @app.get("/v1/intent-samples/corrections")
    def list_corrections(
        limit: int = Query(default=1000, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        _auth: None = Depends(require_token),
    ) -> dict:
        return {"items": store.list_corrected_samples(limit=limit, offset=offset)}

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

    @app.get("/v1/stats")
    def stats(_auth: None = Depends(require_token)) -> dict:
        return store.stats()

    return app


app = create_app()
