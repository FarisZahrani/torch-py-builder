#!/usr/bin/env python3
"""Resolve the latest stable PyTorch release version from the GitHub API."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

RELEASE_TAG_PATTERN = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
PYTORCH_RELEASES_URL = "https://api.github.com/repos/pytorch/pytorch/releases"


def fetch_releases() -> list[dict]:
    releases: list[dict] = []
    page = 1
    while True:
        url = f"{PYTORCH_RELEASES_URL}?per_page=100&page={page}"
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "torch-py-builder/1.0",
        }
        token = os.environ.get("GITHUB_TOKEN", "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        if not payload:
            break
        releases.extend(payload)
        # Stop once we have enough stable candidates to be confident in the latest.
        stable = [
            r for r in releases
            if not r.get("draft") and not r.get("prerelease")
            and RELEASE_TAG_PATTERN.match(r.get("tag_name", ""))
        ]
        if len(stable) >= 5:
            break
        page += 1
    return releases


def latest_stable_release(releases: list[dict]) -> dict:
    best: tuple[int, int, int] | None = None
    best_release: dict | None = None
    for release in releases:
        if release.get("draft") or release.get("prerelease"):
            continue
        tag = release.get("tag_name", "")
        m = RELEASE_TAG_PATTERN.match(tag)
        if not m:
            continue
        version_tuple = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if best is None or version_tuple > best:
            best = version_tuple
            best_release = release

    if best_release is None:
        raise RuntimeError("No stable PyTorch release found on GitHub.")

    tag = best_release["tag_name"]
    version = tag.lstrip("v")
    return {
        "version": version,
        "tag": tag,
        "tag_commit_sha": best_release.get("target_commitish", ""),
        "release_url": best_release.get("html_url", ""),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resolve the latest stable PyTorch release version from GitHub."
    )
    parser.add_argument(
        "--output",
        default="-",
        help="Output file path for resolved JSON. Use '-' or omit for stdout.",
    )
    parser.add_argument(
        "--version-override",
        help="Skip GitHub API and use this exact version (e.g. 2.7.0).",
    )
    args = parser.parse_args()

    if args.version_override:
        version = args.version_override.lstrip("v")
        if not RELEASE_TAG_PATTERN.match(f"v{version}"):
            sys.exit(f"Invalid --version-override: {args.version_override!r}. Expected format: MAJOR.MINOR.PATCH")
        result: dict = {
            "version": version,
            "tag": f"v{version}",
            "tag_commit_sha": "",
            "release_url": "",
        }
    else:
        releases = fetch_releases()
        result = latest_stable_release(releases)

    output_json = json.dumps(result, indent=2)

    if not args.output or args.output == "-":
        print(output_json)
    else:
        Path(args.output).write_text(output_json + "\n", encoding="utf-8")
        print(output_json)


if __name__ == "__main__":
    main()
