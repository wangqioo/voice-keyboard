"""Pull reviewed corrected intents from server into local overrides."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent.intent_sync import sync_corrected_intents


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Voice Keyboard intent corrections")
    parser.add_argument(
        "--server",
        default=os.getenv("INTENT_TRAINING_SERVER", "http://127.0.0.1:8000"),
        help="training server base URL",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("INTENT_TRAINING_UPLOAD_TOKEN", ""),
        help="server token",
    )
    parser.add_argument(
        "--overrides",
        default=str(Path.home() / ".voice-keyboard" / "intent_overrides.jsonl"),
        help="local override JSONL file",
    )
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()

    headers = {}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"
    response = requests.get(
        args.server.rstrip("/") + "/v1/intent-samples",
        params={"limit": args.limit, "review_label": "wrong_intent"},
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()
    rows = response.json().get("items", [])
    result = sync_corrected_intents(rows, override_path=args.overrides)
    print(f"synced={result['synced']} skipped={result['skipped']}")


if __name__ == "__main__":
    main()
