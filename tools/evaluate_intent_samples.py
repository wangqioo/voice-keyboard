"""Evaluate reviewed intent-training samples against current local rules."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent.intent_evaluation import build_evaluation_dataset, evaluate_reviewed_samples, write_evaluation_report


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
    parser.add_argument("--dataset-output", default="", help="write a deduplicated evaluation dataset JSONL")
    parser.add_argument("--dataset-limit", type=int, default=0, help="max dataset rows when writing a dataset")
    parser.add_argument("--report-dir", default="", help="write a versioned JSON evaluation report")
    parser.add_argument("--version", default="", help="report filename version, defaults to timestamp")
    parser.add_argument("--intent-model", default="", help="local intent model JSON to include in evaluation")
    parser.add_argument(
        "--intent-model-min-similarity",
        type=float,
        default=1.0,
        help="local intent model similarity threshold; 1.0 means exact-only",
    )
    args = parser.parse_args()

    if args.dataset_output:
        summary = build_evaluation_dataset(
            args.input,
            args.dataset_output,
            limit=args.dataset_limit or None,
        )
        print(json.dumps({"dataset": summary}, ensure_ascii=False, indent=2) if args.json else (
            f"dataset={summary['output']} written={summary['written']} source_total={summary['source_total']}"
        ))
        if not args.report_dir:
            return

    if args.report_dir:
        result = write_evaluation_report(
            args.input,
            args.report_dir,
            override_path=args.overrides,
            intent_model_path=args.intent_model or None,
            intent_model_min_similarity=args.intent_model_min_similarity,
            version=args.version or None,
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            report = result["report"]
            print(
                f"report={result['path']} accuracy={report['accuracy_label']} "
                f"correct={report['correct']} wrong={report['wrong']} total={report['total']}"
            )
        return

    report = evaluate_reviewed_samples(
        args.input,
        override_path=args.overrides,
        intent_model_path=args.intent_model or None,
        intent_model_min_similarity=args.intent_model_min_similarity,
    )
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
