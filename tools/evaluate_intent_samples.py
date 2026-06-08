"""Evaluate reviewed intent-training samples against current local rules."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent.intent_evaluation import evaluate_reviewed_samples


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Voice Keyboard intent corrections")
    parser.add_argument(
        "--input",
        default=str(Path.home() / ".voice-keyboard" / "intent_samples.jsonl"),
        help="source JSONL file",
    )
    parser.add_argument(
        "--overrides",
        default=str(Path.home() / ".voice-keyboard" / "intent_overrides.jsonl"),
        help="local override JSONL file",
    )
    parser.add_argument("--json", action="store_true", help="print full JSON report")
    parser.add_argument("--limit-mismatches", type=int, default=20)
    args = parser.parse_args()

    report = evaluate_reviewed_samples(args.input, override_path=args.overrides)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    print(
        f"accuracy={report['accuracy_label']} "
        f"correct={report['correct']} wrong={report['wrong']} total={report['total']}"
    )
    for item in report["mismatches"][: max(0, args.limit_mismatches)]:
        print(json.dumps(item, ensure_ascii=False))


if __name__ == "__main__":
    main()
