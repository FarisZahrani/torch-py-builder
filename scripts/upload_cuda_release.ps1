[CmdletBinding()]
param(
    [string]$TorchVersion,
    [string]$ReleaseTag,
    [string]$Repository,
    [string]$GitHubToken,
    [string]$AssetsDirectory
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $AssetsDirectory) {
    $AssetsDirectory = Join-Path $repoRoot 'build\local-cuda\release-assets'
}

$uploadScript = Join-Path $repoRoot 'scripts\build_cuda_local.ps1'
$uploadArgs = @(
    '-UploadOnly',
    '-TargetOs', 'linux'
)
if ($TorchVersion) { $uploadArgs += @('-TorchVersion', $TorchVersion) }
if ($ReleaseTag) { $uploadArgs += @('-ReleaseTag', $ReleaseTag) }
if ($Repository) { $uploadArgs += @('-Repository', $Repository) }
if ($GitHubToken) { $uploadArgs += @('-GitHubToken', $GitHubToken) }

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $uploadScript @uploadArgs
