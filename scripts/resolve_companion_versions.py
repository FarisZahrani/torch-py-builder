#!/usr/bin/env python3
"""Resolve torchvision and torchaudio versions that match a torch release."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[.+-].*)?$")


def parse_version(version: str) -> tuple[int, int, int]:
    match = VERSION_RE.match(version.strip())
    if not match:
        raise SystemExit(f"Unsupported torch version format: {version!r}")
    return tuple(int(part) for part in match.groups())


def derive_torchvision_version(torch_version: str) -> str:
    major, minor, patch = parse_version(torch_version)

    if major == 1:
        return f"0.{minor + 1}.{patch}"
    if major == 2:
        return f"0.{minor + 15}.{patch}"

    raise SystemExit(
        "Automatic torchvision version mapping is only defined for torch 1.x and 2.x releases."
    )


def derive_torchaudio_version(torch_version: str) -> str:
    major, minor, patch = parse_version(torch_version)

    if major == 1:
        return f"0.{minor}.{patch}"
    if major == 2:
        return f"{major}.{minor}.{patch}"

    raise SystemExit(
        "Automatic torchaudio version mapping is only defined for torch 1.x and 2.x releases."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resolve torchvision and torchaudio versions for a torch release."
    )
    parser.add_argument("--torch-version", required=True, help="Torch version to match.")
    parser.add_argument(
        "--output",
        help="Optional output JSON path. If omitted, prints JSON to stdout.",
    )
    args = parser.parse_args()

    result = {
        "torch_version": args.torch_version,
        "torchvision_version": derive_torchvision_version(args.torch_version),
        "torchaudio_version": derive_torchaudio_version(args.torch_version),
    }

    payload = json.dumps(result, indent=2)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)


if __name__ == "__main__":
    main()