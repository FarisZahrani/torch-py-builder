#!/usr/bin/env bash
set -euo pipefail

WHEEL="${1:?wheel path required}"
TMP="$(mktemp -d)"
export TMP WHEEL
trap 'rm -rf "$TMP"' EXIT

python3 - <<'PY'
import os
import zipfile
from pathlib import Path

wheel = Path(os.environ["WHEEL"])
tmpdir = Path(os.environ["TMP"])
with zipfile.ZipFile(wheel) as archive:
    for name in (
        "torch/lib/libc10_cuda.so",
        "torch/lib/libtorch_cuda.so",
        "torch/lib/libtorch_cpu.so",
    ):
        archive.extract(name, tmpdir)
        print(f"extracted {name}")
PY

echo "--- ldd libc10_cuda.so ---"
ldd "$TMP/torch/lib/libc10_cuda.so"
echo
echo "--- libtorch_cuda.so CUDA-related / not found ---"
ldd "$TMP/torch/lib/libtorch_cuda.so" | grep -Ei 'cuda|cublas|cudnn|cufft|curand|cusparse|cusolver|nvrtc|nccl|not found' || true
