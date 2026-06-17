param(
    [ValidateSet("", "mock", "gmail", "outlook")]
    [string]$Provider = "",
    [int]$PollSeconds = 0,
    [int]$BatchSize = 1,
    [int]$Limit = 10,
    [string]$SelectedModel = "",
    [string]$BaseUrl = "",
    [switch]$DryRun,
    [switch]$Force,
    [switch]$RunOnce,
    [switch]$EnsureUvSync,
    [string]$LogDirectory = ""
)

$ErrorActionPreference = "Stop"

function Stop-WithMessage {
    param([string]$Message)
    Write-Host "STOP: $Message" -ForegroundColor Red
    exit 1
}

function Get-EnvValueFromFile {
    param(
        [string]$Path,
        [string]$Name
    )
    if (-not (Test-Path $Path)) {
        return ""
    }
    $match = Select-String -Path $Path -Pattern "^\s*$([regex]::Escape($Name))\s*=\s*(.+?)\s*$" | Select-Object -First 1
    if (-not $match) {
        return ""
    }
    return $match.Matches[0].Groups[1].Value.Trim().Trim('"').Trim("'")
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$envFile = Join-Path $repoRoot ".env"
$resolvedProvider = $Provider.Trim()
if (-not $resolvedProvider) {
    $resolvedProvider = Get-EnvValueFromFile -Path $envFile -Name "MAILASSIST_DEFAULT_PROVIDER"
}
if (-not $resolvedProvider) {
    Stop-WithMessage "No provider was supplied and .env does not set MAILASSIST_DEFAULT_PROVIDER."
}
if ($resolvedProvider -notin @("mock", "gmail", "outlook")) {
    Stop-WithMessage "Unsupported provider '$resolvedProvider'. Use mock, gmail, or outlook."
}
if ($resolvedProvider -ne "mock" -and -not (Test-Path $envFile)) {
    Stop-WithMessage "Missing .env. Configure provider settings before running the real bot."
}

if ($EnsureUvSync -and -not (Test-Path ".venv\Scripts\mailassist.exe")) {
    if (-not (Get-Command "uv" -ErrorAction SilentlyContinue)) {
        Stop-WithMessage "uv is required to create .venv, but uv was not found."
    }
    Write-Host "Creating MailAssist Python 3.12 environment..."
    & uv venv --python 3.12 .venv
    if ($LASTEXITCODE -ne 0) {
        Stop-WithMessage "uv venv failed."
    }
    Write-Host "Syncing MailAssist Python environment..."
    & uv sync
    if ($LASTEXITCODE -ne 0) {
        Stop-WithMessage "uv sync failed."
    }
}

$mailassist = Join-Path $repoRoot ".venv\Scripts\mailassist.exe"
if (-not (Test-Path $mailassist)) {
    Stop-WithMessage "MailAssist executable not found at $mailassist. Run 'uv sync' first, or rerun this script with -EnsureUvSync."
}

$logDir = $LogDirectory.Trim()
if (-not $logDir) {
    $logDir = Join-Path $repoRoot "data\service-logs"
}
if (-not [System.IO.Path]::IsPathRooted($logDir)) {
    $logDir = Join-Path $repoRoot $logDir
}
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$action = if ($RunOnce) { "watch-once" } else { "watch-loop" }
$logFile = Join-Path $logDir "mailassist-$action-$resolvedProvider-$timestamp.log"

$mailassistArgs = @(
    "review-bot",
    "--action", $action,
    "--provider", $resolvedProvider,
    "--batch-size", ([Math]::Max(1, $BatchSize)).ToString(),
    "--limit", ([Math]::Max(1, $Limit)).ToString()
)
if ($PollSeconds -gt 0) {
    $mailassistArgs += @("--poll-seconds", $PollSeconds.ToString())
}
if ($SelectedModel.Trim()) {
    $mailassistArgs += @("--selected-model", $SelectedModel.Trim())
}
if ($BaseUrl.Trim()) {
    $mailassistArgs += @("--base-url", $BaseUrl.Trim())
}
if ($DryRun) {
    $mailassistArgs += "--dry-run"
}
if ($Force) {
    $mailassistArgs += "--force"
}

Write-Host "Starting MailAssist bot"
Write-Host "Workspace: $repoRoot"
Write-Host "Provider:  $resolvedProvider"
Write-Host "Action:    $action"
Write-Host "Dry run:   $([bool]$DryRun)"
Write-Host "Log file:  $logFile"
Write-Host ""

& $mailassist @mailassistArgs *> $logFile
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    Write-Host "MailAssist bot exited with code $exitCode. Last log lines:" -ForegroundColor Yellow
    if (Test-Path $logFile) {
        Get-Content $logFile -Tail 20
    }
} else {
    Write-Host "MailAssist bot exited cleanly."
}
exit $exitCode
