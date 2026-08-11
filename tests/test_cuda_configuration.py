from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_cuda_local import (  # noqa: E402
    CUDA_ARCH_LIST,
    CUDA_TOOLKIT_VERSION,
    SUPPORTED_TORCH_VERSION,
    build_environment,
)


def test_single_cuda_toolkit_is_current_default() -> None:
    assert SUPPORTED_TORCH_VERSION == "2.11.0"
    assert CUDA_TOOLKIT_VERSION == "12.8"


def test_cuda_architecture_list_covers_turing_through_blackwell() -> None:
    assert CUDA_ARCH_LIST == "5.0;5.2;6.0;6.1;7.0;7.5;8.0;8.6;8.9;9.0;10.0;12.0+PTX"


def test_workflow_has_no_competing_cuda_toolkit_versions() -> None:
    workflow = (ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")

    assert "cuda: '12.8.0'" in workflow
    assert "cuda: '12.4.1'" not in workflow


def test_optional_cuda_acceleration_libraries_are_disabled(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("build_cuda_local.optional_sccache_environment", lambda: {})
    monkeypatch.setattr("build_cuda_local.max_parallel_jobs", lambda target_os: 1)
    monkeypatch.setattr("build_cuda_local.get_pip_cmake_bin", lambda work_root: tmp_path)

    environment = build_environment("windows", "2.11.0", "C:/CUDA/v12.8", tmp_path)

    assert environment["USE_CUDNN"] == "0"
    assert environment["USE_CUSPARSELT"] == "0"
    assert environment["USE_FLASH_ATTENTION"] == "0"
    assert environment["USE_MEM_EFF_ATTENTION"] == "0"
