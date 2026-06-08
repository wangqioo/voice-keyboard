"""Train a lightweight local intent model from corrected samples."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent.intent_model import train_intent_model


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Voice Keyboard local intent model")
    parser.add_argument(
        "--input",
        default=str(Path.home() / ".voice-keyboard" / "intent_samples.jsonl"),
        help="source JSONL file with corrected_intent rows",
    )
    parser.add_argument(
        "--output",
        default=str(Path.home() / ".voice-keyboard" / "intent_model.json"),
        help="output model JSON file",
    )
    parser.add_argument("--version", default="", help="model version label")
    parser.add_argument("--json", action="store_true", help="print JSON summary")
    args = parser.parse_args()

    summary = train_intent_model(args.input, args.output, version=args.version)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(
            f"model={summary['output']} examples={summary['examples']} "
            f"skipped={summary['skipped']} source_total={summary['source_total']} "
            f"version={summary['version']}"
        )


if __name__ == "__main__":
    main()
