#!/usr/bin/env python3
"""Plan whether a new shared torch-family release is needed based on the resolved torch version."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plan whether a new shared torch-family build and release is needed."
    )
    parser.add_argument(
        "--resolved-file",
        required=True,
        help="Path to resolved torch version JSON (output of resolve_latest_torch.py).",
    )
    parser.add_argument(
        "--state-file",
        default="release-state/latest.json",
        help="Path to the committed release state file.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force a rebuild even if the version has not changed.",
    )
    parser.add_argument(
        "--release-tag",
        help="Optional explicit release tag override (e.g. torch-2.7.0).",
    )
    args = parser.parse_args()

    resolved = json.loads(Path(args.resolved_file).read_text(encoding="utf-8"))
    current_version: str = resolved["version"]

    state_path = Path(args.state_file)
    previous_payload: dict = (
        json.loads(state_path.read_text(encoding="utf-8"))
        if state_path.exists()
        else {}
    )
    previous_version: str = previous_payload.get("torch_version", "")

    has_new_version = current_version != previous_version

    if not previous_version:
        release_reason = "initial-release"
    elif has_new_version:
        release_reason = "version-bump"
    elif args.force:
        release_reason = "forced"
    else:
        release_reason = "no-change"

    should_build = has_new_version or args.force

    if args.release_tag:
        release_tag = args.release_tag
    elif should_build:
        release_tag = f"torch-{current_version}"
    else:
        release_tag = ""

    plan = {
        "should_build": should_build,
        "torch_version": current_version,
        "previous_version": previous_version,
        "release_tag": release_tag,
        "release_reason": release_reason,
        "resolved": resolved,
    }

    print(json.dumps(plan, indent=2))


if __name__ == "__main__":
    main()
