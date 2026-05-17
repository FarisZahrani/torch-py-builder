[CmdletBinding()]
param(
    [ValidateSet('both', 'windows', 'linux')]
    [string]$TargetOs = 'both',

    [string[]]$PythonVersions,

    [string]$TorchVersion,

    [string]$ReleaseTag,

    [string]$Repository,

    [string]$GitHubToken,

    [string]$WslDistro,

    [string]$WslWorkRoot = '~/.cache/torch-py-builder/local-cuda',

    [switch]$BootstrapSystemDependencies,

    [switch]$SkipUpload
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Step {
    param([string]$Message)
    $timestamp = [DateTime]::UtcNow.ToString('s') + 'Z'
    Write-Host "[$timestamp] $Message"
}

function Get-RepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
}

function Invoke-CommandArray {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Command,

        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory
    )

    Write-Step ("Running: " + ($Command -join ' '))
    Push-Location $WorkingDirectory
    try {
        if ($Command.Count -eq 1) {
            & $Command[0]
        }
        else {
            & $Command[0] $Command[1..($Command.Count - 1)]
        }
        if ($LASTEXITCODE -ne 0) {
            throw "Command failed with exit code ${LASTEXITCODE}: $($Command -join ' ')"
        }
    }
    finally {
        Pop-Location
    }
}

function Resolve-WindowsPythonLauncher {
    param([Parameter(Mandatory = $true)][string]$Version)

    if (Get-Command py -ErrorAction SilentlyContinue) {
        return @('py', "-$Version")
    }

    if (Get-Command python -ErrorAction SilentlyContinue) {
        return @('python')
    }

    throw "Could not find a Windows Python launcher for Python $Version."
}

function Ensure-WindowsVenv {
    param(
        [Parameter(Mandatory = $true)][string]$Version,
        [Parameter(Mandatory = $true)][string]$VenvPath,
        [Parameter(Mandatory = $true)][string]$RepoRoot
    )

    $venvPython = Join-Path $VenvPath 'Scripts\python.exe'
    if (-not (Test-Path $venvPython)) {
        $launcher = Resolve-WindowsPythonLauncher -Version $Version
        $command = $launcher + @('-m', 'venv', $VenvPath)
        Invoke-CommandArray -Command $command -WorkingDirectory $RepoRoot
    }
    return $venvPython
}

function Import-VsDevEnvironment {
    $vswherePath = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path $vswherePath)) {
        throw "vswhere.exe was not found. Install Visual Studio Build Tools 2022."
    }

    $installationPath = & $vswherePath -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if (-not $installationPath) {
        throw 'Could not find a Visual Studio installation with MSVC tools.'
    }

    $vcvarsPath = Join-Path $installationPath 'VC\Auxiliary\Build\vcvars64.bat'
    if (-not (Test-Path $vcvarsPath)) {
        throw "vcvars64.bat was not found at $vcvarsPath"
    }

    Write-Step 'Importing MSVC build environment'
    $environmentDump = & cmd.exe /c "`"$vcvarsPath`" >nul && set"
    foreach ($line in $environmentDump) {
        if ($line -match '^(.*?)=(.*)$') {
            [System.Environment]::SetEnvironmentVariable($matches[1], $matches[2])
        }
    }
}

function Convert-WindowsPathToWsl {
    param([Parameter(Mandatory = $true)][string]$WindowsPath)

    $resolvedPath = (Resolve-Path $WindowsPath).Path
    if ($resolvedPath -notmatch '^(?<drive>[A-Za-z]):\\(?<rest>.*)$') {
        throw "Cannot convert path to WSL form: $resolvedPath"
    }

    $drive = $matches['drive'].ToLowerInvariant()
    $rest = ($matches['rest'] -replace '\\', '/')
    return "/mnt/$drive/$rest"
}

function ConvertTo-BashSingleQuoted {
    param([Parameter(Mandatory = $true)][string]$Value)
    return "'" + ($Value -replace "'", "'\\''") + "'"
}

function Invoke-WslBash {
    param([Parameter(Mandatory = $true)][string]$CommandText)

    $arguments = @()
    if ($WslDistro) {
        $arguments += @('-d', $WslDistro)
    }
    $arguments += @('bash', '-lc', $CommandText)

    Write-Step "Running in WSL: $CommandText"
    & wsl.exe @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "WSL command failed with exit code $LASTEXITCODE"
    }
}

function Resolve-CompanionVersions {
    param(
        [Parameter(Mandatory = $true)][string]$TorchVersion,
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$PythonVersion
    )

    $launcher = Resolve-WindowsPythonLauncher -Version $PythonVersion
    $tempFile = Join-Path $RepoRoot 'build\local-cuda\companion-versions.json'
    $command = @(
        $launcher + @(
            (Join-Path $RepoRoot 'scripts\resolve_companion_versions.py'),
            '--torch-version', $TorchVersion,
            '--output', $tempFile
        )
    )
    Invoke-CommandArray -Command $command -WorkingDirectory $RepoRoot
    return Get-Content -Path $tempFile -Raw | ConvertFrom-Json
}

function New-Sha256File {
    param([Parameter(Mandatory = $true)][string]$AssetsDirectory)

    $assets = Get-ChildItem -Path $AssetsDirectory -File | Where-Object {
        $_.Extension -eq '.whl'
    } | Sort-Object Name

    if (-not $assets) {
        throw "No wheel files were produced in $AssetsDirectory"
    }

    $lines = foreach ($asset in $assets) {
        $hash = (Get-FileHash -Path $asset.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        "$hash  $($asset.Name)"
    }

    $checksumPath = Join-Path $AssetsDirectory 'SHA256SUMS.txt'
    Set-Content -Path $checksumPath -Value $lines -Encoding utf8
    return $checksumPath
}

function Get-GitHubToken {
    param([string]$ExplicitToken)

    if ($ExplicitToken) {
        return $ExplicitToken
    }
    if ($env:GITHUB_TOKEN) {
        return $env:GITHUB_TOKEN
    }
    if ($env:GH_TOKEN) {
        return $env:GH_TOKEN
    }
    throw 'Set -GitHubToken or the GITHUB_TOKEN/GH_TOKEN environment variable before uploading.'
}

function Invoke-GitHubJsonRequest {
    param(
        [Parameter(Mandatory = $true)][string]$Method,
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][string]$Token,
        $Body
    )

    $headers = @{
        Authorization = "Bearer $Token"
        Accept = 'application/vnd.github+json'
        'User-Agent' = 'torch-py-builder-local-cuda'
        'X-GitHub-Api-Version' = '2022-11-28'
    }

    if ($null -ne $Body) {
        $jsonBody = $Body | ConvertTo-Json -Depth 10
        return Invoke-RestMethod -Method $Method -Uri $Uri -Headers $headers -ContentType 'application/json' -Body $jsonBody
    }

    return Invoke-RestMethod -Method $Method -Uri $Uri -Headers $headers
}

function Get-ReleaseByTag {
    param(
        [Parameter(Mandatory = $true)][string]$Repository,
        [Parameter(Mandatory = $true)][string]$ReleaseTag,
        [Parameter(Mandatory = $true)][string]$Token
    )

    $uri = "https://api.github.com/repos/$Repository/releases/tags/$ReleaseTag"
    try {
        return Invoke-GitHubJsonRequest -Method GET -Uri $uri -Token $Token
    }
    catch {
        $statusCode = $_.Exception.Response.StatusCode.value__
        if ($statusCode -eq 404) {
            return $null
        }
        throw
    }
}

function New-ReleaseBody {
    param(
        [Parameter(Mandatory = $true)][string]$TorchVersion,
        [Parameter(Mandatory = $true)][string]$ReleaseTag
    )

    return @"
Source-built torch $TorchVersion, matching torchvision, and matching torchaudio wheels for platforms and Python versions not covered by official PyPI releases.

Package Layout
- The release tag is shared across the full package family and remains torch-based.
- torch, torchvision, and torchaudio are published as separate wheel files.
- CPU and MPS assets can be published by the normal GitHub Actions workflow.
- Local CUDA assets can be appended by this local build script.

Platforms & Backends
- Linux x86_64 | CUDA 12.4
- Windows x86_64 | CUDA 12.4

Notes
- These wheels preserve the normal package split: install torch, torchvision, and torchaudio separately as needed.
- CUDA wheels include compiled CUDA kernels. A physical NVIDIA GPU is required at runtime for GPU acceleration.
- Torch is built from the official PyTorch source at tag v$TorchVersion.
"@
}

function Get-OrCreateRelease {
    param(
        [Parameter(Mandatory = $true)][string]$Repository,
        [Parameter(Mandatory = $true)][string]$ReleaseTag,
        [Parameter(Mandatory = $true)][string]$TorchVersion,
        [Parameter(Mandatory = $true)][string]$Token
    )

    $release = Get-ReleaseByTag -Repository $Repository -ReleaseTag $ReleaseTag -Token $Token
    if ($release) {
        return $release
    }

    Write-Step "Creating release $ReleaseTag"
    return Invoke-GitHubJsonRequest -Method POST -Uri "https://api.github.com/repos/$Repository/releases" -Token $Token -Body @{
        tag_name = $ReleaseTag
        name = "PyTorch $TorchVersion - Source-Built torch, torchvision, and torchaudio Wheels"
        body = (New-ReleaseBody -TorchVersion $TorchVersion -ReleaseTag $ReleaseTag)
        draft = $false
        prerelease = $false
        generate_release_notes = $false
    }
}

function Remove-ReleaseAssetIfPresent {
    param(
        [Parameter(Mandatory = $true)]$Release,
        [Parameter(Mandatory = $true)][string]$AssetName,
        [Parameter(Mandatory = $true)][string]$Repository,
        [Parameter(Mandatory = $true)][string]$Token
    )

    $existingAsset = $Release.assets | Where-Object { $_.name -eq $AssetName } | Select-Object -First 1
    if (-not $existingAsset) {
        return
    }

    Write-Step "Deleting existing release asset $AssetName"
    Invoke-GitHubJsonRequest -Method DELETE -Uri "https://api.github.com/repos/$Repository/releases/assets/$($existingAsset.id)" -Token $Token | Out-Null
}

function Upload-ReleaseAsset {
    param(
        [Parameter(Mandatory = $true)]$Release,
        [Parameter(Mandatory = $true)][System.IO.FileInfo]$File,
        [Parameter(Mandatory = $true)][string]$Repository,
        [Parameter(Mandatory = $true)][string]$Token
    )

    Remove-ReleaseAssetIfPresent -Release $Release -AssetName $File.Name -Repository $Repository -Token $Token

    $headers = @{
        Authorization = "Bearer $Token"
        Accept = 'application/vnd.github+json'
        'User-Agent' = 'torch-py-builder-local-cuda'
        'X-GitHub-Api-Version' = '2022-11-28'
    }
    $uploadBase = ($Release.upload_url -replace '\{.*$', '')
    $encodedName = [System.Uri]::EscapeDataString($File.Name)
    $uploadUri = "$uploadBase?name=$encodedName"

    Write-Step "Uploading $($File.Name)"
    Invoke-RestMethod -Method POST -Uri $uploadUri -Headers $headers -ContentType 'application/octet-stream' -InFile $File.FullName | Out-Null
}

function Publish-ReleaseAssets {
    param(
        [Parameter(Mandatory = $true)][string]$Repository,
        [Parameter(Mandatory = $true)][string]$ReleaseTag,
        [Parameter(Mandatory = $true)][string]$TorchVersion,
        [Parameter(Mandatory = $true)][string]$AssetsDirectory,
        [Parameter(Mandatory = $true)][string]$Token
    )

    $release = Get-OrCreateRelease -Repository $Repository -ReleaseTag $ReleaseTag -TorchVersion $TorchVersion -Token $Token
    $files = Get-ChildItem -Path $AssetsDirectory -File | Where-Object {
        $_.Extension -eq '.whl' -or $_.Name -eq 'SHA256SUMS.txt'
    } | Sort-Object Name

    foreach ($file in $files) {
        Upload-ReleaseAsset -Release $release -File $file -Repository $Repository -Token $Token
    }
}

$repoRoot = Get-RepoRoot
$latestState = Get-Content -Path (Join-Path $repoRoot 'release-state\latest.json') -Raw | ConvertFrom-Json
$buildMatrix = Get-Content -Path (Join-Path $repoRoot 'config\build_matrix.json') -Raw | ConvertFrom-Json

if (-not $TorchVersion) {
    $TorchVersion = $latestState.torch_version
}
if (-not $ReleaseTag) {
    $ReleaseTag = $latestState.release_tag
}
if (-not $Repository) {
    $Repository = $latestState.workflow_run.repository
}
if (-not $PythonVersions -or $PythonVersions.Count -eq 0) {
    $PythonVersions = @($buildMatrix.python_versions)
}

$buildRoot = Join-Path $repoRoot 'build\local-cuda'
$artifactRoot = Join-Path $buildRoot 'release-assets'
$windowsWorkRoot = Join-Path $buildRoot 'windows-work'
$windowsVenvRoot = Join-Path $buildRoot 'venvs'

New-Item -ItemType Directory -Force -Path $artifactRoot | Out-Null
Get-ChildItem -Path $artifactRoot -File -ErrorAction SilentlyContinue | Remove-Item -Force
New-Item -ItemType Directory -Force -Path $windowsWorkRoot | Out-Null
New-Item -ItemType Directory -Force -Path $windowsVenvRoot | Out-Null

$companionVersions = Resolve-CompanionVersions -TorchVersion $TorchVersion -RepoRoot $repoRoot -PythonVersion $PythonVersions[0]

Write-Step "Local CUDA build plan | target_os=$TargetOs | python_versions=$($PythonVersions -join ',') | torch=$TorchVersion | release_tag=$ReleaseTag | repository=$Repository"

if ($TargetOs -in @('both', 'windows')) {
    Import-VsDevEnvironment

    foreach ($pythonVersion in $PythonVersions) {
        $pyNoDot = $pythonVersion -replace '\.', ''
        $venvPath = Join-Path $windowsVenvRoot "windows-py$pyNoDot"
        $venvPython = Ensure-WindowsVenv -Version $pythonVersion -VenvPath $venvPath -RepoRoot $repoRoot
        $workPath = Join-Path $windowsWorkRoot "py$pyNoDot"
        New-Item -ItemType Directory -Force -Path $workPath | Out-Null

        $command = @(
            $venvPython,
            (Join-Path $repoRoot 'scripts\build_cuda_local.py'),
            '--target-os', 'windows',
            '--python-version', $pythonVersion,
            '--torch-version', $TorchVersion,
            '--torchvision-version', $companionVersions.torchvision_version,
            '--torchaudio-version', $companionVersions.torchaudio_version,
            '--release-tag', $ReleaseTag,
            '--work-root', $workPath,
            '--artifact-root', $artifactRoot
        )
        if ($BootstrapSystemDependencies) {
            $command += '--bootstrap-system-deps'
        }
        Invoke-CommandArray -Command $command -WorkingDirectory $repoRoot
    }
}

if ($TargetOs -in @('both', 'linux')) {
    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
        throw 'WSL2 is required for Linux CUDA builds from Windows.'
    }

    $wslRepoRoot = Convert-WindowsPathToWsl -WindowsPath $repoRoot
    $wslArtifactRoot = Convert-WindowsPathToWsl -WindowsPath $artifactRoot

    foreach ($pythonVersion in $PythonVersions) {
        $pyNoDot = $pythonVersion -replace '\.', ''
        $linuxVenvPath = "$WslWorkRoot/venvs/linux-py$pyNoDot"
        $linuxWorkPath = "$WslWorkRoot/work/linux-py$pyNoDot"
        $bootstrapSuffix = ''
        if ($BootstrapSystemDependencies) {
            $bootstrapSuffix = ' --bootstrap-system-deps'
        }

        $quotedWslRepoRoot = ConvertTo-BashSingleQuoted $wslRepoRoot
        $quotedWslWorkRoot = ConvertTo-BashSingleQuoted $WslWorkRoot
        $quotedWslVenvRoot = ConvertTo-BashSingleQuoted "$WslWorkRoot/venvs"
        $quotedWslBuildRoot = ConvertTo-BashSingleQuoted "$WslWorkRoot/work"
        $quotedLinuxVenvPython = ConvertTo-BashSingleQuoted "$linuxVenvPath/bin/python"
        $quotedLinuxVenvPath = ConvertTo-BashSingleQuoted $linuxVenvPath
        $quotedLinuxWorkPath = ConvertTo-BashSingleQuoted $linuxWorkPath
        $quotedPythonVersion = ConvertTo-BashSingleQuoted $pythonVersion
        $quotedTorchVersion = ConvertTo-BashSingleQuoted $TorchVersion
        $quotedTorchvisionVersion = ConvertTo-BashSingleQuoted $companionVersions.torchvision_version
        $quotedTorchaudioVersion = ConvertTo-BashSingleQuoted $companionVersions.torchaudio_version
        $quotedReleaseTag = ConvertTo-BashSingleQuoted $ReleaseTag
        $quotedWslArtifactRoot = ConvertTo-BashSingleQuoted $wslArtifactRoot

        $commandText = @(
            'set -euo pipefail',
            "cd $quotedWslRepoRoot",
            "mkdir -p $quotedWslWorkRoot $quotedWslVenvRoot $quotedWslBuildRoot",
            "if [ ! -x $quotedLinuxVenvPython ]; then python$pythonVersion -m venv $quotedLinuxVenvPath; fi",
            "$quotedLinuxVenvPython scripts/build_cuda_local.py --target-os linux --python-version $quotedPythonVersion --torch-version $quotedTorchVersion --torchvision-version $quotedTorchvisionVersion --torchaudio-version $quotedTorchaudioVersion --release-tag $quotedReleaseTag --work-root $quotedLinuxWorkPath --artifact-root $quotedWslArtifactRoot$bootstrapSuffix"
        ) -join '; '

        Invoke-WslBash -CommandText $commandText
    }
}

$checksumPath = New-Sha256File -AssetsDirectory $artifactRoot
Write-Step "Generated checksums at $checksumPath"

if (-not $SkipUpload) {
    $token = Get-GitHubToken -ExplicitToken $GitHubToken
    Publish-ReleaseAssets -Repository $Repository -ReleaseTag $ReleaseTag -TorchVersion $TorchVersion -AssetsDirectory $artifactRoot -Token $token
    Write-Step 'Release upload completed'
}
else {
    Write-Step 'Skipping release upload by request'
}

Write-Step 'Local CUDA build workflow completed'