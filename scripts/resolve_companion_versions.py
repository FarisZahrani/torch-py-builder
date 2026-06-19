#!/usr/bin/env python3
"""Resolve torchvision and torchaudio versions that match a torch release."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from companion_source import resolve_companion_sources


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resolve torchvision and torchaudio versions for a torch release."
    )
    parser.add_argument("--torch-version", required=True, help="Torch version to match.")
    parser.add_argument(
        "--output",
        help="Optional output JSON path. If omitted, prints JSON to stdout.",
    )
    parser.add_argument(
        "--skip-tag-verify",
        action="store_true",
        help="Skip GitHub tag existence checks (for local/offline use only).",
    )
    args = parser.parse_args()

    result = resolve_companion_sources(
        args.torch_version,
        verify_tags=not args.skip_tag_verify,
    )

    if not result["ready"]:
        for error in result["errors"]:
            print(error, file=sys.stderr)
        sys.exit(1)

    payload = json.dumps(result, indent=2)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
