#!/usr/bin/env python3
"""Import and run lightweight inference checks for built CUDA wheels."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def add_cuda_to_path() -> None:
    if sys.platform != "win32":
        return
    cuda_home = os.environ.get("CUDA_HOME") or os.environ.get("CUDA_PATH")
    if not cuda_home:
        return
    cuda_root = Path(cuda_home)
    prefixes = [
        cuda_root / "bin",
        cuda_root / "extras" / "CUPTI" / "lib64",
        cuda_root / "extras" / "CUPTI" / "bin",
    ]
    try:
        import site

        for site_packages in site.getsitepackages():
            torch_lib = Path(site_packages) / "torch" / "lib"
            if torch_lib.is_dir():
                prefixes.append(torch_lib)
                break
    except Exception:
        pass
    os.environ["PATH"] = os.pathsep.join(str(p) for p in prefixes if p.exists()) + os.pathsep + os.environ.get("PATH", "")


def run_checks(label: str) -> None:
    import torch
    import torchaudio
    import torchvision

    print(f"[{label}] torch={torch.__version__} cuda={torch.version.cuda}")
    print(f"[{label}] torchvision={torchvision.__version__}")
    print(f"[{label}] torchaudio={torchaudio.__version__}")

    x = torch.randn(4, 3, 32, 32)
    with torch.inference_mode():
        y = torchvision.models.resnet18(weights=None)(x)
    print(f"[{label}] resnet18 cpu output shape={tuple(y.shape)}")

    waveform = torch.randn(1, 16000)
    with torch.inference_mode():
        spec = torchaudio.transforms.MelSpectrogram()(waveform)
    print(f"[{label}] mel spectrogram shape={tuple(spec.shape)}")

    if torch.cuda.is_available():
        device = torch.device("cuda")
        x_gpu = x.to(device)
        with torch.inference_mode():
            y_gpu = torchvision.models.resnet18(weights=None).to(device)(x_gpu)
            z_gpu = torch.mm(torch.randn(128, 128, device=device), torch.randn(128, 128, device=device))
        print(f"[{label}] resnet18 cuda output shape={tuple(y_gpu.shape)}")
        print(f"[{label}] cuda matmul sum={z_gpu.sum().item():.4f} device={z_gpu.device}")
    else:
        print(f"[{label}] CUDA runtime not available; CPU checks only")

    print(f"[{label}] inference-ok")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test import and inference for CUDA wheels.")
    parser.add_argument("--label", default="local")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    add_cuda_to_path()
    run_checks(args.label)


if __name__ == "__main__":
    main()
