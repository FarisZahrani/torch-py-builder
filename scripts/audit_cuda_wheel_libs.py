#!/usr/bin/env python3
"""Audit CUDA runtime bundling inside a torch wheel."""
from __future__ import annotations

import argparse
import re
import zipfile
from pathlib import Path

CUDA_LIB_PATTERN = re.compile(
    r"(?:^lib)?cudart|(?:^lib)?cublas|(?:^lib)?cudnn|(?:^lib)?cufft|(?:^lib)?curand|"
    r"(?:^lib)?cusparse|(?:^lib)?cusolver|(?:^lib)?nvrtc(?!.*caffe2)|(?:^lib)?nvjit|"
    r"(?:^lib)?nccl|(?:^lib)?cupti|(?:^lib)?nvtx",
    re.I,
)
PYTORCH_OWNED_LIB_PATTERN = re.compile(r"caffe2_nvrtc", re.I)


def audit_wheel(wheel_path: Path) -> dict:
    with zipfile.ZipFile(wheel_path) as archive:
        names = archive.namelist()
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = archive.read(metadata_name).decode("utf-8", errors="replace")

        lib_entries = [
            name
            for name in names
            if name.startswith("torch/lib/") and (name.endswith(".so") or name.endswith(".dll"))
        ]
        cuda_libs = [
            name
            for name in lib_entries
            if CUDA_LIB_PATTERN.search(Path(name).name)
            and not PYTORCH_OWNED_LIB_PATTERN.search(Path(name).name)
        ]
        requires = [
            line.split(":", 1)[1].strip()
            for line in metadata.splitlines()
            if line.startswith("Requires-Dist:")
        ]
        nvidia_requires = [item for item in requires if item.lower().startswith("nvidia-")]

    return {
        "wheel": wheel_path.name,
        "size_gb": wheel_path.stat().st_size / (1024**3),
        "torch_lib_count": len(lib_entries),
        "cuda_runtime_in_torch_lib": len(cuda_libs),
        "cuda_runtime_names": [Path(name).name for name in sorted(cuda_libs)],
        "requires_dist_count": len(requires),
        "nvidia_requires_dist_count": len(nvidia_requires),
        "nvidia_requires_dist": nvidia_requires,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit CUDA runtime bundling in a torch wheel.")
    parser.add_argument("wheels", nargs="+", help="Paths to torch .whl files.")
    args = parser.parse_args()

    for wheel_arg in args.wheels:
        result = audit_wheel(Path(wheel_arg))
        print(f"=== {result['wheel']} ({result['size_gb']:.2f} GB) ===")
        print(f"torch/lib binaries     : {result['torch_lib_count']}")
        print(f"CUDA runtime in lib    : {result['cuda_runtime_in_torch_lib']}")
        if result["cuda_runtime_names"]:
            for name in result["cuda_runtime_names"]:
                print(f"  - {name}")
        print(f"Requires-Dist entries  : {result['requires_dist_count']}")
        print(f"nvidia-* Requires-Dist : {result['nvidia_requires_dist_count']}")
        for item in result["nvidia_requires_dist"]:
            print(f"  - {item}")

        standalone = result["cuda_runtime_in_torch_lib"] > 0 or result["nvidia_requires_dist_count"] > 0
        print(f"standalone CUDA delivery: {'YES' if standalone else 'NO'}")
        print()


if __name__ == "__main__":
    main()
