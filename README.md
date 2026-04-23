# torch-py-builder

Source-built PyTorch wheels for platforms and Python versions not covered by official PyPI releases.

## Problem

PyTorch's official PyPI wheels only support a limited set of platform/Python combinations. As of 2025, macOS Intel (x86\_64) and Python 3.13+ are no longer covered for the latest releases. This project builds PyTorch from source on GitHub Actions and publishes the wheels as GitHub Releases.

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
| `build.yml`    | Automatic / manual       | Resolve latest PyTorch, build & release wheels   |
| `test.yml`     | Push / PR                | Validate scripts and version resolution          |
| `cleanup.yml`  | Automatic / manual       | Remove old artifacts and workflow runs           |

## Release State

`release-state/latest.json` tracks the last successfully released PyTorch version. It is updated automatically on each release and committed back to the repository. History snapshots are kept in `release-state/history/`.

## Manual Trigger

Use the **Build PyTorch Wheels** workflow with `workflow_dispatch` to:

- Force a rebuild of the current version
- Override the PyTorch version to build (e.g. build `2.6.0` specifically)
- Filter builds to a specific OS, architecture, or Python version
- Set a custom release tag

## Scripts

| Script                     | Purpose                                          |
|----------------------------|--------------------------------------------------|
| `resolve_latest_torch.py`  | Fetch the latest stable PyTorch release from GitHub |
| `plan_release.py`          | Compare resolved version to state; decide whether to build |
| `update_release_state.py`  | Write `release-state/latest.json` and history snapshot |
| `validate_wheel.py`        | Structural validation of a built `.whl` file     |
