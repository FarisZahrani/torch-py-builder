#!/usr/bin/env python3
"""Structural validation of a built PyTorch wheel archive."""
from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate the structure of a built PyTorch wheel file."
    )
    parser.add_argument("wheel", help="Path to the .whl file to validate.")
    parser.add_argument(
        "--expected-version",
        help="Expected torch version string to verify against the wheel filename.",
    )
    parser.add_argument(
        "--full-timeout-seconds",
        type=int,
        default=0,
        help="Unused; kept for CLI compatibility.",
    )
    args = parser.parse_args()

    wheel_path = Path(args.wheel)

    if not wheel_path.exists():
        sys.exit(f"Wheel not found: {wheel_path}")

    if wheel_path.suffix != ".whl":
        sys.exit(f"Not a .whl file: {wheel_path.name}")

    size_bytes = wheel_path.stat().st_size
    # A minimal CPU-only torch wheel is several hundred MB.
    if size_bytes < 50_000_000:
        sys.exit(
            f"Wheel is suspiciously small ({size_bytes // 1024 // 1024} MB): {wheel_path.name}"
        )

    size_mb = size_bytes // 1024 // 1024
    print(f"Validating wheel: {wheel_path.name} ({size_mb} MB)")

    with zipfile.ZipFile(wheel_path) as zf:
        names = zf.namelist()

    has_torch_package = any(n.startswith("torch/") for n in names)
    if not has_torch_package:
        sys.exit(f"torch/ package directory not found in wheel: {wheel_path.name}")

    has_metadata = any(n.endswith(".dist-info/METADATA") for n in names)
    if not has_metadata:
        sys.exit(f"dist-info/METADATA not found in wheel: {wheel_path.name}")

    print(f"  Files in archive : {len(names)}")
    print(f"  torch/ present   : yes")
    print(f"  METADATA present : yes")

    if args.expected_version:
        if args.expected_version not in wheel_path.name:
            sys.exit(
                f"Expected version {args.expected_version!r} not found in wheel filename: {wheel_path.name}"
            )
        print(f"  Version check    : {args.expected_version} OK")

    print("Wheel validation passed.")


if __name__ == "__main__":
    main()
