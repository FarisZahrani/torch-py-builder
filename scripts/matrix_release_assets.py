#!/usr/bin/env python3
"""Match matrix entries to published release wheel filenames and plan fill-missing builds."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Iterable


def platform_substrings(target_os: str, target_arch: str) -> list[str]:
    if target_os == "linux" and target_arch == "x86_64":
        return ["linux_x86_64"]
    if target_os == "windows" and target_arch == "x86_64":
        return ["win_amd64"]
    if target_os == "macos" and target_arch == "x86_64":
        return ["macosx_10_15", "macosx_10_13"]
    if target_os == "macos" and target_arch == "arm64":
        return ["macosx_11_0", "macosx_12_0", "macosx_13_0", "macosx_14_0", "_arm64"]
    raise ValueError(f"Unsupported platform: {target_os}/{target_arch}")


def wheel_prefix(package: str, version: str, python_version: str) -> str:
    py_tag = f"cp{python_version.replace('.', '')}"
    return f"{package}-{version}-{py_tag}-{py_tag}-"


def has_release_wheel(
    release_asset_names: Iterable[str],
    package: str,
    version: str,
    python_version: str,
    platform_markers: list[str],
) -> bool:
    prefix = wheel_prefix(package, version, python_version)
    for name in release_asset_names:
        if not name.endswith(".whl"):
            continue
        if not name.startswith(prefix):
            continue
        platform_part = name[len(prefix) :]
        if any(marker in platform_part for marker in platform_markers):
            return True
    return False


def matrix_entry_is_complete(entry: dict, release_asset_names: Iterable[str]) -> bool:
    backend = entry.get("backend", "cpu")
    if backend == "cuda" and entry["target_os"] in {"linux", "windows"}:
        # CPU and CUDA wheels share identical filenames on Linux and Windows.
        return False

    markers = platform_substrings(entry["target_os"], entry["target_arch"])
    packages = (
        ("torch", entry["torch_version"]),
        ("torchvision", entry["torchvision_version"]),
        ("torchaudio", entry["torchaudio_version"]),
    )
    return all(
        has_release_wheel(
            release_asset_names,
            package,
            version,
            entry["python_version"],
            markers,
        )
        for package, version in packages
    )


def select_missing_matrix_entries(
    matrix: dict,
    release_asset_names: Iterable[str],
    *,
    force_full: bool = False,
) -> dict:
    if force_full:
        return {"include": list(matrix.get("include", []))}
    missing = [
        entry
        for entry in matrix.get("include", [])
        if not matrix_entry_is_complete(entry, release_asset_names)
    ]
    return {"include": missing}


def merge_sha256_sums(existing_text: str, assets_dir: Path) -> str:
    entries: dict[str, str] = {}
    for line in existing_text.splitlines():
        line = line.strip()
        if not line:
            continue
        match = re.match(r"^([0-9a-fA-F]{64})\s+(.+)$", line)
        if match:
            entries[match.group(2)] = match.group(1).lower()

    for path in sorted(assets_dir.iterdir()):
        if not path.is_file() or path.name == "SHA256SUMS.txt":
            continue
        digest = _sha256_file(path)
        entries[path.name] = digest

    return "".join(f"{entries[name]}  {name}\n" for name in sorted(entries))


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def plan_matrix_phase(
    plan: dict,
    cpu_candidate_matrix: dict,
    cuda_candidate_matrix: dict,
    release_asset_names: list[str],
    *,
    build_scope: str = "cpu",
    force_rebuild: bool = False,
) -> dict:
    force_full = force_rebuild or plan.get("release_reason") == "forced"
    cpu_matrix = select_missing_matrix_entries(
        cpu_candidate_matrix,
        release_asset_names,
        force_full=force_full,
    )
    cuda_matrix = select_missing_matrix_entries(
        cuda_candidate_matrix,
        release_asset_names,
        force_full=force_full,
    )
    if build_scope == "cuda":
        should_build = bool(cuda_matrix["include"])
    else:
        should_build = bool(cpu_matrix["include"])

    updated_plan = dict(plan)
    if should_build and not plan.get("should_build"):
        updated_plan["should_build"] = True
        updated_plan["release_reason"] = "fill-missing"

    return {
        "should_build": should_build,
        "cpu_matrix": cpu_matrix,
        "cpu_matrix_has_entries": bool(cpu_matrix["include"]),
        "cuda_matrix": cuda_matrix,
        "cuda_matrix_has_entries": bool(cuda_matrix["include"]),
        "release_plan_json": updated_plan,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plan CPU/CUDA matrix entries missing from a GitHub release."
    )
    parser.add_argument("--plan-file", required=True, help="Release plan JSON path.")
    parser.add_argument(
        "--cpu-candidate-matrix",
        required=True,
        help="CPU candidate matrix JSON string or @file path.",
    )
    parser.add_argument(
        "--cuda-candidate-matrix",
        default='{"include": []}',
        help="CUDA candidate matrix JSON string or @file path.",
    )
    parser.add_argument(
        "--release-assets-json",
        default="[]",
        help="JSON array of existing release asset filenames.",
    )
    parser.add_argument(
        "--build-scope",
        choices=("cpu", "cuda"),
        default="cpu",
        help="Whether should_build follows the CPU or CUDA matrix.",
    )
    parser.add_argument(
        "--force-rebuild",
        action="store_true",
        help="Treat every matrix entry as missing.",
    )
    parser.add_argument(
        "--github-output",
        help="Optional path to append GitHub Actions step outputs.",
    )
    parser.add_argument(
        "--output-json",
        help="Optional path to write the full planning result as JSON.",
    )
    args = parser.parse_args()

    def load_json_arg(value: str) -> dict:
        if value.startswith("@"):
            return json.loads(Path(value[1:]).read_text(encoding="utf-8"))
        return json.loads(value)

    plan = json.loads(Path(args.plan_file).read_text(encoding="utf-8"))
    cpu_candidate_matrix = load_json_arg(args.cpu_candidate_matrix)
    cuda_candidate_matrix = load_json_arg(args.cuda_candidate_matrix)
    release_asset_names = json.loads(args.release_assets_json)

    result = plan_matrix_phase(
        plan,
        cpu_candidate_matrix,
        cuda_candidate_matrix,
        release_asset_names,
        build_scope=args.build_scope,
        force_rebuild=args.force_rebuild,
    )

    if args.output_json:
        Path(args.output_json).write_text(
            json.dumps(result, indent=2) + "\n",
            encoding="utf-8",
        )

    if args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as fh:
            fh.write(f"should_build={'true' if result['should_build'] else 'false'}\n")
            fh.write(f"cpu_matrix={json.dumps(result['cpu_matrix'])}\n")
            fh.write(
                "cpu_matrix_has_entries="
                f"{'true' if result['cpu_matrix_has_entries'] else 'false'}\n"
            )
            fh.write(f"cuda_matrix={json.dumps(result['cuda_matrix'])}\n")
            fh.write(
                "cuda_matrix_has_entries="
                f"{'true' if result['cuda_matrix_has_entries'] else 'false'}\n"
            )
            fh.write(
                f"release_plan_json={json.dumps(result['release_plan_json'])}\n"
            )

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
