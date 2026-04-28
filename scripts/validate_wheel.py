#!/usr/bin/env python3
"""Structural validation of a built Python package wheel archive."""
from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate the structure of a built package wheel file."
    )
    parser.add_argument("wheel", help="Path to the .whl file to validate.")
    parser.add_argument(
        "--expected-package",
        default="torch",
        help="Top-level package directory expected inside the wheel archive.",
    )
    parser.add_argument(
        "--expected-version",
        help="Expected package version string to verify against the wheel filename.",
    )
    parser.add_argument(
        "--min-size-bytes",
        type=int,
        help="Optional minimum expected wheel size in bytes.",
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
    min_size_bytes = args.min_size_bytes
    if min_size_bytes is None and args.expected_package == "torch":
        min_size_bytes = 50_000_000

    if min_size_bytes is not None and size_bytes < min_size_bytes:
        sys.exit(
            f"Wheel is suspiciously small ({size_bytes // 1024 // 1024} MB): {wheel_path.name}"
        )

    size_mb = size_bytes // 1024 // 1024
    print(f"Validating wheel: {wheel_path.name} ({size_mb} MB)")

    with zipfile.ZipFile(wheel_path) as zf:
        names = zf.namelist()

    expected_prefix = f"{args.expected_package}/"
    has_expected_package = any(n.startswith(expected_prefix) for n in names)
    if not has_expected_package:
        sys.exit(
            f"{expected_prefix} package directory not found in wheel: {wheel_path.name}"
        )

    has_metadata = any(n.endswith(".dist-info/METADATA") for n in names)
    if not has_metadata:
        sys.exit(f"dist-info/METADATA not found in wheel: {wheel_path.name}")

    print(f"  Files in archive : {len(names)}")
    print(f"  Package present  : {args.expected_package}")
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
