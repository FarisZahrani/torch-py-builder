#!/usr/bin/env python3
"""Merge new release asset checksums with an existing SHA256SUMS.txt."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from matrix_release_assets import merge_sha256_sums


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge release SHA256SUMS.txt entries.")
    parser.add_argument(
        "--assets-dir",
        default="release-assets",
        help="Directory containing wheels and other release files.",
    )
    parser.add_argument(
        "--existing-sha256sums",
        default="",
        help="Existing SHA256SUMS.txt contents to merge with.",
    )
    parser.add_argument(
        "--existing-sha256sums-file",
        help="Optional file containing existing SHA256SUMS.txt contents.",
    )
    args = parser.parse_args()

    assets_dir = Path(args.assets_dir)
    existing_text = args.existing_sha256sums
    if args.existing_sha256sums_file:
        existing_text = Path(args.existing_sha256sums_file).read_text(encoding="utf-8")
    merged = merge_sha256_sums(existing_text, assets_dir)
    checksum_path = assets_dir / "SHA256SUMS.txt"
    checksum_path.write_text(merged, encoding="utf-8")
    print(f"Wrote merged checksums to {checksum_path}")


if __name__ == "__main__":
    main()
