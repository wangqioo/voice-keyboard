# Intent Training Server

This is the server side of the Voice Keyboard intent-data loop. The desktop
client collects sanitized samples locally; this server receives exported JSONL
batches, stores samples, supports review labels, and exposes statistics.

## Current Implementation

- FastAPI API
- Built-in SQLite store for development and small deployments
- Token-based upload/review protection
- JSONL batch ingestion
- Sample listing
- Review label update
- Built-in `/review` web review console
- Corrected intent review payloads
- Basic stats
- Client upload CLI

The API shape is designed so the store can later be migrated to PostgreSQL
without changing the client upload command.

## Install

```bash
python -m venv .venv-server
.venv-server/bin/pip install -r requirements-server.txt
```

Windows:

```powershell
python -m venv .venv-server
.\.venv-server\Scripts\pip install -r requirements-server.txt
```

## Run

```bash
export INTENT_TRAINING_DATABASE_URL=sqlite:///./intent_training.db
export INTENT_TRAINING_UPLOAD_TOKEN=change-me
uvicorn training_server.api:app --host 0.0.0.0 --port 8000
```

Windows:

```powershell
$env:INTENT_TRAINING_DATABASE_URL = "sqlite:///./intent_training.db"
$env:INTENT_TRAINING_UPLOAD_TOKEN = "change-me"
uvicorn training_server.api:app --host 0.0.0.0 --port 8000
```

## Upload From Client

```bash
python tools/upload_intent_samples.py \
  --server http://SERVER:8000 \
  --token change-me \
  --source laptop-a
```

Dry run:

```bash
python tools/upload_intent_samples.py --dry-run
```

## Web Review Console

After the server starts, open:

```text
http://SERVER:8000/review
```

The page is built into the FastAPI app and does not require a separate frontend
build step.

Use the same token as `INTENT_TRAINING_UPLOAD_TOKEN` in the Token field. The
browser stores it in `localStorage` and sends it as:

```text
Authorization: Bearer <token>
```

The review console supports:

- Viewing total and corrected sample counts.
- Filtering samples by `review_label`, `intent_type`, and `status`.
- Reviewing recent samples without leaving the page.
- Saving review labels and notes.
- Filling `corrected_intent` for shortcut, delete, memory, chat, rewrite, replace, and continue intents.

## API

Health:

```text
GET /health
```

Upload JSONL:

```text
POST /v1/intent-samples/batches?source=laptop-a
Authorization: Bearer <token>
Content-Type: application/jsonl
```

List samples:

```text
GET /v1/intent-samples?limit=100&review_label=&intent_type=shortcut&status=ok
Authorization: Bearer <token>
```

Review sample:

```text
POST /v1/intent-samples/{id}/review
Authorization: Bearer <token>
Content-Type: application/json

{
  "label": "wrong_intent",
  "note": "Should be shortcut 保存",
  "corrected_intent": {"type": "shortcut", "name": "保存"}
}
```

Stats:

```text
GET /v1/stats
Authorization: Bearer <token>
```

## Review Labels

- `correct`
- `wrong_intent`
- `wrong_target`
- `unsafe_should_confirm`
- `missing_shortcut`
- `unclear`

## Final Production Shape

For a real multi-device setup:

- Put the server behind VPN or private network.
- Use HTTPS termination at a reverse proxy.
- Keep `INTENT_TRAINING_UPLOAD_TOKEN` secret.
- Use PostgreSQL for production storage.
- Add scheduled exports for analysis.

Recommended production stack:

- FastAPI
- PostgreSQL 15+
- Nginx/Caddy reverse proxy
- Private network/VPN
- Optional object storage for raw batch archives

## Analysis Loop

Do this before model training:

1. Review samples and apply labels.
2. Check `/v1/stats`.
3. Find high-frequency `llm` samples and add local rules/aliases.
4. Find `missing_shortcut` samples and update shortcut catalog.
5. Find `unsafe_should_confirm` samples and add confirmation flow.
6. Only after reviewed data is large enough, train a lightweight intent model.

Minimum useful reviewed dataset:

- 300+ labeled samples for rule mining
- 1,000+ labeled samples for a small classifier experiment
- 5,000+ labeled samples for serious model evaluation
