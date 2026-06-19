#!/usr/bin/env python3
"""Verify a release-assets directory contains every wheel required by the CPU matrix."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from matrix_release_assets import matrix_entry_is_complete


def verify_release_bundle(cpu_matrix: dict, assets_dir: Path) -> list[str]:
    asset_names = sorted(
        path.name for path in assets_dir.iterdir() if path.is_file() and path.name != "SHA256SUMS.txt"
    )
    errors: list[str] = []
    for entry in cpu_matrix.get("include", []):
        if matrix_entry_is_complete(entry, asset_names):
            continue
        label = (
            f"{entry['target_os']}/{entry['target_arch']}/"
            f"{entry.get('backend', 'cpu')}/py{entry['python_version']}"
        )
        errors.append(
            f"Incomplete wheel set for matrix entry {label}. "
            f"Expected torch {entry['torch_version']}, "
            f"torchvision {entry['torchvision_version']}, "
            f"and torchaudio {entry['torchaudio_version']} wheels in {assets_dir}."
        )
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify release assets cover every CPU matrix entry."
    )
    parser.add_argument(
        "--matrix",
        required=True,
        help="Build matrix JSON string or @file path.",
    )
    parser.add_argument(
        "--assets-dir",
        default="release-assets",
        help="Directory containing wheels to upload.",
    )
    args = parser.parse_args()

    matrix_arg = args.matrix
    if matrix_arg.startswith("@"):
        build_matrix = json.loads(Path(matrix_arg[1:]).read_text(encoding="utf-8"))
    else:
        build_matrix = json.loads(matrix_arg)

    errors = verify_release_bundle(build_matrix, Path(args.assets_dir))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        sys.exit(1)

    print(f"Verified {len(build_matrix.get('include', []))} matrix entries in {args.assets_dir}")


if __name__ == "__main__":
    main()
