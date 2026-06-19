"""Check local Voice Keyboard config for plaintext secrets."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent.config_hygiene import find_plaintext_secrets


def main() -> None:
    parser = argparse.ArgumentParser(description="Check Voice Keyboard config for plaintext secrets")
    parser.add_argument(
        "--config",
        default=str(Path.home() / ".voice-keyboard" / "config.yaml"),
        help="config.yaml path to inspect",
    )
    parser.add_argument("--json", action="store_true", help="print JSON findings")
    args = parser.parse_args()

    findings = find_plaintext_secrets(args.config)
    if args.json:
        print(json.dumps({"findings": findings}, ensure_ascii=False, indent=2))
    elif findings:
        for finding in findings:
            line = f":{finding['line']}" if finding.get("line") else ""
            print(f"{args.config}{line} plaintext secret at {finding['path']}")
    if findings:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
