#!/usr/bin/env python3
"""Verify import torch works without CUDA toolkit directories on PATH."""
from __future__ import annotations

import os
import site
import sys
from pathlib import Path


def isolated_torch_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in list(env):
        if key.upper().startswith("CUDA"):
            env.pop(key, None)

    torch_lib: Path | None = None
    for site_packages in site.getsitepackages():
        candidate = Path(site_packages) / "torch" / "lib"
        if candidate.is_dir():
            torch_lib = candidate
            break
    if torch_lib is None:
        raise SystemExit("Could not find installed torch/lib for isolated import test.")

    system_root = env.get("SystemRoot", r"C:\Windows")
    filtered_path: list[str] = []
    for entry in env.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        lowered = entry.lower()
        if "cuda" in lowered or "nvidia gpu computing" in lowered:
            continue
        filtered_path.append(entry)

    env["PATH"] = os.pathsep.join([str(torch_lib), str(Path(system_root) / "System32"), *filtered_path])
    return env


def main() -> None:
    if sys.platform != "win32":
        print("Skipping isolated import test on non-Windows platform.")
        return

    env = isolated_torch_env()
    code = (
        "import os, site\n"
        "dll_dirs = []\n"
        "for sp in site.getsitepackages():\n"
        "    torch_lib = os.path.join(sp, 'torch', 'lib')\n"
        "    if os.path.isdir(torch_lib):\n"
        "        dll_dirs.append(torch_lib)\n"
        "for dll_dir in dll_dirs:\n"
        "    os.add_dll_directory(dll_dir)\n"
        "if dll_dirs:\n"
        "    os.environ['PATH'] = os.pathsep.join(dll_dirs + [os.environ.get('PATH', '')])\n"
        "import torch\n"
        "assert torch.version.cuda is not None\n"
        "print(f'torch={torch.__version__} cuda={torch.version.cuda}')\n"
        "if torch.cuda.is_available():\n"
        "    print(torch.cuda.get_device_name(0))\n"
        "print('isolated-import-ok')\n"
    )
    import subprocess

    completed = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
