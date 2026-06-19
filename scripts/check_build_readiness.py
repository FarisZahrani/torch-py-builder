#!/usr/bin/env python3
"""Check whether torch, torchvision, and torchaudio source tags exist for a build."""
from __future__ import annotations

import argparse
import json
import sys

from companion_source import resolve_companion_sources


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify companion source repositories have tags for a torch release."
    )
    parser.add_argument("--torch-version", required=True, help="Torch version to check.")
    parser.add_argument(
        "--github-output",
        help="Optional path to append ready=true/false for GitHub Actions.",
    )
    parser.add_argument(
        "--exit-zero",
        action="store_true",
        help="Always exit 0 (for sync gating without failing the workflow).",
    )
    args = parser.parse_args()

    result = resolve_companion_sources(args.torch_version, verify_tags=True)

    if args.github_output:
        from pathlib import Path

        with Path(args.github_output).open("a", encoding="utf-8") as fh:
            fh.write(f"ready={'true' if result['ready'] else 'false'}\n")
            fh.write(f"companion_versions_json={json.dumps(result)}\n")

    print(json.dumps(result, indent=2))

    if not result["ready"]:
        for error in result["errors"]:
            print(error, file=sys.stderr)
        if not args.exit_zero:
            sys.exit(1)


if __name__ == "__main__":
    main()
