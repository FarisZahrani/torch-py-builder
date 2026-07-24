#!/usr/bin/env python3
"""Bundle NVIDIA CUDA runtime DLLs into a Windows torch wheel under torch/lib/."""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

CUDA_DLL_GLOBS = (
    "cudart64_*.dll",
    "cublas64_*.dll",
    "cublasLt64_*.dll",
    "cudnn*.dll",
    "cufft64_*.dll",
    "cufftw64_*.dll",
    "curand64_*.dll",
    "cusparse64_*.dll",
    "cusolver64_*.dll",
    "cusolverMg64_*.dll",
    "nvrtc64_*.dll",
    "nvrtc-builtins64_*.dll",
    "nvJitLink_*.dll",
    "cupti64_*.dll",
    "nvperf_host.dll",
    "nvToolsExt64_1.dll",
    "libiomp5md.dll",
    "libiompstubs5md.dll",
    "uv.dll",
    "zlibwapi.dll",
)

REQUIRED_DLL_PATTERNS = (
    re.compile(r"^cudart64_.*\.dll$", re.I),
    re.compile(r"^nvrtc64_.*\.dll$", re.I),
    re.compile(r"^cublas64_.*\.dll$", re.I),
    re.compile(r"^cublasLt64_.*\.dll$", re.I),
    re.compile(r"^cudnn64_.*\.dll$", re.I),
    re.compile(r"^nvJitLink_.*\.dll$", re.I),
)


def resolve_cuda_home(explicit: str | None) -> Path:
    for candidate in (explicit, os.environ.get("CUDA_PATH"), os.environ.get("CUDA_HOME")):
        if candidate:
            path = Path(candidate)
            if path.exists():
                return path
    nvcc = shutil.which("nvcc")
    if nvcc:
        return Path(nvcc).resolve().parent.parent
    raise SystemExit("Could not resolve CUDA_HOME/CUDA_PATH for DLL bundling.")


def search_directories(cuda_home: Path, pytorch_src: Path | None) -> list[Path]:
    directories: list[Path] = [
        cuda_home / "bin",
        cuda_home / "bin" / "x64",
        cuda_home / "extras" / "CUPTI" / "lib64",
        cuda_home / "extras" / "CUPTI" / "bin",
    ]
    for env_name in ("CUDNN_PATH", "CUDNN_HOME", "NVTOOLSEXT_PATH"):
        value = os.environ.get(env_name, "").strip()
        if value:
            directories.extend([Path(value) / "bin", Path(value)])

    if pytorch_src is not None:
        directories.extend(
            [
                pytorch_src / "build" / "bin" / "Release",
                pytorch_src / "build" / "bin",
            ]
        )

    system_root = os.environ.get("SystemRoot") or r"C:\Windows"
    directories.append(Path(system_root) / "System32")

    program_files = os.environ.get("ProgramFiles")
    if program_files:
        directories.append(Path(program_files) / "NVIDIA GPU Computing Toolkit" / "CUDA" / cuda_home.name / "bin")
        cudnn_root = Path(program_files) / "NVIDIA" / "CUDNN"
        if cudnn_root.is_dir():
            directories.extend(path / "bin" for path in sorted(cudnn_root.glob("v*")) if (path / "bin").is_dir())

    seen: set[Path] = set()
    unique: list[Path] = []
    for directory in directories:
        if directory in seen or not directory.is_dir():
            continue
        seen.add(directory)
        unique.append(directory)
    return unique


def collect_cuda_runtime_dlls(
    cuda_home: Path,
    *,
    pytorch_src: Path | None = None,
) -> dict[str, Path]:
    discovered: dict[str, Path] = {}
    for directory in search_directories(cuda_home, pytorch_src):
        for pattern in CUDA_DLL_GLOBS:
            for path in sorted(directory.glob(pattern)):
                if path.is_file():
                    discovered.setdefault(path.name.lower(), path)
    return {path.name: path for path in discovered.values()}


def list_torch_lib_dlls(wheel_path: Path) -> list[str]:
    with zipfile.ZipFile(wheel_path, "r") as archive:
        return sorted(
            Path(name).name
            for name in archive.namelist()
            if name.endswith(".dll") and "/torch/lib/" in name.replace("\\", "/")
        )


def verify_bundled_wheel(wheel_path: Path, *, min_dll_count: int = 20) -> None:
    dll_names = list_torch_lib_dlls(wheel_path)
    if len(dll_names) < min_dll_count:
        raise SystemExit(
            f"Bundled wheel has only {len(dll_names)} torch/lib DLLs; expected at least {min_dll_count}."
        )
    missing_patterns = []
    for pattern in REQUIRED_DLL_PATTERNS:
        if not any(pattern.match(name) for name in dll_names):
            missing_patterns.append(pattern.pattern)
    if missing_patterns:
        raise SystemExit(
            "Bundled wheel is missing required CUDA runtime DLL patterns: "
            + ", ".join(missing_patterns)
        )


def repack_wheel_with_dlls(wheel_path: Path, dlls: dict[str, Path]) -> Path:
    if not dlls:
        raise SystemExit("No CUDA runtime DLLs were discovered to bundle.")

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        unpack_dir = tmpdir / "unpacked"
        unpack_dir.mkdir()

        subprocess.run(
            [sys.executable, "-m", "wheel", "unpack", str(wheel_path), "-d", str(unpack_dir)],
            check=True,
        )
        package_dirs = sorted(path for path in unpack_dir.iterdir() if path.is_dir())
        if len(package_dirs) != 1:
            raise SystemExit(f"Expected one unpacked wheel directory, found {len(package_dirs)}")
        torch_lib = package_dirs[0] / "torch" / "lib"
        if not torch_lib.is_dir():
            raise SystemExit(f"torch/lib not found in unpacked wheel: {package_dirs[0]}")

        bundled = 0
        for dest_name, src_path in dlls.items():
            destination = torch_lib / dest_name
            if destination.exists():
                continue
            shutil.copy2(src_path, destination)
            bundled += 1

        dist_dir = tmpdir / "dist"
        dist_dir.mkdir()
        subprocess.run(
            [sys.executable, "-m", "wheel", "pack", str(package_dirs[0]), "-d", str(dist_dir)],
            check=True,
        )
        packed_candidates = sorted(dist_dir.glob("*.whl"))
        if len(packed_candidates) != 1:
            raise SystemExit(f"Expected one packed wheel, found {len(packed_candidates)}")
        packed_wheel = packed_candidates[0]
        shutil.copy2(packed_wheel, wheel_path)

    print(f"Bundled {bundled} CUDA runtime DLLs into {wheel_path.name}")
    print(f"torch/lib DLL count: {len(list_torch_lib_dlls(wheel_path))}")
    return wheel_path


def bundle_windows_cuda_wheel(
    wheel_path: Path,
    *,
    cuda_home: Path,
    pytorch_src: Path | None = None,
) -> Path:
    wheel_path = wheel_path.resolve()
    if not wheel_path.exists():
        raise SystemExit(f"Wheel not found: {wheel_path}")

    before = list_torch_lib_dlls(wheel_path)
    print(f"Before bundling: {len(before)} torch/lib DLLs in {wheel_path.name}")

    dlls = collect_cuda_runtime_dlls(cuda_home, pytorch_src=pytorch_src)
    print(f"Discovered {len(dlls)} CUDA runtime DLL candidates under {cuda_home}")
    repack_wheel_with_dlls(wheel_path, dlls)
    verify_bundled_wheel(wheel_path)
    return wheel_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bundle NVIDIA CUDA runtime DLLs into a Windows torch wheel."
    )
    parser.add_argument("--wheel", required=True, help="Path to the torch .whl file.")
    parser.add_argument("--cuda-home", help="CUDA toolkit root (defaults to CUDA_PATH/CUDA_HOME).")
    parser.add_argument(
        "--pytorch-src",
        help="Optional PyTorch source tree for extra build/bin DLL discovery.",
    )
    args = parser.parse_args()

    cuda_home = resolve_cuda_home(args.cuda_home)
    pytorch_src = Path(args.pytorch_src).resolve() if args.pytorch_src else None
    bundle_windows_cuda_wheel(Path(args.wheel), cuda_home=cuda_home, pytorch_src=pytorch_src)


if __name__ == "__main__":
    main()
