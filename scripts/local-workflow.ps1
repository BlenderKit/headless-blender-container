param(
    [string]$PythonExe = "python",
    [string]$Registry = "docker.io",
    [string]$Runtime = "docker",
    [string]$StartVersion,
    [switch]$SkipDependencyInstall,
    [switch]$PushImages
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptRoot
Push-Location $repoRoot
try {

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message" -ForegroundColor Cyan
}

    if (-not $env:MIN_FREE_GB) {
        $env:MIN_FREE_GB = "12"
    }
    $env:DOCKER_REGISTRY = $Registry
    $env:CONTAINER_RUNTIME = $Runtime
    Write-Step "Validating container runtime '$Runtime'"
    $runtimeCmd = Get-Command $Runtime -ErrorAction SilentlyContinue
    if (-not $runtimeCmd) {
        throw "Container runtime '$Runtime' not found in PATH. Install Docker Desktop or Podman and retry."
    }
    try {
        $runtimeInfo = & $Runtime --version 2>$null
        if (-not $runtimeInfo) {
            $runtimeInfo = & $Runtime version 2>$null
        }
        Write-Host $runtimeInfo
    } catch {
        throw "Failed to execute '$Runtime --version'. Ensure $Runtime is installed correctly."
    }
    $isDocker = $Runtime -match 'docker'
    if ($isDocker -and ($runtimeInfo -notmatch 'Docker')) {
        Write-Warning "Runtime '$Runtime' does not appear to be Docker. Output: $runtimeInfo"
    }
    if (-not $PushImages) {
        $env:SKIP_IMAGE_PUSH = "1"
        Write-Step "Image push disabled for local run"
    } else {
        Write-Step "Image push ENABLED"
    }
    if ($StartVersion) {
        $env:START_VERSION = $StartVersion
        Write-Step "Starting build at version $StartVersion"
    }

    Write-Step "Disk snapshot"
    $driveLetter = (Get-Location).Path.Substring(0,1)
    $drive = Get-PSDrive -Name $driveLetter -ErrorAction Stop
    $driveInfo = Get-CimInstance -ClassName Win32_LogicalDisk -Filter "DeviceID='$($driveLetter):'"
    if (-not $driveInfo) {
        throw "Unable to read disk information for ${driveLetter}:"
    }
    $sizeBytes = if ($driveInfo.Size) { $driveInfo.Size } else { throw "Unable to determine size of drive ${driveLetter}:" }
    $totalGB = [math]::Round($sizeBytes / 1GB, 2)
    $freeGB = [math]::Round($driveInfo.FreeSpace / 1GB, 2)
    $minFree = [double]$env:MIN_FREE_GB
    Write-Host ("Drive {0}: total {1:N1} GB | free {2:N1} GB" -f $driveLetter, $totalGB, $freeGB)
    if ($freeGB -lt $minFree) {
        throw "Free space ${freeGB} GB is below required ${minFree} GB"
    }

    if (-not $SkipDependencyInstall) {
        Write-Step "Installing Python requirements"
        & $PythonExe -m pip install --upgrade pip
        & $PythonExe -m pip install -r requirements.txt
    }

    Write-Step "Printing docker info"
    & $Runtime info | Out-Host

    Write-Step "Running build.py"
    & $PythonExe (Join-Path $repoRoot 'build.py')
}
finally {
    Pop-Location
}
