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
    ensure_pip_available,
    git_submodule_environment,
    update_pytorch_submodules,
)


def test_single_cuda_toolkit_is_current_default() -> None:
    assert SUPPORTED_TORCH_VERSION == "2.11.0"
    assert CUDA_TOOLKIT_VERSION == "12.8"


def test_cuda_builder_reads_the_shared_torch_pin() -> None:
    import json

    matrix = json.loads((ROOT / "config" / "build_matrix.json").read_text(encoding="utf-8"))
    assert SUPPORTED_TORCH_VERSION == matrix["torch_version"]


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


def test_missing_pip_is_bootstrapped_with_ensurepip(monkeypatch, tmp_path) -> None:
    class Result:
        returncode = 1

    commands = []
    monkeypatch.setattr("build_cuda_local.subprocess.run", lambda *args, **kwargs: Result())
    monkeypatch.setattr(
        "build_cuda_local.run_command",
        lambda command, **kwargs: commands.append(command),
    )

    ensure_pip_available(tmp_path)

    assert commands[0][2:] == ["ensurepip", "--upgrade"]
    assert commands[1][2:] == ["pip", "--version"]


def test_windows_submodule_git_config_reaches_nested_processes() -> None:
    environment = git_submodule_environment("windows")

    assert environment == {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.longpaths",
        "GIT_CONFIG_VALUE_0": "true",
    }
    assert git_submodule_environment("linux") is None


def test_submodule_update_retries_transient_failure(monkeypatch, tmp_path) -> None:
    update_attempts = 0
    sleeps = []

    def fake_run(command, **kwargs):
        nonlocal update_attempts
        if command[:3] == ["git", "submodule", "update"]:
            update_attempts += 1
            if update_attempts == 1:
                raise RuntimeError("temporary network failure")

    monkeypatch.setattr("build_cuda_local.run_command", fake_run)
    monkeypatch.setattr("build_cuda_local.time.sleep", sleeps.append)

    update_pytorch_submodules(tmp_path, "windows", attempts=3)

    assert update_attempts == 2
    assert sleeps == [5]
