#!/usr/bin/env python3
"""Build local CUDA torch-family wheels for the current OS."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
HEARTBEAT_SECONDS = 300
LINUX_CUDA_ARCH_LIST = "5.0;6.0;7.0;7.5;8.0;8.6;8.9;9.0+PTX"
WINDOWS_CUDA_ARCH_LIST = "7.5;8.0;8.6;8.9;9.0"


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(message: str) -> None:
    print(f"[{timestamp()}] {message}", flush=True)


def command_string(command: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(command)
    return " ".join(command)


def directory_size_label(path: Path) -> str:
    if not path.exists():
        return "n/a"
    total = 0
    for file_path in path.rglob("*"):
        if file_path.is_file():
            try:
                total += file_path.stat().st_size
            except OSError:
                continue
    if total == 0:
        return "0.00 GB"
    return f"{total / (1024 ** 3):.2f} GB"


def run_command(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    label: str,
    heartbeat_paths: list[Path] | None = None,
) -> None:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    heartbeat_paths = heartbeat_paths or []
    log(f"Starting {label}: {command_string(command)}")
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=merged_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    stop_event = threading.Event()

    def heartbeat() -> None:
        while not stop_event.wait(HEARTBEAT_SECONDS):
            details = [f"{path.name}={directory_size_label(path)}" for path in heartbeat_paths]
            suffix = f" | {' | '.join(details)}" if details else ""
            log(f"Heartbeat {label}{suffix}")

    heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
    heartbeat_thread.start()

    assert process.stdout is not None
    try:
        for line in process.stdout:
            print(line.rstrip(), flush=True)
    finally:
        return_code = process.wait()
        stop_event.set()
        heartbeat_thread.join(timeout=1)

    if return_code != 0:
        raise RuntimeError(f"{label} failed with exit code {return_code}")

    log(f"Completed {label}")


def capture_command(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> str:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        env=merged_env,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def current_target_os() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    raise SystemExit(f"Unsupported host OS for local CUDA builds: {sys.platform}")


def python_tag() -> str:
    return f"cp{sys.version_info.major}{sys.version_info.minor}"


def ensure_python_version(expected_version: str) -> None:
    actual = f"{sys.version_info.major}.{sys.version_info.minor}"
    if actual != expected_version:
        raise SystemExit(
            f"Expected Python {expected_version} but current interpreter is {actual}: {sys.executable}"
        )


def ensure_checkout(destination: Path, repository_url: str, ref: str) -> None:
    git_dir = destination / ".git"
    if not git_dir.exists():
        if destination.exists():
            shutil.rmtree(destination)
        run_command(
            ["git", "clone", "--branch", ref, "--depth", "1", repository_url, str(destination)],
            cwd=destination.parent,
            label=f"Clone {destination.name}",
        )
        return

    log(f"Reusing checkout at {destination}")


def reset_directory(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def optional_sccache_environment() -> dict[str, str]:
    if shutil.which("sccache") is None:
        return {}
    return {
        "USE_RELATIVE_PATHS": "1",
        "CMAKE_C_COMPILER_LAUNCHER": "sccache",
        "CMAKE_CXX_COMPILER_LAUNCHER": "sccache",
        "CMAKE_CUDA_COMPILER_LAUNCHER": "sccache",
    }


def show_sccache_stats(work_root: Path) -> None:
    if shutil.which("sccache") is None:
        return
    try:
        run_command(["sccache", "--show-stats"], cwd=work_root, label="Show sccache stats")
    except RuntimeError:
        log("sccache stats were unavailable; continuing")


def bootstrap_system_dependencies(target_os: str, work_root: Path) -> None:
    if target_os == "linux":
        run_command(["sudo", "-n", "apt-get", "update"], cwd=work_root, label="apt-get update")
        run_command(
            [
                "sudo",
                "-n",
                "apt-get",
                "install",
                "-y",
                "build-essential",
                "cmake",
                "git",
                "libjpeg-dev",
                "libomp-dev",
                "libopenblas-dev",
                "libpng-dev",
                "libwebp-dev",
                "ninja-build",
            ],
            cwd=work_root,
            label="Install Linux system dependencies",
        )
        return

    if target_os == "windows":
        if shutil.which("choco") is None:
            raise SystemExit("Chocolatey is required for --bootstrap-system-deps on Windows.")
        run_command(
            ["choco", "install", "cmake", "ninja", "-y"],
            cwd=work_root,
            label="Install Windows system dependencies",
        )
        return

    raise SystemExit(f"Unsupported bootstrap target OS: {target_os}")


def ensure_cuda_home(target_os: str) -> str:
    for candidate in (os.environ.get("CUDA_PATH"), os.environ.get("CUDA_HOME")):
        if candidate and Path(candidate).exists():
            return candidate

    nvcc = shutil.which("nvcc")
    if nvcc:
        return str(Path(nvcc).resolve().parent.parent)

    if target_os == "linux":
        for candidate in ("/usr/local/cuda", "/opt/cuda"):
            if Path(candidate).exists():
                return candidate

    raise SystemExit(
        "Could not determine CUDA_HOME. Install CUDA 12.4 and expose CUDA_PATH/CUDA_HOME or nvcc."
    )


def get_pip_cmake_bin(cwd: Path) -> Path:
    output = capture_command(
        [
            sys.executable,
            "-c",
            (
                "import cmake, os;"
                "print(os.path.join(os.path.dirname(cmake.__file__), 'data', 'bin'))"
            ),
        ],
        cwd=cwd,
    )
    return Path(output)


def selected_wheel(source_dir: Path, expected_tag: str) -> Path:
    wheels = sorted(source_dir.glob("*.whl"))
    if not wheels:
        raise SystemExit(f"No wheel found in {source_dir}")

    matches = [wheel for wheel in wheels if expected_tag in wheel.name]
    if not matches:
        found = ", ".join(wheel.name for wheel in wheels)
        raise SystemExit(f"No wheel matching {expected_tag} found in {source_dir}: {found}")

    if len(matches) != 1:
        found = ", ".join(wheel.name for wheel in matches)
        raise SystemExit(
            f"Expected exactly one wheel matching {expected_tag} in {source_dir}, found {len(matches)}: {found}"
        )
    return matches[0]


def copy_to_artifacts(wheel_path: Path, artifact_root: Path) -> Path:
    artifact_root.mkdir(parents=True, exist_ok=True)
    destination = artifact_root / wheel_path.name
    shutil.copy2(wheel_path, destination)
    return destination


def validate_wheel_structure(wheel_path: Path, expected_version: str, expected_package: str | None = None) -> None:
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "validate_wheel.py"),
        str(wheel_path),
    ]
    if expected_package:
        command.extend(["--expected-package", expected_package])
    command.extend(["--expected-version", expected_version])
    run_command(command, cwd=REPO_ROOT, label=f"Validate {wheel_path.name}")


def run_python_inline(code: str, *, cwd: Path, env: dict[str, str] | None = None, label: str) -> None:
    run_command([sys.executable, "-c", code], cwd=cwd, env=env, label=label)


def pip_install(arguments: list[str], *, cwd: Path, env: dict[str, str] | None = None, label: str) -> None:
    run_command([sys.executable, "-m", "pip", *arguments], cwd=cwd, env=env, label=label)


def build_environment(target_os: str, torch_version: str, cuda_home: str, work_root: Path) -> dict[str, str]:
    environment = {
        "PYTORCH_BUILD_VERSION": torch_version,
        "PYTORCH_BUILD_NUMBER": "1",
        "USE_CUDA": "1",
        "USE_ROCM": "0",
        "USE_NUMPY": "1",
        "BUILD_TEST": "0",
        "CUDA_HOME": cuda_home,
    }
    environment.update(optional_sccache_environment())

    max_jobs = str(os.cpu_count() or 4)
    environment["MAX_JOBS"] = max_jobs
    log(f"Using MAX_JOBS={max_jobs}")

    if target_os == "linux":
        environment.update(
            {
                "USE_MKLDNN": "1",
                "USE_DISTRIBUTED": "0",
                "TORCH_CUDA_ARCH_LIST": LINUX_CUDA_ARCH_LIST,
            }
        )
        jemalloc = next(iter(Path("/usr/lib").glob("**/libjemalloc.so.2")), None)
        if jemalloc:
            environment["LD_PRELOAD"] = str(jemalloc)
            log(f"Using jemalloc: {jemalloc}")
    else:
        environment.update(
            {
                "CMAKE_GENERATOR": "Ninja",
                "TORCH_CUDA_ARCH_LIST": WINDOWS_CUDA_ARCH_LIST,
            }
        )

    python_executable = sys.executable
    environment["PYTHON_EXECUTABLE"] = python_executable
    environment["Python_EXECUTABLE"] = python_executable
    environment["Python3_EXECUTABLE"] = python_executable
    environment["DESIRED_PYTHON"] = python_tag()

    cmake_bin = get_pip_cmake_bin(work_root)
    environment["PATH"] = str(cmake_bin) + os.pathsep + environment.get("PATH", os.environ.get("PATH", ""))
    return environment


def build_torch(args: argparse.Namespace, target_os: str, work_root: Path, artifact_root: Path) -> Path:
    source_dir = work_root / f"pytorch-src-v{args.torch_version}"
    ensure_checkout(source_dir, "https://github.com/pytorch/pytorch", f"v{args.torch_version}")

    run_command(
        ["git", "submodule", "sync", "--recursive"],
        cwd=source_dir,
        label="Sync PyTorch submodules",
    )
    run_command(
        ["git", "submodule", "update", "--init", "--recursive", "--depth", "1", "--jobs", "4"],
        cwd=source_dir,
        label="Update PyTorch submodules",
    )

    pip_install(["install", "--upgrade", "pip"], cwd=source_dir, label="Upgrade pip")
    pip_install(
        ["install", "cmake<4", "ninja", "build", "wheel"],
        cwd=source_dir,
        label="Install PyTorch build tools",
    )
    pip_install(["install", "-r", "requirements.txt"], cwd=source_dir, label="Install PyTorch requirements")

    cuda_home = ensure_cuda_home(target_os)
    environment = build_environment(target_os, args.torch_version, cuda_home, source_dir)

    remove_path(source_dir / "dist")

    show_sccache_stats(work_root)
    run_command(
        [sys.executable, "tools/build_libtorch.py"],
        cwd=source_dir,
        env=environment,
        label=f"Build libtorch ({target_os})",
        heartbeat_paths=[source_dir / "build", source_dir / "dist"],
    )
    run_command(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation"],
        cwd=source_dir,
        env=environment,
        label=f"Build torch wheel ({target_os})",
        heartbeat_paths=[source_dir / "build", source_dir / "dist"],
    )
    show_sccache_stats(work_root)

    wheel_path = selected_wheel(source_dir / "dist", python_tag())
    copied_wheel = copy_to_artifacts(wheel_path, artifact_root)
    validate_wheel_structure(copied_wheel, args.torch_version)

    smoke_code = (
        "import torch\n"
        "print(f'torch version: {torch.__version__}')\n"
        "t = torch.ones(2, 2)\n"
        "assert t.sum().item() == 4.0\n"
        "linear = torch.nn.Linear(2, 2)\n"
        "out = linear(t)\n"
        "print(f'nn.Linear output shape: {tuple(out.shape)}')\n"
        "assert torch.version.cuda is not None\n"
        "print(f'CUDA compiled version: {torch.version.cuda}')\n"
        "print('smoke-ok')\n"
    )
    pip_install(["install", "--force-reinstall", str(copied_wheel)], cwd=source_dir, label="Install built torch wheel")
    run_python_inline(smoke_code, cwd=source_dir, label=f"Smoke test torch ({target_os})")
    return copied_wheel


def installed_torch_version(cwd: Path) -> str:
    return capture_command([sys.executable, "-c", "import torch; print(torch.__version__)"], cwd=cwd)


def build_torchvision(
    args: argparse.Namespace,
    target_os: str,
    work_root: Path,
    artifact_root: Path,
    torch_wheel: Path,
) -> Path:
    source_dir = work_root / f"vision-src-v{args.torchvision_version}"
    ensure_checkout(source_dir, "https://github.com/pytorch/vision", f"v{args.torchvision_version}")

    pip_install(["install", "--force-reinstall", str(torch_wheel)], cwd=source_dir, label="Install local torch wheel for torchvision")
    installed_version = installed_torch_version(source_dir)
    pip_install(
        ["install", "cmake<4", "ninja", "numpy", "pillow", "setuptools<82", "wheel"],
        cwd=source_dir,
        label="Install torchvision build tools",
    )

    remove_path(source_dir / "dist")
    environment = {
        "BUILD_VERSION": args.torchvision_version,
        "PYTORCH_VERSION": installed_version,
        "SETUPTOOLS_USE_DISTUTILS": "local",
        "FORCE_CUDA": "1",
    }
    if target_os == "linux":
        environment["CUDA_HOME"] = ensure_cuda_home(target_os)
    else:
        environment["DISTUTILS_USE_SDK"] = "1"
        environment["CUDA_HOME"] = ensure_cuda_home(target_os)

    run_command(
        [sys.executable, "setup.py", "bdist_wheel"],
        cwd=source_dir,
        env=environment,
        label=f"Build torchvision wheel ({target_os})",
        heartbeat_paths=[source_dir / "build", source_dir / "dist"],
    )

    wheel_path = selected_wheel(source_dir / "dist", python_tag())
    copied_wheel = copy_to_artifacts(wheel_path, artifact_root)
    validate_wheel_structure(copied_wheel, args.torchvision_version, expected_package="torchvision")

    smoke_code = (
        "import torch, torchvision\n"
        "print(f'torchvision version: {torchvision.__version__}')\n"
        "boxes = torch.tensor([[0.0, 0.0, 10.0, 10.0], [1.0, 1.0, 9.0, 9.0]])\n"
        "scores = torch.tensor([0.9, 0.8])\n"
        "keep = torchvision.ops.nms(boxes, scores, 0.5)\n"
        "print(f'nms keep: {keep.tolist()}')\n"
        "cuda_version = torch.ops.torchvision._cuda_version()\n"
        "assert cuda_version != -1\n"
        "print(f'torchvision cuda version: {cuda_version}')\n"
        "print('smoke-ok')\n"
    )
    pip_install(
        ["install", "--force-reinstall", "--no-deps", str(copied_wheel)],
        cwd=source_dir,
        label="Install built torchvision wheel",
    )
    run_python_inline(smoke_code, cwd=source_dir, label=f"Smoke test torchvision ({target_os})")
    return copied_wheel


def build_torchaudio(
    args: argparse.Namespace,
    target_os: str,
    work_root: Path,
    artifact_root: Path,
    torch_wheel: Path,
) -> Path:
    source_dir = work_root / f"audio-src-v{args.torchaudio_version}"
    ensure_checkout(source_dir, "https://github.com/pytorch/audio", f"v{args.torchaudio_version}")

    pip_install(["install", "--force-reinstall", str(torch_wheel)], cwd=source_dir, label="Install local torch wheel for torchaudio")
    pip_install(
        ["install", "cmake<4", "ninja", "setuptools<82", "wheel"],
        cwd=source_dir,
        label="Install torchaudio build tools",
    )

    remove_path(source_dir / "dist")
    environment = {
        "BUILD_VERSION": args.torchaudio_version,
        "SETUPTOOLS_USE_DISTUTILS": "local",
        "USE_CUDA": "1",
    }
    if target_os == "linux":
        environment["CUDA_HOME"] = ensure_cuda_home(target_os)
    else:
        environment["DISTUTILS_USE_SDK"] = "1"
        environment["CUDA_HOME"] = ensure_cuda_home(target_os)

    run_command(
        [sys.executable, "setup.py", "bdist_wheel"],
        cwd=source_dir,
        env=environment,
        label=f"Build torchaudio wheel ({target_os})",
        heartbeat_paths=[source_dir / "build", source_dir / "dist"],
    )

    wheel_path = selected_wheel(source_dir / "dist", python_tag())
    copied_wheel = copy_to_artifacts(wheel_path, artifact_root)
    validate_wheel_structure(copied_wheel, args.torchaudio_version, expected_package="torchaudio")

    smoke_code = (
        "import torch, torchaudio\n"
        "print(f'torchaudio version: {torchaudio.__version__}')\n"
        "waveform = torch.zeros(1, 16000)\n"
        "spec = torchaudio.transforms.MelSpectrogram(sample_rate=16000)(waveform)\n"
        "print(f'mel spectrogram shape: {tuple(spec.shape)}')\n"
        "cuda_version = torchaudio._extension._check_cuda_version()\n"
        "assert cuda_version is not None\n"
        "print(f'torchaudio cuda version: {cuda_version}')\n"
        "print('smoke-ok')\n"
    )
    pip_install(
        ["install", "--force-reinstall", "--no-deps", str(copied_wheel)],
        cwd=source_dir,
        label="Install built torchaudio wheel",
    )
    run_python_inline(smoke_code, cwd=source_dir, label=f"Smoke test torchaudio ({target_os})")
    return copied_wheel


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build local CUDA torch-family wheels for the current OS.")
    parser.add_argument("--target-os", required=True, choices=["linux", "windows"])
    parser.add_argument("--python-version", required=True)
    parser.add_argument("--torch-version", required=True)
    parser.add_argument("--torchvision-version", required=True)
    parser.add_argument("--torchaudio-version", required=True)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--work-root", required=True)
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--bootstrap-system-deps", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    target_os = current_target_os()
    if args.target_os != target_os:
        raise SystemExit(f"This script is running on {target_os}, not {args.target_os}.")

    ensure_python_version(args.python_version)

    work_root = Path(args.work_root).expanduser().resolve()
    artifact_root = Path(args.artifact_root).expanduser().resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    artifact_root.mkdir(parents=True, exist_ok=True)

    if args.bootstrap_system_deps:
        bootstrap_system_dependencies(target_os, work_root)

    log(
        f"Building CUDA wheels for {target_os} | python={args.python_version} | "
        f"torch={args.torch_version} | release_tag={args.release_tag}"
    )

    torch_wheel = build_torch(args, target_os, work_root, artifact_root)
    torchvision_wheel = build_torchvision(args, target_os, work_root, artifact_root, torch_wheel)
    torchaudio_wheel = build_torchaudio(args, target_os, work_root, artifact_root, torch_wheel)

    log("Finished local CUDA build set:")
    for wheel_path in (torch_wheel, torchvision_wheel, torchaudio_wheel):
        print(f" - {wheel_path}")


if __name__ == "__main__":
    main()