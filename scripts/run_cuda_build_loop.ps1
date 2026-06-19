[CmdletBinding()]
param(
    [ValidateSet('both', 'windows', 'linux')]
    [string]$TargetOs = 'both',

    [string[]]$PythonVersions = @('3.13'),

    [string]$WslDistro = 'Ubuntu-24.04',

    [int]$MaxAttempts = 50
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$logRoot = Join-Path $repoRoot 'build\local-cuda\logs'
$stateFile = Join-Path $repoRoot 'build\local-cuda\build-state.json'
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null

function Write-Log {
    param([string]$Message)
    $timestamp = [DateTime]::UtcNow.ToString('s') + 'Z'
    $line = "[$timestamp] $Message"
    Write-Host $line
    Add-Content -Path (Join-Path $logRoot 'loop.log') -Value $line -Encoding utf8
}

function Get-BuildState {
    if (-not (Test-Path $stateFile)) {
        return @{
            windows_success = $false
            linux_success = $false
            windows_attempts = 0
            linux_attempts = 0
            last_windows_error = ''
            last_linux_error = ''
        }
    }
    return (Get-Content -Path $stateFile -Raw | ConvertFrom-Json)
}

function Set-BuildState {
    param($State)
    $State | ConvertTo-Json -Depth 5 | Set-Content -Path $stateFile -Encoding utf8
}

function New-BuildResult {
    param(
        [bool]$Success,
        [string]$LogFile = '',
        [string]$ErrorSummary = ''
    )
    return [PSCustomObject]@{
        success = $Success
        log_file = $LogFile
        error_summary = $ErrorSummary
    }
}

function Test-WheelsPresent {
    param(
        [Parameter(Mandatory = $true)][string]$PlatformPrefix
    )

    $artifactRoot = Join-Path $repoRoot 'build\local-cuda\release-assets'
    if (-not (Test-Path $artifactRoot)) {
        return $false
    }

    $patterns = @(
        "torch-*-$PlatformPrefix*.whl",
        "torchvision-*-$PlatformPrefix*.whl",
        "torchaudio-*-$PlatformPrefix*.whl"
    )

    foreach ($pattern in $patterns) {
        $matches = Get-ChildItem -Path $artifactRoot -Filter $pattern -ErrorAction SilentlyContinue
        if (-not $matches) {
            return $false
        }
    }
    return $true
}

function Invoke-PlatformBuild {
    param(
        [Parameter(Mandatory = $true)][string]$Platform,
        [Parameter(Mandatory = $true)][int]$Attempt
    )

    $timestamp = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss')
    $logFile = Join-Path $logRoot "$Platform-attempt$Attempt-$timestamp.log"
    Write-Log "Starting $Platform build attempt $Attempt (log: $logFile)"

    $buildArgs = @(
        '-TargetOs', $Platform,
        '-SkipUpload'
    )
    foreach ($pythonVersion in $PythonVersions) {
        $buildArgs += @('-PythonVersions', $pythonVersion)
    }

    if ($Platform -eq 'linux' -and $WslDistro) {
        $buildArgs += @('-WslDistro', $WslDistro)
    }

    $buildScript = Join-Path $repoRoot 'scripts\build_cuda_local.ps1'
    $exitCode = 0
    $ErrorActionPreference = 'Continue'
    try {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $buildScript @buildArgs 2>&1 | Tee-Object -FilePath $logFile
        if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) {
            $exitCode = $LASTEXITCODE
        }
    }
    catch {
        $exitCode = 1
        Add-Content -Path $logFile -Value $_.Exception.Message -Encoding utf8
    }
    $ErrorActionPreference = 'Stop'

    if ($exitCode -ne 0) {
        $tail = @()
        if (Test-Path $logFile) {
            $tail = Get-Content -Path $logFile -Tail 40 -ErrorAction SilentlyContinue
        }
        $errorSummary = ($tail -join "`n")
        Write-Log "$Platform build attempt $Attempt failed with exit code $exitCode"
        return (New-BuildResult -Success $false -LogFile $logFile -ErrorSummary $errorSummary)
    }

    $prefix = if ($Platform -eq 'windows') { 'win_amd64' } else { 'linux_x86_64' }
    if (-not (Test-WheelsPresent -PlatformPrefix $prefix)) {
        if ($Platform -eq 'linux') {
            Start-Sleep -Seconds 5
            if (Test-WheelsPresent -PlatformPrefix $prefix) {
                Write-Log "$Platform build attempt $Attempt succeeded after artifact sync"
                return (New-BuildResult -Success $true -LogFile $logFile)
            }
        }
        Write-Log "$Platform build exited 0 but expected wheels were not found"
        return (New-BuildResult -Success $false -LogFile $logFile -ErrorSummary 'Build script completed but wheels are missing from release-assets')
    }

    Write-Log "$Platform build attempt $Attempt succeeded"
    return (New-BuildResult -Success $true -LogFile $logFile)
}

$state = Get-BuildState
Write-Log "CUDA build loop started | target_os=$TargetOs | max_attempts=$MaxAttempts"

for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
    $linuxBuildResult = $null
    if ($TargetOs -in @('both', 'windows') -and -not $state.windows_success) {
        $state.windows_attempts++
        $result = $null
        try {
            $result = Invoke-PlatformBuild -Platform 'windows' -Attempt $state.windows_attempts
        }
        catch {
            Write-Log "windows build attempt $($state.windows_attempts) crashed: $($_.Exception.Message)"
            $result = New-BuildResult -Success $false -ErrorSummary $_.Exception.Message
        }
        if ($null -ne $result -and ($result -is [pscustomobject]) -and $result.success) {
            $state.windows_success = $true
        }
        elseif ($null -ne $result -and ($result -is [pscustomobject])) {
            $state.last_windows_error = $result.error_summary
        }
        Set-BuildState $state
    }

    if ($TargetOs -in @('both', 'linux') -and -not $state.linux_success) {
        $state.linux_attempts++
        $linuxBuildResult = $null
        try {
            $linuxBuildResult = Invoke-PlatformBuild -Platform 'linux' -Attempt $state.linux_attempts
        }
        catch {
            Write-Log "linux build attempt $($state.linux_attempts) crashed: $($_.Exception.Message)"
            $linuxBuildResult = New-BuildResult -Success $false -ErrorSummary $_.Exception.Message
        }
        if ($null -ne $linuxBuildResult -and ($linuxBuildResult -is [pscustomobject]) -and $linuxBuildResult.success) {
            $state.linux_success = $true
        }
        elseif ($null -ne $linuxBuildResult -and ($linuxBuildResult -is [pscustomobject])) {
            $state.last_linux_error = $linuxBuildResult.error_summary
        }
        Set-BuildState $state
    }

    $retryDelaySeconds = 120
    $linuxMissingWheelsOnly = $false
    if ($TargetOs -in @('both', 'linux') -and -not $state.linux_success -and $state.linux_attempts -gt 0) {
        if ($null -ne $linuxBuildResult -and ($linuxBuildResult -is [pscustomobject]) -and -not $linuxBuildResult.success) {
            $linuxMissingWheelsOnly = $linuxBuildResult.error_summary -like '*wheels are missing from release-assets*'
        }
    }
    if ($TargetOs -in @('both', 'linux') -and -not $state.linux_success -and $state.linux_attempts -gt 0 -and -not $linuxMissingWheelsOnly) {
        $retryDelaySeconds = 180
        Write-Log "Waiting ${retryDelaySeconds}s before next linux retry (cooldown after WSL/OOM failure)"
        try {
            wsl.exe --shutdown | Out-Null
            Start-Sleep -Seconds 15
        }
        catch {
            Write-Log "WSL shutdown during cooldown failed: $($_.Exception.Message)"
        }
    }

    $windowsDone = ($TargetOs -eq 'linux') -or $state.windows_success
    $linuxDone = ($TargetOs -eq 'windows') -or $state.linux_success

    if ($windowsDone -and $linuxDone) {
        Write-Log 'All requested CUDA builds completed successfully'
        $artifactRoot = Join-Path $repoRoot 'build\local-cuda\release-assets'
        Get-ChildItem -Path $artifactRoot -Filter '*.whl' | ForEach-Object {
            Write-Log "  wheel: $($_.Name) ($([math]::Round($_.Length / 1GB, 2)) GB)"
        }
        exit 0
    }

    Write-Log "Loop iteration $attempt complete | windows=$($state.windows_success) | linux=$($state.linux_success)"
    Start-Sleep -Seconds $retryDelaySeconds
}

Write-Log 'Reached maximum attempts without completing all builds'
exit 1
