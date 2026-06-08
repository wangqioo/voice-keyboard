# Intent Training Data Loop

This project does not train a model on the desktop client. The client only
collects local, sanitized intent samples so later rule tuning or model training
can happen on a separate server.

## Data Flow

1. User speaks an AI instruction.
2. The client records sanitized metadata after execution.
3. Samples are stored locally in JSONL.
4. The user exports JSONL or CSV manually.
5. A server can ingest the exported file for analysis, rule mining, or training.

No audio is recorded. Selected text and recent text contents are not stored;
only booleans and lengths are stored.

## Enable Collection

Add this to `~/.voice-keyboard/config.yaml`:

```yaml
instruction_mode:
  intent_training:
    enabled: true
    path: ~/.voice-keyboard/intent_samples.jsonl
    capture_text: true
    max_text_length: 240
```

`capture_text: true` stores the recognized instruction text after basic
redaction. Set it to `false` if you only want hashed text and metadata.

## Sample Schema

Each line is one JSON object:

```json
{
  "ts": 1760000000.0,
  "text": "帮我保存一下",
  "text_hash": "b6a9...",
  "active_application": "Codex (com.openai.codex)",
  "has_selection": false,
  "selected_length": 0,
  "has_recent_text": true,
  "recent_text_length": 18,
  "shortcut_count": 6,
  "intent_type": "shortcut",
  "intent_name": "保存",
  "intent_key": "",
  "intent_source": "local",
  "intent_confidence": "high",
  "intent_cache_hit": false,
  "status": "ok",
  "detail": "shortcut:保存;intent_source=local;intent_confidence=high"
}
```

Redaction replaces emails, phone-like numbers, URLs, obvious secrets, and long
hex strings with placeholders.

## Export

```powershell
python tools/export_intent_samples.py --format jsonl
python tools/export_intent_samples.py --format csv --output intent_samples.csv
```

## Server Environment

A simple first server can be:

- Python 3.11+
- FastAPI or Flask for upload APIs
- PostgreSQL for samples
- Object storage for raw exported batches
- A private network or VPN endpoint
- No public anonymous upload

Suggested ingestion API:

```text
POST /v1/intent-samples/batches
Content-Type: application/jsonl
Authorization: Bearer <upload-token>
```

Minimum database fields:

- `id`
- `created_at`
- `source_machine_hash`
- `text_hash`
- `text`
- `active_application`
- `intent_type`
- `intent_name`
- `intent_source`
- `intent_confidence`
- `status`
- `detail`
- `review_label`
- `review_note`

## Training Strategy

Start without model training:

1. Aggregate frequent phrases by `intent_type`, `intent_name`, and `status`.
2. Find high-frequency LLM-only phrases and add local aliases.
3. Find shortcut failures and missing catalog names.
4. Find low-confidence or conflicting patterns for confirmation flows.

Only after several hundred reviewed samples should we consider model training.
The first training target should be a lightweight intent classifier, not a full
assistant:

- Input: sanitized instruction text, active app, shortcut names, selection flags.
- Output: intent type, optional shortcut/memo target, confidence.
- Baseline: local rules plus LLM labels.
- Better labels: manually reviewed corrections.

## Review Loop

The useful labels are:

- `correct`
- `wrong_intent`
- `wrong_target`
- `unsafe_should_confirm`
- `missing_shortcut`
- `unclear`

These labels can later drive rule changes or supervised fine-tuning.

## Evaluation Baseline

Before training a local model, keep a fixed evaluation dataset and compare every
rule/model change against it.

Build a deduplicated evaluation dataset from corrected local samples:

```bash
.venv/bin/python tools/evaluate_intent_samples.py \
  --input ~/.voice-keyboard/intent_samples.jsonl \
  --dataset-output tmp/intent-eval-dataset.jsonl
```

Write a versioned JSON report:

```bash
.venv/bin/python tools/evaluate_intent_samples.py \
  --input tmp/intent-eval-dataset.jsonl \
  --report-dir tmp/intent-eval-reports \
  --version baseline
```

Compare a local intent model against the same fixed dataset:

```bash
.venv/bin/python tools/evaluate_intent_samples.py \
  --input tmp/intent-eval-dataset.jsonl \
  --report-dir tmp/intent-eval-reports \
  --version model-0.8 \
  --intent-model ~/.voice-keyboard/intent_models/current.json \
  --intent-model-min-similarity 0.8
```

The report contains total/correct/wrong counts, accuracy, and mismatches. Keep
reports when changing rules, overrides, or future local models so regressions
are visible instead of guessed. Model reports include the model path and
similarity threshold used for the run.

## Local Intent Model

The first local model is intentionally lightweight: it maps normalized corrected
instruction text to a corrected intent. By default it only does exact
normalized-text matches, so it can be enabled before a broader classifier exists.
You can optionally lower `intent_model_min_similarity` for high-threshold
similar-expression matching after checking it against an evaluation dataset.

Train it from corrected samples:

```bash
.venv/bin/python tools/train_intent_model.py \
  --input ~/.voice-keyboard/intent_samples.jsonl \
  --output ~/.voice-keyboard/intent_model.json \
  --version baseline
```

Run upload, correction sync, local evaluation, model training, and model
evaluation in one command:

```bash
.venv/bin/python tools/run_intent_training_loop.py \
  --server http://SERVER:8000 \
  --token change-me \
  --model-registry-dir ~/.voice-keyboard/intent_models \
  --model-version model-0.8 \
  --model-report-dir ~/.voice-keyboard/intent_eval_reports \
  --model-min-similarity 0.8
```

Or train into a versioned registry and activate that version as `current.json`:

```bash
.venv/bin/python tools/train_intent_model.py \
  --input ~/.voice-keyboard/intent_samples.jsonl \
  --output ~/.voice-keyboard/intent_models/current.json \
  --registry-dir ~/.voice-keyboard/intent_models \
  --version baseline
```

List, switch, or roll back model versions:

```bash
.venv/bin/python tools/manage_intent_model.py --registry-dir ~/.voice-keyboard/intent_models list
.venv/bin/python tools/manage_intent_model.py --registry-dir ~/.voice-keyboard/intent_models activate baseline
.venv/bin/python tools/manage_intent_model.py --registry-dir ~/.voice-keyboard/intent_models rollback
```

Enable it in `config.yaml`:

```yaml
instruction_mode:
  intent_fallbacks:
    intent_model: true
    intent_model_path: ~/.voice-keyboard/intent_models/current.json
    intent_model_min_similarity: 1.0
```

Runtime order is:

1. Local hard rules and corrected overrides.
2. Local intent model exact match, plus optional high-threshold similar-expression match.
3. LLM classifier.

Recommended rollout:

- Keep `intent_model_min_similarity: 1.0` for exact-only matching.
- Try `0.8` only after evaluating real corrected samples; it can handle light
  variants such as extra polite prefixes/suffixes, but should not replace a
  proper classifier.
