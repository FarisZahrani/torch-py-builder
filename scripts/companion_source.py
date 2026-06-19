#!/usr/bin/env python3
"""Resolve and verify pytorch/vision and pytorch/audio source tags for a torch release."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[.+-].*)?$")
GITHUB_API = "https://api.github.com"

REPO_CONFIG = {
    "torch": "pytorch/pytorch",
    "torchvision": "pytorch/vision",
    "torchaudio": "pytorch/audio",
}


def parse_version(version: str) -> tuple[int, int, int]:
    match = VERSION_RE.match(version.strip())
    if not match:
        raise ValueError(f"Unsupported version format: {version!r}")
    return tuple(int(part) for part in match.groups())


def derive_torchvision_version(torch_version: str) -> str:
    major, minor, patch = parse_version(torch_version)
    if major == 1:
        return f"0.{minor + 1}.{patch}"
    if major == 2:
        return f"0.{minor + 15}.{patch}"
    raise ValueError(
        "Automatic torchvision version mapping is only defined for torch 1.x and 2.x releases."
    )


def derive_torchaudio_version(torch_version: str) -> str:
    major, minor, patch = parse_version(torch_version)
    if major == 1:
        return f"0.{minor}.{patch}"
    if major == 2:
        return f"{major}.{minor}.{patch}"
    raise ValueError(
        "Automatic torchaudio version mapping is only defined for torch 1.x and 2.x releases."
    )


def _github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "torch-py-builder/1.0",
    }
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def git_tag_exists(repo: str, tag: str) -> bool:
    encoded_tag = urllib.request.quote(tag, safe="")
    url = f"{GITHUB_API}/repos/{repo}/git/ref/tags/{encoded_tag}"
    request = urllib.request.Request(url, headers=_github_headers())
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status == 200
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise


def resolve_git_tag(repo: str, version: str) -> str | None:
    for candidate in (f"v{version}", version):
        if git_tag_exists(repo, candidate):
            return candidate
    return None


def resolve_companion_sources(torch_version: str, *, verify_tags: bool = True) -> dict[str, Any]:
    torchvision_version = derive_torchvision_version(torch_version)
    torchaudio_version = derive_torchaudio_version(torch_version)

    result: dict[str, Any] = {
        "torch_version": torch_version,
        "torchvision_version": torchvision_version,
        "torchaudio_version": torchaudio_version,
        "torch_git_tag": f"v{torch_version}",
        "torchvision_git_tag": "",
        "torchaudio_git_tag": "",
        "ready": True,
        "errors": [],
    }

    if not verify_tags:
        result["torchvision_git_tag"] = f"v{torchvision_version}"
        result["torchaudio_git_tag"] = f"v{torchaudio_version}"
        return result

    checks = (
        ("torch", torch_version, REPO_CONFIG["torch"]),
        ("torchvision", torchvision_version, REPO_CONFIG["torchvision"]),
        ("torchaudio", torchaudio_version, REPO_CONFIG["torchaudio"]),
    )
    tag_fields = {
        "torch": "torch_git_tag",
        "torchvision": "torchvision_git_tag",
        "torchaudio": "torchaudio_git_tag",
    }

    for package, version, repo in checks:
        tag = resolve_git_tag(repo, version)
        if tag is None:
            result["ready"] = False
            result["errors"].append(
                f"{package} source tag for version {version} was not found in {repo} "
                f"(tried v{version} and {version})"
            )
            continue
        result[tag_fields[package]] = tag

    return result


def readiness_json(torch_version: str) -> str:
    return json.dumps(resolve_companion_sources(torch_version), indent=2)
