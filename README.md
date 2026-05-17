# torch-py-builder

Source-built torch, torchvision, and torchaudio wheels for platforms and Python versions not covered by official PyPI releases.

## Problem

PyTorch's official PyPI wheels only support a limited set of platform/Python combinations. As of 2025, macOS Intel (x86\_64) and Python 3.13+ are no longer covered for the latest releases. This project builds torch from source on GitHub Actions, then builds matching torchvision and torchaudio wheels, and publishes them together as GitHub Releases.

## Supported Platforms

| Platform          | Architecture | Runner          |
|-------------------|-------------|-----------------|
| Linux             | x86\_64      | ubuntu-24.04    |
| Windows           | x86\_64      | windows-2022    |
| macOS (Intel)     | x86\_64      | macos-15-intel  |
| macOS (Apple Silicon) | arm64   | macos-14        |

Linux and Windows builds include both CPU and CUDA (12.4) variants. macOS Intel is CPU-only. macOS Apple Silicon uses MPS (Metal Performance Shaders).

## Configuration

### `config/build_matrix.json`

Defines which Python versions and target platforms to build for:

```json
{
  "python_versions": ["3.11", "3.12", "3.13"],
  "targets": [...]
}
```

Edit this file to add or remove Python versions or platforms.

## Workflows

| Workflow       | Trigger                  | Purpose                                          |
|----------------|--------------------------|--------------------------------------------------|
| `sync.yml`     | Automatic / manual       | Detect new PyTorch release, trigger build        |
| `build.yml`    | Automatic / manual       | Resolve latest PyTorch, build and release torch, torchvision, and torchaudio wheels |
| `test.yml`     | Push / PR                | Validate scripts and version resolution          |
| `cleanup.yml`  | Automatic / manual       | Remove old artifacts and workflow runs           |

## Release Layout

Each GitHub release uses a single torch-based tag such as `torch-2.7.0`.

- `torch`, `torchvision`, and `torchaudio` are published as separate wheel files under that same release.
- torchvision and torchaudio versions are resolved to match the torch version for the release.
- Companion wheels are built against the matching torch wheel for the same OS, architecture, backend, and Python version.

## Release State

`release-state/latest.json` tracks the last successfully released torch version and shared release tag. It is updated automatically on each release and committed back to the repository. History snapshots are kept in `release-state/history/`.

## Manual Trigger

Use the **Build PyTorch Family Wheels** workflow with `workflow_dispatch` to:

- Force a rebuild of the current version
- Override the PyTorch version to build (e.g. build `2.6.0` specifically)
- Filter builds to a specific OS, architecture, or Python version
- Set a shared custom release tag for torch, torchvision, and torchaudio assets

## Scripts

| Script                     | Purpose                                          |
|----------------------------|--------------------------------------------------|
| `resolve_latest_torch.py`  | Fetch the latest stable PyTorch release from GitHub |
| `plan_release.py`          | Compare the resolved torch version to state and decide whether to build a shared release |
| `update_release_state.py`  | Write `release-state/latest.json` and history snapshots for a shared release |
| `resolve_companion_versions.py` | Resolve matching torchvision and torchaudio versions for a torch release |
| `validate_wheel.py`        | Structural validation of a built package `.whl` file |
| `build_cuda_local.py`      | Build local CUDA `torch`, `torchvision`, and `torchaudio` wheels for the current OS |
| `build_cuda_local.ps1`     | Orchestrate native Windows and WSL2 Linux CUDA builds, then upload finished wheels to GitHub Releases |

## Local CUDA Builds

Use `scripts/build_cuda_local.ps1` from Windows when GitHub-hosted runners are too slow for CUDA builds. The script:

- Builds Windows CUDA wheels natively on Windows
- Builds Linux CUDA wheels inside WSL2
- Reuses `release-state/latest.json` to default the torch version, release tag, and repository
- Uploads the finished wheel files plus `SHA256SUMS.txt` to the matching GitHub release tag

Example:

```powershell
$env:GITHUB_TOKEN = "<token with contents:write>"
pwsh -File scripts/build_cuda_local.ps1 -TargetOs both -PythonVersions 3.13
```

Useful flags:

- `-TargetOs windows` to build only Windows CUDA wheels
- `-TargetOs linux` to build only Linux CUDA wheels through WSL2
- `-SkipUpload` to keep wheels local without publishing them
- `-BootstrapSystemDependencies` to let the script try package-manager installs for missing local build tools
- `-ReleaseTag`, `-TorchVersion`, and `-Repository` to override release-state defaults

Local prerequisites:

- Windows host with Python for each target version, Visual Studio Build Tools 2022, Git, CUDA 12.4, and WSL2
- Linux WSL2 distro with matching Python versions, Git, CUDA 12.4, and the usual build toolchain
- A GitHub token with `contents:write` access if you want automatic release uploads

The PowerShell entry script creates per-version virtual environments for Windows and WSL2 so the local build dependencies stay isolated from your normal Python installs.
