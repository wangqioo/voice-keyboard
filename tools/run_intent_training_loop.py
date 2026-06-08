"""Run upload -> sync corrections -> local evaluation in one command."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent.intent_loop import run_training_loop


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Voice Keyboard intent training loop")
    parser.add_argument(
        "--input",
        default=str(Path.home() / ".voice-keyboard" / "intent_samples.jsonl"),
        help="source intent samples JSONL",
    )
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
    parser.add_argument("--source", default="local-mac")
    parser.add_argument("--json", action="store_true", help="print full JSON report")
    args = parser.parse_args()

    report = run_training_loop(
        sample_path=args.input,
        server=args.server,
        token=args.token,
        override_path=args.overrides,
        source=args.source,
        http=requests,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    print(
        f"inserted={report['upload'].get('inserted', 0)} "
        f"synced={report['sync']['synced']} skipped={report['sync']['skipped']} "
        f"compacted={report['sync']['compacted']} "
        f"accuracy={report['evaluation']['accuracy_label']} "
        f"correct={report['evaluation']['correct']} total={report['evaluation']['total']}"
    )


if __name__ == "__main__":
    main()
