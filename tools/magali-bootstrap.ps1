param(
    [string]$ClientId = "2b2639c3-605c-466d-ae89-63ef8ffff5c8",
    [string]$TenantId = "organizations",
    [string]$ExpectedEmail = "MagaliDomingue@goldenyearstaxstrategy.com",
    [string]$Model = "qwen3:8b",
    [string]$InstallRoot = "$env:USERPROFILE\Downloads",
    [switch]$SkipDownload
)

$ErrorActionPreference = "Stop"

function Stop-WithMessage {
    param([string]$Message)
    Write-Host ""
    Write-Host "STOP: $Message" -ForegroundColor Red
    exit 1
}

function Ensure-Uv {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        return
    }

    Write-Host "Installing uv..."
    powershell -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    $uvBin = Join-Path $env:USERPROFILE ".local\bin"
    $env:Path = "$uvBin;$env:Path"

    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Stop-WithMessage "uv was installed but is not on PATH yet. Close and reopen PowerShell, then rerun this command."
    }
}

Write-Host "MailAssist Magali bootstrap"
Write-Host "This downloads MailAssist, installs uv/Python if needed, and runs safe readiness checks."
Write-Host "It will not create drafts or send email."
Write-Host ""

if (-not $ClientId.Trim()) {
    Stop-WithMessage "ClientId is required."
}

$zipPath = Join-Path $InstallRoot "MailAssist.zip"
$repoPath = Join-Path $InstallRoot "MailAssist-main"

if (-not $SkipDownload) {
    New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
    if (Test-Path $zipPath) {
        Remove-Item $zipPath -Force
    }
    if (Test-Path $repoPath) {
        Remove-Item $repoPath -Recurse -Force
    }

    Write-Host "Downloading MailAssist from GitHub..."
    Invoke-WebRequest `
        -Uri "https://github.com/ec92009/MailAssist/archive/refs/heads/main.zip" `
        -OutFile $zipPath

    Write-Host "Extracting MailAssist..."
    Expand-Archive $zipPath -DestinationPath $InstallRoot -Force
}

if (-not (Test-Path $repoPath)) {
    Stop-WithMessage "MailAssist folder was not found at $repoPath"
}

Set-Location $repoPath

Ensure-Uv

Write-Host "Installing Python 3.12 through uv if needed..."
uv python install 3.12

Write-Host "Syncing MailAssist environment..."
uv sync --python 3.12

Write-Host "Running Magali readiness checks..."
PowerShell -ExecutionPolicy Bypass -File .\tools\magali-readiness.ps1 `
    -ClientId $ClientId `
    -TenantId $TenantId `
    -ExpectedEmail $ExpectedEmail `
    -Model $Model `
    -SkipSync
