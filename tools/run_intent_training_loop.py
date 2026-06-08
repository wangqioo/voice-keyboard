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
    parser.add_argument(
        "--model-registry-dir",
        default="",
        help="optional local intent model registry dir; trains and activates a model version",
    )
    parser.add_argument("--model-version", default="", help="model version label")
    parser.add_argument("--model-report-dir", default="", help="optional report dir for model evaluation")
    parser.add_argument(
        "--model-min-similarity",
        type=float,
        default=1.0,
        help="similarity threshold used when evaluating the trained model",
    )
    parser.add_argument("--json", action="store_true", help="print full JSON report")
    args = parser.parse_args()

    report = run_training_loop(
        sample_path=args.input,
        server=args.server,
        token=args.token,
        override_path=args.overrides,
        source=args.source,
        http=requests,
        model_registry_dir=args.model_registry_dir or None,
        model_version=args.model_version,
        model_report_dir=args.model_report_dir or None,
        model_min_similarity=args.model_min_similarity,
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
    if "model" in report:
        print(
            f"model_version={report['model']['version']} "
            f"model_examples={report['model']['examples']} "
            f"model_current={report['model']['current']}"
        )
    if "model_evaluation" in report:
        model_report = report["model_evaluation"]["report"]
        print(
            f"model_report={report['model_evaluation']['path']} "
            f"model_accuracy={model_report['accuracy_label']} "
            f"model_correct={model_report['correct']} model_total={model_report['total']}"
        )


if __name__ == "__main__":
    main()
